"""想定問答 API（docs/spec.md §4.5 / §5.6 / API 一覧）。

- GET   /api/companies    企業一覧（想定問答の企業セレクト用）
- GET   /api/qa           クエリ company_id の想定問答一覧 ＋ source ＋ prepared_rate
- POST  /api/qa/generate  AI で生成し、その企業の既存レコードを入れ替える
- PATCH /api/qa/{id}      回答骨子を保存する（保存できたら is_prepared が true になる）

AI の呼び出しそのものは services/ai.py にある（openai を import する唯一の場所）。
このファイルの責務は「DB への保存と入れ替え」と「導出値 prepared_rate の算出」。
"""

import json
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import Session, delete, select

from db import get_session
from models import PROFILE_FIELDS, PROFILE_ID, QA, Company, Profile, filled_fields
from services.ai import generate_qa

router = APIRouter(prefix="/api", tags=["qa"])

#: AI が落ちたときに使うテンプレ質問セット（§5.6 フォールバック）。
TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "seed" / "questions.json"

VALID_CATEGORIES = ("志望動機", "ガクチカ", "逆質問")


class CompanyOut(BaseModel):
    """企業セレクトの1件。domain は画面に出さないので返さない。"""

    id: int
    name: str
    tags: str | None


class QAOut(BaseModel):
    id: int
    company_id: int
    question: str
    answer_draft: str
    category: str
    is_prepared: bool
    source: str
    generated_at: datetime


class QASheetOut(BaseModel):
    """一覧・生成の共通レスポンス。prepared_rate は保存しない導出値（§6）。"""

    company_id: int
    #: 生成元。1件も無いときは null（画面は「まだありません」を出す）
    source: str | None
    items: list[QAOut]
    prepared_rate: int


class GenerateBody(BaseModel):
    company_id: int


class QAPatch(BaseModel):
    """回答骨子の保存。保存できたら準備済みになる（§4.5）。

    is_prepared は受け取らない。準備済みは「自分の回答を書いた」ことの結果であり、
    クライアントが直接立てる値ではないため（取り消しも今回は作らない）。
    """

    answer_draft: str


def _to_out(qa: QA) -> QAOut:
    return QAOut(
        id=qa.id or 0,
        company_id=qa.company_id,
        question=qa.question,
        answer_draft=qa.answer_draft,
        category=qa.category,
        is_prepared=qa.is_prepared,
        source=qa.source,
        generated_at=qa.generated_at,
    )


def prepared_rate(items: list[QA]) -> int:
    """準備率%（is_prepared が true の件数 ÷ 総件数）。0件なら 0（§5.6）。

    丸めは半数切り上げ。Python の round() は偶数丸めで説明できなくなるため使わない
    （§5.3 の時間の丸めと同じ方針）。
    """
    if not items:
        return 0
    ratio = sum(1 for qa in items if qa.is_prepared) / len(items) * 100
    return int(ratio + 0.5)


def _load_template_items() -> list[dict[str, str]]:
    """seed/questions.json を読んで検証する。壊れていたら SeedError 相当で 500 にする。"""
    try:
        raw = json.loads(TEMPLATE_PATH.read_text(encoding="utf-8"))
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"questions.json を読み込めません: {e}") from e
    except json.JSONDecodeError as e:
        raise HTTPException(
            status_code=500, detail=f"questions.json の JSON が壊れています: {e}"
        ) from e

    if not isinstance(raw, list) or not raw:
        raise HTTPException(status_code=500, detail="questions.json は1件以上の配列である必要があります")

    items: list[dict[str, str]] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise HTTPException(status_code=500, detail=f"questions.json の {i} 件目がオブジェクトではありません")
        missing = [k for k in ("question", "answer_draft", "category") if not item.get(k)]
        if missing:
            raise HTTPException(
                status_code=500,
                detail=f"questions.json の {i} 件目に必須項目がありません: {', '.join(missing)}",
            )
        if item["category"] not in VALID_CATEGORIES:
            raise HTTPException(
                status_code=500,
                detail=f"questions.json の {i} 件目の category が不正です: {item['category']}",
            )
        items.append(
            {
                "question": item["question"],
                "answer_draft": item["answer_draft"],
                "category": item["category"],
            }
        )
    return items


