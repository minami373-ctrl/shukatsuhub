"""想定問答 API のテスト（docs/spec.md §7「想定問答（④）」）。

AI の出力内容そのものは期待値にしない（§3「AI 部分のテスト方針」）。
検証するのは「AI の周りのコードが正しいか」＝保存・入れ替え・フォールバック・導出値。
Azure OpenAI 呼び出しは services.ai._get_client をモックに差し替えるので実 API を叩かない。
"""

import json
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from models import QA, PROFILE_ID, Company, Profile
from routers.qa import TEMPLATE_PATH
from services import ai


@pytest.fixture(name="company")
def company_fixture(session: Session) -> Company:
    company = Company(name="アルファテック", domain="alphatech.co.jp", tags="IT")
    other = Company(name="ベータ社", domain="beta-inc.jp", tags="")
    session.add_all([company, other])
    session.commit()
    session.refresh(company)
    return company


@pytest.fixture(name="profile")
def profile_fixture(session: Session) -> Profile:
    """生成には「1項目以上入力済み」が必要なので、最低限を入れておく。"""
    profile = Profile(id=PROFILE_ID, gakuchika="研究室で画像認識の実験系を立ち上げた")
    session.add(profile)
    session.commit()
    return profile


def _mock_response(parsed=None, refusal=None, status="completed") -> MagicMock:
    """openai の ParsedResponse（Responses API）相当のモック（test_ai.py と同じ形）。"""
    response = MagicMock()
    response.status = status
    response.output_parsed = parsed

    if refusal is not None:
        content = MagicMock()
        content.type = "refusal"
        content.refusal = refusal
        message = MagicMock()
        message.type = "message"
        message.content = [content]
        response.output = [message]
    else:
        response.output = []

    return response


def _mock_client(count: int = 6) -> MagicMock:
    """count 件の QASheet を返す Azure OpenAI クライアントのモック。"""
    categories = ["志望動機", "ガクチカ", "逆質問"]
    sheet = ai.QASheet(
        items=[
            ai.QAItem(
                question=f"質問{i}",
                answer_draft=f"回答骨子{i}",
                category=categories[i % len(categories)],
            )
            for i in range(count)
        ]
    )
    client = MagicMock()
    client.responses.parse.return_value = _mock_response(parsed=sheet)
    return client


# ---- 受け入れ条件：想定問答の生成と入れ替え ----------------------------------


def test_generate_saves_six_items_with_source_ai_and_unprepared(
    client: TestClient, company: Company, profile: Profile
):
    with patch("services.ai._get_client", return_value=_mock_client(6)):
        res = client.post("/api/qa/generate", json={"company_id": company.id})

    assert res.status_code == 200
    body = res.json()
    assert body["source"] == "ai"
    assert len(body["items"]) == 6
    assert all(item["source"] == "ai" for item in body["items"])
    assert all(item["is_prepared"] is False for item in body["items"])
    assert all(item["company_id"] == company.id for item in body["items"])
    assert body["prepared_rate"] == 0


def test_generating_twice_replaces_instead_of_appending(
    client: TestClient, company: Company, profile: Profile
):
    """同じ企業で2回生成しても 12件にならず 6件のまま（§5.6 の 3）。"""
    with patch("services.ai._get_client", return_value=_mock_client(6)):
        client.post("/api/qa/generate", json={"company_id": company.id})
        res = client.post("/api/qa/generate", json={"company_id": company.id})

    assert res.status_code == 200
    assert len(res.json()["items"]) == 6
    assert len(client.get("/api/qa", params={"company_id": company.id}).json()["items"]) == 6


def test_generating_does_not_touch_other_companies_qa(
    client: TestClient, session: Session, company: Company, profile: Profile
):
    """入れ替えは company_id 単位。他社の想定問答を消さない。"""
    other = session.exec(select(Company).where(Company.domain == "beta-inc.jp")).first()
    assert other is not None  # company フィクスチャがベータ社も作っている

    with patch("services.ai._get_client", return_value=_mock_client(6)):
        client.post("/api/qa/generate", json={"company_id": company.id})
        client.post("/api/qa/generate", json={"company_id": other.id})
        client.post("/api/qa/generate", json={"company_id": other.id})

    assert len(client.get("/api/qa", params={"company_id": company.id}).json()["items"]) == 6
    assert len(client.get("/api/qa", params={"company_id": other.id}).json()["items"]) == 6


