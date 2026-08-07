"""ナレッジ蓄積 API（docs/spec.md §6 Knowledge / 03-today-focus/FEATURE_PAGE_SPECS.md §11）。

- GET  /api/knowledge  クエリ category でフィルタしたメモ一覧（更新日時の新しい順）
- POST /api/knowledge  メモを1件追加
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from db import get_session
from models import Company, Knowledge

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])

VALID_CATEGORIES = ("面接振り返り", "企業メモ", "テンプレート", "学び")


class KnowledgeOut(BaseModel):
    id: int
    title: str
    category: str
    company_id: int | None
    company_name: str | None
    content: str
    updated_at: datetime


class KnowledgeCreate(BaseModel):
    title: str
    category: str
    company_id: int | None = None
    content: str


def _to_out(note: Knowledge, companies: dict[int, Company]) -> KnowledgeOut:
    company = companies.get(note.company_id) if note.company_id else None
    return KnowledgeOut(
        id=note.id or 0,
        title=note.title,
        category=note.category,
        company_id=note.company_id,
        company_name=company.name if company else None,
        content=note.content,
        updated_at=note.updated_at,
    )


@router.get("", response_model=list[KnowledgeOut])
def list_knowledge(
    category: str | None = None, session: Session = Depends(get_session)
) -> list[KnowledgeOut]:
    query = select(Knowledge)
    if category is not None:
        query = query.where(Knowledge.category == category)
    notes = session.exec(query.order_by(Knowledge.updated_at.desc())).all()

    companies = {c.id: c for c in session.exec(select(Company)) if c.id is not None}
    return [_to_out(note, companies) for note in notes]


@router.post("", response_model=KnowledgeOut)
def create_knowledge(body: KnowledgeCreate, session: Session = Depends(get_session)) -> KnowledgeOut:
    if body.category not in VALID_CATEGORIES:
        raise HTTPException(status_code=422, detail=f"category は次のいずれかです: {', '.join(VALID_CATEGORIES)}")
    if not body.title.strip():
        raise HTTPException(status_code=422, detail="タイトルを入力してください")

    note = Knowledge(
        title=body.title,
        category=body.category,
        company_id=body.company_id,
        content=body.content,
        updated_at=datetime.now(),
    )
    session.add(note)
    session.commit()
    session.refresh(note)

    companies = {c.id: c for c in session.exec(select(Company)) if c.id is not None}
    return _to_out(note, companies)
