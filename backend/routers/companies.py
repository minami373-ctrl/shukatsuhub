"""選考ステータス管理ボード API（`03-today-focus/FEATURE_PAGE_SPECS.md` §7）。

GET   /api/pipeline                … 5列カンバン（気になる / エントリー / 書類選考 / 面接 / 最終・内定）
POST  /api/matching                … 企業の発見・マッチング（§5.9。AI は使わない）
GET   /api/companies/suggestions   … 受信箱からの企業登録の提案（§5.11）
POST  /api/companies/from-emails   … 提案されたドメインを企業として登録（§5.11）
POST  /api/companies               … 企業を追加
PATCH /api/companies/{id}          … 選考段階の変更（列の移動）ほか

カードに出す状態タグ（`ES 本日` / `今日 15:00` / `結果待ち N日`）は**保存しない**。
その企業の `Task.due_at` と `Event.start_at` から導出する（`docs/spec.md` §6 の注記）。
推測でひも付けないため、紐づくタスクも予定も無い企業はタグ無しで返す。
"""

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field, field_validator
from sqlmodel import Session, select

from db import get_session
from models import PROFILE_ID, Company, Email, Event, Profile, Task
from services import company_source, grouping, matching
from services.freetime import resolve_day, resolve_now

router = APIRouter(prefix="/api", tags=["pipeline"])

#: 選考段階。`docs/spec.md` §6 の stage。カンバンの列と1対1に対応させる
Stage = Literal["気になる", "エントリー", "書類選考", "面接", "最終・内定"]

#: 列の並び。FEATURE_PAGE_SPECS.md §7 の順序をそのまま使う
STAGES: tuple[Stage, ...] = ("気になる", "エントリー", "書類選考", "面接", "最終・内定")

#: 「選考中」に数える段階（ヘッダの `選考中 N社`）。気になるは応募していないので除く
IN_PROGRESS_STAGES = ("エントリー", "書類選考", "面接")

NAME_MAX = 80
DOMAIN_MAX = 120

#: 年収（万円）と年間休日（日）の入力範囲。桁を打ち間違えた値がマッチ率に混ざらないようにする
SALARY_MAX = 9999
HOLIDAYS_MAX = 365


class CompanyCard(BaseModel):
    """カンバンのカード1枚。next_* は導出値なので保存しない。"""

    id: int
    name: str
    domain: str
    stage: str
    is_watched: bool
    #: マッチング用（§5.9）。編集フォームの初期値にも使う
    job_type: str | None
    location: str | None
    remote_ok: bool
    tags: str | None
    #: 想定年収の下限（万円）と年間休日（日）。未登録は None＝マッチ率で合致しない
    salary_min: int | None
    holidays_per_year: int | None
    #: 直近の未完了タスクの締切（無ければ None）
    next_task_at: datetime | None
    next_task_label: str | None
    #: 直近の予定（無ければ None）
    next_event_at: datetime | None
    next_event_title: str | None


class PipelineColumn(BaseModel):
    stage: str
    count: int
    companies: list[CompanyCard]


class PipelineCounts(BaseModel):
    """ページヘッダの `24社・選考中 18社・内定 1社`（§7）。"""

    total: int
    in_progress: int
    offer: int


class PipelineResponse(BaseModel):
    #: 緊急度の色帯（当日 / 3日以内）の判定に使う基準時刻
    now: datetime
    counts: PipelineCounts
    columns: list[PipelineColumn]


#: 期限の名前を省略したときの既定。カードとタスク一覧の両方でこの文言が出る
DEFAULT_DEADLINE_LABEL = "選考の締切"