def _company_or_404(session: Session, company_id: int) -> Company:
    company = session.get(Company, company_id)
    if company is None:
        raise HTTPException(status_code=404, detail="企業が見つかりません")
    return company


def _qa_for_company(session: Session, company_id: int) -> list[QA]:
    """カテゴリ順ではなく id 昇順（＝生成された順）で返す。AI が並べた順を保つため。"""
    statement = select(QA).where(QA.company_id == company_id).order_by(QA.id)
    return list(session.exec(statement))


def _sheet(session: Session, company_id: int) -> QASheetOut:
    items = _qa_for_company(session, company_id)
    return QASheetOut(
        company_id=company_id,
        # 同じ企業の QA は一括で入れ替わるので、source は全件で同じ値になる
        source=items[0].source if items else None,
        items=[_to_out(qa) for qa in items],
        prepared_rate=prepared_rate(items),
    )


@router.get("/companies", response_model=list[CompanyOut])
def list_companies(session: Session = Depends(get_session)) -> list[CompanyOut]:
    """企業セレクト用の一覧。seed/companies.json の並び（id 昇順）で返す。"""
    return [
        CompanyOut(id=c.id, name=c.name, tags=c.tags)
        for c in session.exec(select(Company).order_by(Company.id))
        if c.id is not None
    ]


@router.get("/qa", response_model=QASheetOut)
def list_qa(
    company_id: int = Query(..., description="どの企業の想定問答か"),
    session: Session = Depends(get_session),
) -> QASheetOut:
    """未生成でも 404 にせず空の一覧を返す（画面が落ちないように）。"""
    _company_or_404(session, company_id)
    return _sheet(session, company_id)


@router.post("/qa/generate", response_model=QASheetOut)
def generate(body: GenerateBody, session: Session = Depends(get_session)) -> QASheetOut:
    """想定問答を生成して、その企業の既存レコードを入れ替える（§5.6）。

    再生成しても件数が増えないよう、保存前に同じ company_id を全削除する。
    """
    company = _company_or_404(session, body.company_id)

    profile = session.get(Profile, PROFILE_ID) or Profile(id=PROFILE_ID)
    if not filled_fields(profile):
        # AI もテンプレも呼ばずに弾く（§5.6 の 1）
        raise HTTPException(status_code=422, detail="プロフィールを1項目以上入力してください")

    profile_fields = {name: getattr(profile, name) for name in PROFILE_FIELDS}
    items, source = generate_qa(
        profile_fields=profile_fields,
        company_name=company.name,
        company_tags=company.tags or "",
        template_items=_load_template_items(),
    )

    generated_at = datetime.now()
    session.exec(delete(QA).where(QA.company_id == body.company_id))
    session.add_all(
        [
            QA(
                company_id=body.company_id,
                question=item["question"],
                answer_draft=item["answer_draft"],
                category=item["category"],
                is_prepared=False,
                source=source,
                generated_at=generated_at,
            )
            for item in items
        ]
    )
    session.commit()
    return _sheet(session, body.company_id)


@router.patch("/qa/{qa_id}", response_model=QAOut)
def update_qa(qa_id: int, body: QAPatch, session: Session = Depends(get_session)) -> QAOut:
    """回答骨子を保存し、その QA を準備済みにする（§4.5）。

    準備率はフロントが一覧を取り直して再計算する。
    """
    qa = session.get(QA, qa_id)
    if qa is None:
        raise HTTPException(status_code=404, detail="想定問答が見つかりません")

    if not body.answer_draft.strip():
        # 空欄を準備済みと数えないため、保存自体を断る（§4.5）
        raise HTTPException(status_code=422, detail="回答を入力してください")

    qa.answer_draft = body.answer_draft
    qa.is_prepared = True
    session.add(qa)
    session.commit()
    session.refresh(qa)
    return _to_out(qa)