# ---- 受け入れ条件：想定問答のフォールバック ----------------------------------


def test_generate_without_api_key_falls_back_to_template(
    client: TestClient, company: Company, profile: Profile
):
    """キー未設定なら seed/questions.json のテンプレが保存され source = template。"""
    template = json.loads(TEMPLATE_PATH.read_text(encoding="utf-8"))

    with patch("services.ai._get_client", return_value=None):
        res = client.post("/api/qa/generate", json={"company_id": company.id})

    assert res.status_code == 200
    body = res.json()
    assert body["source"] == "template"
    assert [item["question"] for item in body["items"]] == [i["question"] for i in template]
    assert all(item["source"] == "template" for item in body["items"])


def test_generate_with_empty_profile_returns_422_without_calling_ai(
    client: TestClient, company: Company
):
    """プロフィールが全項目空なら 422。AI もテンプレも呼ばない（§5.6 の 1）。"""
    mock_client = _mock_client(6)

    with patch("services.ai._get_client", return_value=mock_client) as get_client:
        res = client.post("/api/qa/generate", json={"company_id": company.id})

    assert res.status_code == 422
    assert res.json()["detail"] == "プロフィールを1項目以上入力してください"
    get_client.assert_not_called()
    mock_client.responses.parse.assert_not_called()


def test_generate_with_whitespace_only_profile_returns_422(
    client: TestClient, session: Session, company: Company
):
    """空白のみは未入力として数える（§5.5 の解釈と揃える）。"""
    session.add(Profile(id=PROFILE_ID, gakuchika="   \n "))
    session.commit()

    res = client.post("/api/qa/generate", json={"company_id": company.id})

    assert res.status_code == 422


def test_generate_falls_back_to_template_on_repeated_api_failure(
    client: TestClient, company: Company, profile: Profile
):
    mock_client = MagicMock()
    mock_client.responses.parse.side_effect = ConnectionError("down")

    with patch("services.ai._get_client", return_value=mock_client):
        res = client.post("/api/qa/generate", json={"company_id": company.id})

    assert res.status_code == 200
    assert res.json()["source"] == "template"
    assert mock_client.responses.parse.call_count == 2


def test_generate_falls_back_to_template_on_refusal(
    client: TestClient, company: Company, profile: Profile
):
    mock_client = MagicMock()
    mock_client.responses.parse.return_value = _mock_response(refusal="ポリシー違反のため拒否")

    with patch("services.ai._get_client", return_value=mock_client):
        res = client.post("/api/qa/generate", json={"company_id": company.id})

    assert res.status_code == 200
    assert res.json()["source"] == "template"


def test_generate_falls_back_to_template_when_status_is_incomplete(
    client: TestClient, company: Company, profile: Profile
):
    """res.status が incomplete なら output_parsed を読まずテンプレに落ちる（§5.6）。"""
    mock_client = MagicMock()
    mock_client.responses.parse.return_value = _mock_response(status="incomplete")

    with patch("services.ai._get_client", return_value=mock_client):
        res = client.post("/api/qa/generate", json={"company_id": company.id})

    assert res.status_code == 200
    assert res.json()["source"] == "template"


# ---- 受け入れ条件：準備率の算出 ----------------------------------------------


def test_prepared_rate_is_33_when_two_of_six_answers_are_saved(
    client: TestClient, company: Company, profile: Profile
):
    """6件のうち2件の回答を保存すると準備率 33%（未準備は 4問）。"""
    with patch("services.ai._get_client", return_value=_mock_client(6)):
        items = client.post("/api/qa/generate", json={"company_id": company.id}).json()["items"]

    for item in items[:2]:
        res = client.patch(f"/api/qa/{item['id']}", json={"answer_draft": "自分で書いた回答"})
        assert res.status_code == 200
        assert res.json()["is_prepared"] is True

    sheet = client.get("/api/qa", params={"company_id": company.id}).json()
    assert sheet["prepared_rate"] == 33
    assert sum(1 for item in sheet["items"] if not item["is_prepared"]) == 4