class CompanyCreate(BaseModel):
    name: str = Field(max_length=NAME_MAX)
    domain: str = Field(max_length=DOMAIN_MAX)
    stage: Stage = "気になる"
    is_watched: bool = True
    #: マッチング用（§5.9）。空なら「未登録」＝その条件では合致しない
    job_type: str | None = Field(default=None, max_length=60)
    location: str | None = Field(default=None, max_length=60)
    remote_ok: bool = False
    tags: str | None = Field(default=None, max_length=200)
    #: 年収・休日は AI に生成させない。人が入力した値だけを保存する（§5.9）
    salary_min: int | None = Field(default=None, ge=0, le=SALARY_MAX)
    holidays_per_year: int | None = Field(default=None, ge=0, le=HOLIDAYS_MAX)
    #: 次の締切。渡されたら Task として登録する（Company に期限カラムを持たない理由は
    #: docs/spec.md §6 の注記を参照。カードの状態タグは Task.due_at から導出している）
    deadline_at: datetime | None = None
    #: 締切の名前（例「ES提出」）。省略時は DEFAULT_DEADLINE_LABEL
    deadline_label: str | None = Field(default=None, max_length=40)
    #: 締切タスクの見積り分。空き時間の算出に効く（spec.md §5.3）
    deadline_estimate_min: int = Field(default=30, ge=0)

    @field_validator("deadline_label")
    @classmethod
    def _label_blank_to_none(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None

    @field_validator("name", "domain")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("空にできません")
        return stripped

    @field_validator("domain")
    @classmethod
    def _host_only(cls, value: str) -> str:
        """`@` を含めない（spec.md §6「ホスト部のみ」）。"""
        if "@" in value:
            raise ValueError("ドメインは @ を含めずホスト部のみを入れてください")
        return value.lower()


class CompanyPatch(BaseModel):
    """列の移動（stage の変更）が主な用途。渡された項目だけを更新する。

    マッチング用の3項目（§5.9）もここから編集できる。空文字を渡すと「未登録」に戻せる
    （未登録の項目はマッチ率で合致しない扱いになる）。
    """

    name: str | None = Field(default=None, max_length=NAME_MAX)
    stage: Stage | None = None
    is_watched: bool | None = None
    job_type: str | None = Field(default=None, max_length=60)
    location: str | None = Field(default=None, max_length=60)
    remote_ok: bool | None = None
    #: カンマ区切りの特徴タグ。就活軸との照合に使う
    tags: str | None = Field(default=None, max_length=200)
    #: 年収（万円）と年間休日（日）。null を渡すと「未登録」に戻せる
    salary_min: int | None = Field(default=None, ge=0, le=SALARY_MAX)
    holidays_per_year: int | None = Field(default=None, ge=0, le=HOLIDAYS_MAX)

    @field_validator("name")
    @classmethod
    def _not_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("空にできません")
        return stripped


def _next_task(session: Session, company_id: int) -> Task | None:
    """その企業の未完了タスクのうち締切が最も近いもの。"""
    statement = (
        select(Task)
        .where(Task.company_id == company_id, Task.is_done == False)  # noqa: E712
        .order_by(Task.due_at, Task.id)
        .limit(1)
    )
    return session.exec(statement).first()


def _next_event(session: Session, company_id: int, now: datetime) -> Event | None:
    """その企業の予定のうち、基準時刻以降で最も近いもの。"""
    statement = (
        select(Event)
        .where(Event.company_id == company_id, Event.start_at >= now)
        .order_by(Event.start_at, Event.id)
        .limit(1)
    )
    return session.exec(statement).first()


def _to_card(session: Session, company: Company, now: datetime) -> CompanyCard:
    task = _next_task(session, company.id or 0)
    event = _next_event(session, company.id or 0, now)
    return CompanyCard(
        id=company.id or 0,
        name=company.name,
        domain=company.domain,
        stage=company.stage,
        is_watched=company.is_watched,
        job_type=company.job_type,
        location=company.location,
        remote_ok=company.remote_ok,
        tags=company.tags,
        salary_min=company.salary_min,
        holidays_per_year=company.holidays_per_year,
        next_task_at=task.due_at if task else None,
        next_task_label=(task.short_label or task.title) if task else None,
        next_event_at=event.start_at if event else None,
        next_event_title=event.title if event else None,
    )


@router.get("/pipeline", response_model=PipelineResponse)
def get_pipeline(
    day: str | None = Query(default=None, alias="date", description="対象日（省略時は seed の基準日）"),
    session: Session = Depends(get_session),
) -> PipelineResponse:
    """5列カンバンをまとめて返す（§7）。

    列は STAGES の順に必ず5つ返す（空の列も返す。画面側で列が消えないようにするため）。
    """
    target = resolve_day(datetime.fromisoformat(day).date() if day else None)
    now = resolve_now(target)

    companies = list(session.exec(select(Company).order_by(Company.name, Company.id)))
    by_stage: dict[str, list[Company]] = {stage: [] for stage in STAGES}
    for company in companies:
        # 想定外の段階が入っていても落とさず「気になる」に寄せる（画面が消えないことを優先）
        by_stage.setdefault(company.stage, by_stage["気になる"]).append(company)

    return PipelineResponse(
        now=now,
        counts=PipelineCounts(
            total=len(companies),
            in_progress=sum(1 for c in companies if c.stage in IN_PROGRESS_STAGES),
            offer=sum(1 for c in companies if c.stage == "最終・内定"),
        ),
        columns=[
            PipelineColumn(
                stage=stage,
                count=len(by_stage[stage]),
                companies=[_to_card(session, c, now) for c in by_stage[stage]],
            )
            for stage in STAGES
        ],
    )


class MatchRequest(BaseModel):
    """テンプレ質問の回答（§5.9）。すべて任意。全部空なら 422 にする。"""

    job_type: str | None = Field(default=None, max_length=60)
    location: str | None = Field(default=None, max_length=60)
    remote_only: bool = False
    #: 希望年収の下限（万円）と希望する年間休日の下限（日）。null なら条件に数えない
    salary_min: int | None = Field(default=None, ge=0, le=SALARY_MAX)
    holidays_min: int | None = Field(default=None, ge=0, le=HOLIDAYS_MAX)
    #: 就活軸。省略時はプロフィールの job_axis を使う
    axes: list[str] | None = Field(default=None, max_length=20)
    #: おすすめ / 条件検索 / 気になる のセグメント（§7 のフィルタ）
    scope: Literal["recommended", "search", "watched"] = "recommended"


class MatchedCompany(BaseModel):
    id: int
    name: str
    domain: str
    stage: str
    is_watched: bool
    job_type: str | None
    location: str | None
    remote_ok: bool
    #: 企業側の登録値。画面に並記して、マッチ率の根拠を目で照合できるようにする（§5.9）
    salary_min: int | None
    holidays_per_year: int | None
    #: 0〜100。プログラム計算（AI は使わない）
    rate: int
    #: 合致した条件だけ。合致しなかったものは入れない
    reasons: list[str]


class MatchResponse(BaseModel):
    #: 企業一覧の取得元。実データ移行後は 'api' などになる（§5.10）
    source: str
    #: 使った就活軸（プロフィール由来か、画面で指定されたもの）
    axes: list[str]
    #: マッチ率が閾値以上の件数（ページヘッダの `おすすめ N社`）
    recommended_count: int
    #: 絞り込み前の全企業数（`条件に合致 N社` の母数）
    total_count: int
    items: list[MatchedCompany]


#: 「おすすめ」に出す下限。§7 は 70% 以上をティール、90% 以上を緑で色分けするので下限を 70 にする
RECOMMEND_THRESHOLD = 70


@router.post("/matching", response_model=MatchResponse)
def match_companies(body: MatchRequest, session: Session = Depends(get_session)) -> MatchResponse:
    """条件に合う企業をマッチ率つきで返す（§5.9）。

    **AI は使わない。**同じ条件なら常に同じ結果になる。
    企業一覧の取得元は `services/company_source.py` に集約してあり、
    実データへ移行するときはそこだけを差し替える（§5.10）。
    """
    axes = body.axes
    if axes is None:
        # 省略時はプロフィールの就活軸を使う。未入力なら空（条件に数えない）
        profile = session.get(Profile, PROFILE_ID)
        axes = matching.split_csv(profile.job_axis if profile else None)
    axes = [a.strip() for a in axes if a.strip()]

    criteria = matching.MatchCriteria(
        job_type=body.job_type,
        location=body.location,
        remote_only=body.remote_only,
        salary_min=body.salary_min,
        holidays_min=body.holidays_min,
        axes=tuple(axes),
    )
    if not criteria.has_any:
        raise HTTPException(status_code=422, detail="条件を1つ以上指定してください")

    companies, source = company_source.fetch_companies(session)

    items: list[MatchedCompany] = []
    for company in companies:
        result = matching.match(
            criteria,
            matching.MatchTarget(
                job_type=company.job_type,
                location=company.location,
                remote_ok=company.remote_ok,
                salary_min=company.salary_min,
                holidays_per_year=company.holidays_per_year,
                tags=company.tags,
            ),
        )
        items.append(
            MatchedCompany(
                id=company.id or 0,
                name=company.name,
                domain=company.domain,
                stage=company.stage,
                is_watched=company.is_watched,
                job_type=company.job_type,
                location=company.location,
                remote_ok=company.remote_ok,
                salary_min=company.salary_min,
                holidays_per_year=company.holidays_per_year,
                rate=result.rate,
                reasons=result.reasons,
            )
        )

    recommended = [i for i in items if i.rate >= RECOMMEND_THRESHOLD]

    if body.scope == "recommended":
        shown = recommended
    elif body.scope == "watched":
        shown = [i for i in items if i.is_watched]
    else:
        # 条件検索：1つでも合致した企業だけ出す。0% を並べても選べない
        shown = [i for i in items if i.rate > 0]

    # マッチ率の高い順。同率は企業名順にして並びが毎回変わらないようにする
    shown.sort(key=lambda i: (-i.rate, i.name))

    return MatchResponse(
        source=source,
        axes=axes,
        recommended_count=len(recommended),
        total_count=len(items),
        items=shown,
    )


class CompanySuggestion(BaseModel):
    """受信箱から見つけた企業の登録候補（§5.11）。"""

    domain: str
    #: 送信者表示名の最頻値。ドメインから企業名を推測はしない。登録後に名前を直せる
    suggested_name: str
    email_count: int
    latest_received_at: datetime
    categories: list[str]


class SuggestionResponse(BaseModel):
    items: list[CompanySuggestion]


@router.get("/companies/suggestions", response_model=SuggestionResponse)
def get_company_suggestions(session: Session = Depends(get_session)) -> SuggestionResponse:
    """未登録ドメインからの受信メールを、企業の登録候補として返す（§5.11）。

    **AI もスクレイピングも使わない。**既に受信しているメールだけを材料にする。
    候補が0件なら空配列（エラーにしない）。
    """
    emails = list(session.exec(select(Email)))
    companies = list(session.exec(select(Company)))
    return SuggestionResponse(
        items=[
            CompanySuggestion(**vars(s)) for s in company_source.suggest_from_emails(emails, companies)
        ]
    )


class FromEmailsRequest(BaseModel):
    #: 登録するドメイン（提案に出たもの）。登録済みのドメインは黙って読み飛ばす
    domains: list[str] = Field(min_length=1, max_length=50)


class FromEmailsResponse(BaseModel):
    #: 実際に作られた企業。画面で「条件が未登録」と促すために返す
    created: list[CompanyCard]
    #: 既に登録済みで読み飛ばしたドメイン
    skipped: list[str]
    #: 企業に紐づけ直したメールの件数（受信箱の表示が企業名に変わる）
    linked_emails: int


@router.post(
    "/companies/from-emails",
    response_model=FromEmailsResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_companies_from_emails(
    body: FromEmailsRequest, session: Session = Depends(get_session)
) -> FromEmailsResponse:
    """提案されたドメインを企業として登録する（§5.11）。

    **メールから分かるのはドメインと送信者表示名だけ**なので、職種・勤務地・リモート可否・
    年収・休日・タグは**未登録のまま作る**（推測で埋めない。`CLAUDE.md` §E）。
    未登録の項目はマッチ率で合致しない扱いになるので、条件は人が企業ダイアログで入れる。

    作成後、そのドメインの既存メールの `company_id` を埋め直す。
    """
    emails = list(session.exec(select(Email)))
    known = list(session.exec(select(Company)))
    suggestions = {s.domain: s for s in company_source.suggest_from_emails(emails, known)}
    existing = {c.domain for c in known}

    created: list[Company] = []
    skipped: list[str] = []
    for raw in body.domains:
        domain = raw.strip().lower()
        if not domain or domain in existing:
            skipped.append(raw)
            continue
        suggestion = suggestions.get(domain)
        if suggestion is None:
            # 提案に無いドメインは受け付けない（候補の根拠が無いものを企業にしない）
            raise HTTPException(status_code=422, detail=f"{raw} は登録候補にありません")
        company = Company(
            name=suggestion.suggested_name[:NAME_MAX],
            domain=domain[:DOMAIN_MAX],
            stage="気になる",
            is_watched=True,
        )
        session.add(company)
        existing.add(domain)
        created.append(company)

    if not created:
        return FromEmailsResponse(created=[], skipped=skipped, linked_emails=0)

    session.commit()
    for company in created:
        session.refresh(company)

    # 既存メールの紐づけを埋め直す。thread_key も企業 ID 基準に作り直す（§5.2）
    all_companies = list(session.exec(select(Company)))
    linked = 0
    for email in emails:
        if email.company_id is not None:
            continue
        company_id = grouping.resolve_company_id(email.from_address, all_companies)
        if company_id is None:
            continue
        email.company_id = company_id
        email.thread_key = grouping.build_thread_key(
            email.from_address, email.subject, all_companies
        )
        session.add(email)
        linked += 1
    session.commit()

    now = resolve_now(resolve_day(None))
    return FromEmailsResponse(
        created=[_to_card(session, c, now) for c in created],
        skipped=skipped,
        linked_emails=linked,
    )


@router.post("/companies", response_model=CompanyCard, status_code=status.HTTP_201_CREATED)
def create_company(body: CompanyCreate, session: Session = Depends(get_session)) -> CompanyCard:
    """企業を追加する（§7「＋ 企業を追加」）。

    このボードは「その日に動きがある選考」ではなく**すべての選考**を管理する。
    締切を渡された場合は `Task` として一緒に登録し、カードに状態タグが出るようにする。
    Company に期限カラムを持たせないのは、同じ意味の期限が Task と2箇所に分かれるのを
    避けるため（カードの状態タグは Task.due_at から導出する。docs/spec.md §6）。
    """
    exists = session.exec(select(Company).where(Company.domain == body.domain)).first()
    if exists is not None:
        raise HTTPException(status_code=422, detail="そのドメインの企業は既に登録されています")

    company = Company(
        name=body.name,
        domain=body.domain,
        stage=body.stage,
        is_watched=body.is_watched,
        job_type=body.job_type,
        location=body.location,
        remote_ok=body.remote_ok,
        tags=body.tags,
        salary_min=body.salary_min,
        holidays_per_year=body.holidays_per_year,
    )
    session.add(company)
    session.commit()
    session.refresh(company)

    if body.deadline_at is not None:
        label = body.deadline_label or DEFAULT_DEADLINE_LABEL
        session.add(
            Task(
                title=f"{company.name} {label}",
                short_label=label,
                due_at=body.deadline_at,
                estimate_min=body.deadline_estimate_min,
                company_id=company.id,
            )
        )
        session.commit()

    return _to_card(session, company, resolve_now(resolve_day(None)))


@router.patch("/companies/{company_id}", response_model=CompanyCard)
def update_company(
    company_id: int,
    body: CompanyPatch,
    session: Session = Depends(get_session),
) -> CompanyCard:
    """選考段階を変える（カードを別の列へ移す）。渡された項目だけを更新する。"""
    company = session.get(Company, company_id)
    if company is None:
        raise HTTPException(status_code=404, detail="企業が見つかりません")

    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=422, detail="変更する項目がありません")

    # 必須項目は null で外せない（既定値が決まっているため）
    for field in ("stage", "name", "is_watched", "remote_ok"):
        if field in changes and changes[field] is None:
            raise HTTPException(status_code=422, detail=f"{field} を空にはできません")

    for field, value in changes.items():
        setattr(company, field, value)

    session.add(company)
    session.commit()
    session.refresh(company)
    return _to_card(session, company, resolve_now(resolve_day(None)))


@router.delete("/companies/{company_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_company(company_id: int, session: Session = Depends(get_session)) -> Response:
    """企業を1件削除する。

    メール・タスク・予定が参照している企業は消させない。消すと company_id が
    存在しない id を指したままになり、画面の企業名が消えるだけの不整合になる。
    """
    company = session.get(Company, company_id)
    if company is None:
        raise HTTPException(status_code=404, detail="企業が見つかりません")

    linked = session.exec(select(Task).where(Task.company_id == company_id)).first() or session.exec(
        select(Event).where(Event.company_id == company_id)
    ).first()
    if linked is not None:
        raise HTTPException(
            status_code=422,
            detail="この企業にはタスクまたは予定が紐づいているため削除できません",
        )

    session.delete(company)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
