"""企業研究の情報収集 API（画面は `/interview`。docs/spec.md への追記は人の承認待ち）。

GET    /api/research/companies    … 左カラムの企業一覧（収集済みか・いつ集めたか）
GET    /api/research?company_id=  … その企業のメモ（マークダウン）＋ 出典 ＋ 確認観点
POST   /api/research/collect      … 企業ドメインの定番ページを読み、AI に整理させて上書きする
PATCH  /api/research/checks/{id}  … 確認観点の完了を反転

このファイルの責務は「DB への保存と上書き」と「導出値の算出」。
ページの取得は services/research.py、AI の整理は services/ai.py にある
（それぞれ httpx / openai を import する唯一の場所）。

収集元 URL の登録は持たない。読むのは `Company.domain` 配下の定番ページだけ
（services/research.py の CANDIDATE_PATHS）。
"""

import json
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import Session, select

from db import get_session
from models import (
    PROFILE_FIELDS,
    PROFILE_ID,
    Company,
    Profile,
    ResearchCheck,
    ResearchReport,
)
from services.ai import organize_research
from services.research import FetchResult, fetch_company_pages

router = APIRouter(prefix="/api/research", tags=["research"])

#: 収集も AI も使えないときに使うテンプレ（seed/research.json の template ブロック）。
SEED_PATH = Path(__file__).resolve().parent.parent / "seed" / "research.json"


class CheckOut(BaseModel):
    id: int
    company_id: int
    label: str
    is_done: bool
    source: str


class ReportOut(BaseModel):
    company_id: int
    #: 本文（マークダウン）。画面がそのまま描画する
    markdown: str
    #: 根拠にした公開ページの URL
    source_urls: list[str]
    #: web / ai / template / seed（models.RESEARCH_SOURCES）
    source: str
    collected_at: datetime


class CompanyRow(BaseModel):
    """左カラムの企業一覧1行。収集済みかどうかが一目で分かるようにする。"""

    id: int
    name: str
    domain: str
    collected_at: datetime | None
    source: str | None
    #: その企業の未確認の観点
    unchecked: int


class ResearchResponse(BaseModel):
    company_id: int
    company_name: str
    #: 未収集なら None（画面は「まだありません」を出す）
    report: ReportOut | None
    checks: list[CheckOut]
    #: 未確認の観点の件数（ヒーローの指標に使う）
    unchecked: int


class CollectBody(BaseModel):
    company_id: int


class FetchOut(BaseModel):
    """1 URL の取得結果。どのページが読めたかを画面に出すために返す。"""

    url: str
    status: str  # ok / robots_denied / error
    message: str | None


class CollectResponse(BaseModel):
    company_id: int
    #: web=公開ページから整理／ai=ページが読めず観点のみ／template=AI も使えずテンプレ
    source: str
    report: ReportOut
    checks: list[CheckOut]
    #: 試した URL の結果（成功・robots 拒否・失敗）
    fetched: list[FetchOut]


class CheckPatch(BaseModel):
    is_done: bool


def _split_urls(value: str) -> list[str]:
    return [line for line in (value or "").splitlines() if line.strip()]


def _to_report_out(report: ResearchReport) -> ReportOut:
    return ReportOut(
        company_id=report.company_id,
        markdown=report.markdown,
        source_urls=_split_urls(report.source_urls),
        source=report.source,
        collected_at=report.collected_at,
    )


def _to_check_out(check: ResearchCheck) -> CheckOut:
    return CheckOut(
        id=check.id or 0,
        company_id=check.company_id,
        label=check.label,
        is_done=check.is_done,
        source=check.source,
    )


def _company_or_404(session: Session, company_id: int) -> Company:
    company = session.get(Company, company_id)
    if company is None:
        raise HTTPException(status_code=404, detail="企業が見つかりません")
    return company


def report_of(session: Session, company_id: int) -> ResearchReport | None:
    statement = select(ResearchReport).where(ResearchReport.company_id == company_id)
    return session.exec(statement).one_or_none()


def checks_of(session: Session, company_id: int) -> list[ResearchCheck]:
    statement = (
        select(ResearchCheck).where(ResearchCheck.company_id == company_id).order_by(ResearchCheck.id)
    )
    return list(session.exec(statement))


def _load_template() -> tuple[str, list[str]]:
    """seed/research.json の template ブロックを読む（収集も AI も使えないときの最後の砦）。"""
    try:
        raw = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"research.json を読み込めません: {e}") from e
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=500, detail=f"research.json の JSON が壊れています: {e}") from e

    template = raw.get("template") if isinstance(raw, dict) else None
    if not isinstance(template, dict):
        raise HTTPException(status_code=500, detail="research.json に template がありません")

    markdown = template.get("markdown")
    checks = template.get("checks")
    if not isinstance(markdown, str) or not markdown.strip():
        raise HTTPException(status_code=500, detail="research.json の template.markdown が空です")
    if not isinstance(checks, list):
        raise HTTPException(status_code=500, detail="research.json の template.checks が配列ではありません")
    return markdown, [str(c) for c in checks]