def test_saving_an_answer_persists_the_edited_text(
    client: TestClient, company: Company, profile: Profile
):
    """保存した回答は取り直しても残る（リロードしても消えない）。"""
    with patch("services.ai._get_client", return_value=_mock_client(6)):
        items = client.post("/api/qa/generate", json={"company_id": company.id}).json()["items"]

    qa_id = items[0]["id"]
    client.patch(f"/api/qa/{qa_id}", json={"answer_draft": "研究室での役割を軸に話す"})

    saved = next(
        item
        for item in client.get("/api/qa", params={"company_id": company.id}).json()["items"]
        if item["id"] == qa_id
    )
    assert saved["answer_draft"] == "研究室での役割を軸に話す"
    assert saved["is_prepared"] is True


def test_saving_a_blank_answer_returns_422_and_does_not_mark_prepared(
    client: TestClient, company: Company, profile: Profile
):
    """空欄（空白のみを含む）は保存できない。未入力を準備済みと数えないため。"""
    with patch("services.ai._get_client", return_value=_mock_client(6)):
        items = client.post("/api/qa/generate", json={"company_id": company.id}).json()["items"]

    qa_id = items[0]["id"]
    original = items[0]["answer_draft"]

    for blank in ("", "   \n "):
        res = client.patch(f"/api/qa/{qa_id}", json={"answer_draft": blank})
        assert res.status_code == 422
        assert res.json()["detail"] == "回答を入力してください"

    unchanged = next(
        item
        for item in client.get("/api/qa", params={"company_id": company.id}).json()["items"]
        if item["id"] == qa_id
    )
    assert unchanged["answer_draft"] == original
    assert unchanged["is_prepared"] is False


def test_patch_returns_404_for_unknown_id(client: TestClient, company: Company):
    assert client.patch("/api/qa/9999", json={"answer_draft": "回答"}).status_code == 404


# ---- 一覧・企業セレクト ------------------------------------------------------


def test_list_qa_returns_empty_sheet_before_generating(client: TestClient, company: Company):
    """未生成でも 404 にせず空で返す（画面が落ちないように）。"""
    res = client.get("/api/qa", params={"company_id": company.id})

    assert res.status_code == 200
    assert res.json() == {
        "company_id": company.id,
        "source": None,
        "items": [],
        "prepared_rate": 0,
    }


def test_list_qa_returns_404_for_unknown_company(client: TestClient, company: Company):
    assert client.get("/api/qa", params={"company_id": 9999}).status_code == 404


def test_generate_returns_404_for_unknown_company(client: TestClient, profile: Profile):
    assert client.post("/api/qa/generate", json={"company_id": 9999}).status_code == 404


def test_list_companies_returns_id_and_name(client: TestClient, company: Company):
    res = client.get("/api/companies")

    assert res.status_code == 200
    names = [c["name"] for c in res.json()]
    assert names == ["アルファテック", "ベータ社"]
    assert all({"id", "name", "tags"} == c.keys() for c in res.json())


def test_qa_items_keep_generated_order(client: TestClient, company: Company, profile: Profile):
    """AI が並べた順（id 昇順）を保つ。カテゴリで並べ替えない。"""
    with patch("services.ai._get_client", return_value=_mock_client(6)):
        client.post("/api/qa/generate", json={"company_id": company.id})

    items = client.get("/api/qa", params={"company_id": company.id}).json()["items"]
    assert [item["question"] for item in items] == [f"質問{i}" for i in range(6)]


def test_reloading_companies_seed_does_not_leave_orphan_qa(session: Session, company: Company):
    """企業を採番し直したとき、company_id が宙に浮いた QA を残さない。

    seed/load.py の _load_companies は Company を全削除して入れ直すので、
    参照する側（QA）も一緒に消していないと、どの画面からも見えない行が溜まる。
    """
    from seed.load import SEED_DIR, _load_companies

    session.add(
        QA(
            company_id=company.id,
            question="質問",
            answer_draft="回答",
            category="志望動機",
            source="ai",
            generated_at=datetime(2026, 7, 30, 12, 20),
        )
    )
    session.commit()

    _load_companies(session, SEED_DIR / "companies.json")

    assert session.exec(select(QA)).all() == []


def test_template_seed_covers_all_three_categories():
    """questions.json は3カテゴリすべてを含む（§4.5 のカテゴリタグが全部出せること）。"""
    template = json.loads(TEMPLATE_PATH.read_text(encoding="utf-8"))
    assert {item["category"] for item in template} == {"志望動機", "ガクチカ", "逆質問"}
