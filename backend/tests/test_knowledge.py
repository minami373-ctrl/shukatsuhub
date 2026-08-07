"""ナレッジ蓄積 API（docs/spec.md §6 Knowledge / §11 相当の完了条件）。

conftest.py の session / client フィクスチャ（インメモリ DB）を使う。
"""

from datetime import datetime

from fastapi.testclient import TestClient
from sqlmodel import Session

from models import Company, Knowledge


def seed_knowledge(session: Session) -> Company:
    company = Company(name="アルファテック", domain="alphatech.co.jp", is_watched=True)
    session.add(company)
    session.commit()
    session.refresh(company)

    session.add_all(
        [
            Knowledge(
                title="一次面接 振り返り",
                category="面接振り返り",
                company_id=company.id,
                content="逆算質問が多かった",
                updated_at=datetime(2026, 7, 28, 21, 0),
            ),
            Knowledge(
                title="自己PRテンプレート",
                category="テンプレート",
                company_id=None,
                content="結論→根拠→再現性",
                updated_at=datetime(2026, 7, 25, 10, 0),
            ),
            Knowledge(
                title="逆質問で困った内容",
                category="学び",
                company_id=None,
                content="事前にIR資料を読み込むべきだった",
                updated_at=datetime(2026, 7, 30, 9, 0),
            ),
        ]
    )
    session.commit()
    return company


def test_list_knowledge_returns_all_notes_newest_first(client: TestClient, session: Session):
    seed_knowledge(session)

    res = client.get("/api/knowledge")

    assert res.status_code == 200
    titles = [item["title"] for item in res.json()]
    assert titles == ["逆質問で困った内容", "一次面接 振り返り", "自己PRテンプレート"]


def test_list_knowledge_includes_company_name_when_linked(client: TestClient, session: Session):
    seed_knowledge(session)

    res = client.get("/api/knowledge")

    by_title = {item["title"]: item for item in res.json()}
    assert by_title["一次面接 振り返り"]["company_name"] == "アルファテック"
    assert by_title["自己PRテンプレート"]["company_name"] is None


def test_list_knowledge_filters_by_category(client: TestClient, session: Session):
    seed_knowledge(session)

    res = client.get("/api/knowledge", params={"category": "テンプレート"})

    titles = [item["title"] for item in res.json()]
    assert titles == ["自己PRテンプレート"]


def test_create_knowledge_adds_a_note(client: TestClient, session: Session):
    res = client.post(
        "/api/knowledge",
        json={"title": "新しいメモ", "category": "学び", "company_id": None, "content": "本文"},
    )

    assert res.status_code == 200
    body = res.json()
    assert body["title"] == "新しいメモ"
    assert body["category"] == "学び"

    listed = client.get("/api/knowledge").json()
    assert len(listed) == 1


def test_create_knowledge_rejects_invalid_category(client: TestClient):
    res = client.post(
        "/api/knowledge",
        json={"title": "不正なカテゴリ", "category": "その他", "company_id": None, "content": "本文"},
    )

    assert res.status_code == 422


def test_create_knowledge_rejects_empty_title(client: TestClient):
    res = client.post(
        "/api/knowledge",
        json={"title": "  ", "category": "学び", "company_id": None, "content": "本文"},
    )

    assert res.status_code == 422