@router.get("/companies", response_model=list[CompanyRow])
def list_companies(session: Session = Depends(get_session)) -> list[CompanyRow]:
    """左カラムの企業一覧。seed/companies.json の並び（id 昇順）で返す。"""
    reports = {r.company_id: r for r in session.exec(select(ResearchReport))}
    unchecked: dict[int, int] = {}
    for check in session.exec(select(ResearchCheck)):
        if not check.is_done:
            unchecked[check.company_id] = unchecked.get(check.company_id, 0) + 1

    rows: list[CompanyRow] = []
    for company in session.exec(select(Company).order_by(Company.id)):
        if company.id is None:
            continue
        report = reports.get(company.id)
        rows.append(
            CompanyRow(
                id=company.id,
                name=company.name,
                domain=company.domain,
                collected_at=report.collected_at if report else None,
                source=report.source if report else None,
                unchecked=unchecked.get(company.id, 0),
            )
        )
    return rows


@router.get("", response_model=ResearchResponse)
def get_research(
    company_id: int = Query(..., description="どの企業の研究か"),
    session: Session = Depends(get_session),
) -> ResearchResponse:
    """その企業のメモと確認観点。未収集でも 404 にしない（画面が落ちないように）。"""
    company = _company_or_404(session, company_id)
    report = report_of(session, company_id)
    checks = checks_of(session, company_id)

    return ResearchResponse(
        company_id=company_id,
        company_name=company.name,
        report=_to_report_out(report) if report else None,
        checks=[_to_check_out(c) for c in checks],
        unchecked=sum(1 for c in checks if not c.is_done),
    )


def _allowed_urls(results: list[FetchResult]) -> list[str]:
    """読めたページの URL。出典として画面に出す。"""
    return [r.url for r in results if r.ok]


@router.post("/collect", response_model=CollectResponse)
def collect(body: CollectBody, session: Session = Depends(get_session)) -> CollectResponse:
    """企業ドメインの定番ページを読み、AI に整理させてメモを上書きする。

    読めたページが1件も無ければ、AI に「調べるべき観点」だけを組み立てさせる
    （事実を創作させないため services/ai.py 側で指示を切り替える）。
    AI も使えなければ seed のテンプレに落ちる。**どの段でも例外を投げない。**
    """
    company = _company_or_404(session, body.company_id)

    results = fetch_company_pages(company.domain)
    pages = [
        {"url": r.url, "title": r.title or "", "text": r.text or ""} for r in results if r.ok and r.text
    ]

    profile = session.get(Profile, PROFILE_ID) or Profile(id=PROFILE_ID)
    template_markdown, template_checks = _load_template()

    markdown, checks, source_kind = organize_research(
        company_name=company.name,
        company_tags=company.tags or "",
        profile_fields={name: getattr(profile, name) for name in PROFILE_FIELDS},
        pages=pages,
        template_markdown=template_markdown,
        template_checks=template_checks,
    )

    collected_at = datetime.now()
    report = report_of(session, body.company_id) or ResearchReport(
        company_id=body.company_id, markdown="", source=source_kind, collected_at=collected_at
    )
    report.markdown = markdown
    report.source_urls = "\n".join(_allowed_urls(results))
    report.source = source_kind
    report.collected_at = collected_at
    session.add(report)

    # 確認観点はその企業の分を入れ替える（増えていかないように）
    for existing in checks_of(session, body.company_id):
        session.delete(existing)
    session.add_all(
        [
            ResearchCheck(
                company_id=body.company_id, label=label, is_done=False, source=source_kind
            )
            for label in checks
        ]
    )
    session.commit()
    session.refresh(report)

    return CollectResponse(
        company_id=body.company_id,
        source=source_kind,
        report=_to_report_out(report),
        checks=[_to_check_out(c) for c in checks_of(session, body.company_id)],
        fetched=[FetchOut(url=r.url, status=r.status, message=r.message) for r in results],
    )


@router.patch("/checks/{check_id}", response_model=CheckOut)
def update_check(
    check_id: int, body: CheckPatch, session: Session = Depends(get_session)
) -> CheckOut:
    """確認観点の1件を確認済み / 未確認にする。"""
    check = session.get(ResearchCheck, check_id)
    if check is None:
        raise HTTPException(status_code=404, detail="確認観点が見つかりません")

    check.is_done = body.is_done
    session.add(check)
    session.commit()
    session.refresh(check)
    return _to_check_out(check)


def host_of(url: str) -> str:
    """出典表示用のホスト名（テストとフロントの表記をそろえるために公開しておく）。"""
    return urlparse(url).netloc
