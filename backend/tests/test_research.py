"""企業研究の情報収集 API（routers/research.py）のテスト。

conftest.py の session / client フィクスチャ（インメモリ DB）を使う。
**実サイトも実 AI も叩かない**（`services.research.fetch_company_pages` と
`services.ai._get_client` をモックに差し替える。docs/spec.md §3 の方針）。

AI が書いた文章の内容は期待値にしない。確かめるのは周りのコード
＝保存・上書き・フォールバック・出典の記録。
"""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from models import PROFILE_ID, Company, Profile, ResearchCheck, ResearchReport
from seed.load import SEED_DIR, _load_research
from services import ai
from services.research import FetchResult

MARKDOWN = "## 事業・製品\n- 物流向けの画像認識 [出典](https://alphatech.co.jp/company/)\n"
CHECKS = ["事業の柱を3つ言えるようにする", "強みの重なりを1文にする"]


@pytest.fixture(name="company")
def company_fixture(session: Session) -> Company:
    company = Company(name="アルファテック", domain="alphatech.co.jp", tags="IT", is_watched=True)
    session.add(company)
    session.add(Company(name="ガンマ工業", domain="gamma-kogyo.jp"))
    session.add(Profile(id=PROFILE_ID, gakuchika="研究室で画像認識の実験系を立ち上げた"))
    session.commit()
    session.refresh(company)
    return company


def _ai_client(markdown: str = MARKDOWN, checks: list[str] | None = None) -> MagicMock:
    """Azure OpenAI（Responses API）の応答を模した MagicMock。"""
    parsed = MagicMock()
    parsed.markdown = markdown
    parsed.checks = CHECKS if checks is None else checks

    res = MagicMock()
    res.output = []
    res.status = "completed"
    res.output_parsed = parsed

    client = MagicMock()
    client.responses.parse.return_value = res
    return client


def _ok(url: str) -> FetchResult:
    return FetchResult(url=url, status="ok", title="会社案内", text="事業内容の説明です。")


def test_collect_reads_company_domain(session: Session, client: TestClient, company: Company) -> None:
    """収集は Company.domain を渡して行い、読めたページを出典として記録する。"""
    results = [
        _ok("https://alphatech.co.jp/"),
        _ok("https://alphatech.co.jp/company/"),
        FetchResult(url="https://alphatech.co.jp/recruit/", status="error", message="取得に失敗しました（HTTP 404）"),
    ]

    with (
        patch("routers.research.fetch_company_pages", return_value=results) as fetch,
        patch.object(ai, "_get_client", return_value=_ai_client()),
    ):
        res = client.post("/api/research/collect", json={"company_id": company.id})

    assert res.status_code == 200
    body = res.json()
    assert fetch.call_args.args[0] == "alphatech.co.jp"  # URL 登録ではなくドメインから探す
    assert body["source"] == "web"
    assert body["report"]["markdown"] == MARKDOWN
    # 読めた2件だけが出典に入る
    assert body["report"]["source_urls"] == [
        "https://alphatech.co.jp/",
        "https://alphatech.co.jp/company/",
    ]
    # 試した URL の結果は3件すべて返す（どのページが読めなかったかを画面に出すため）
    assert [f["status"] for f in body["fetched"]] == ["ok", "ok", "error"]
    assert [c["label"] for c in body["checks"]] == CHECKS


def test_collect_overwrites_same_company(session: Session, client: TestClient, company: Company) -> None:
    """2回収集してもメモは1件のまま上書きされ、確認観点も増えない。"""
    for _ in range(2):
        with (
            patch("routers.research.fetch_company_pages", return_value=[_ok("https://alphatech.co.jp/")]),
            patch.object(ai, "_get_client", return_value=_ai_client()),
        ):
            assert client.post("/api/research/collect", json={"company_id": company.id}).status_code == 200

    assert len(session.exec(select(ResearchReport)).all()) == 1
    assert len(session.exec(select(ResearchCheck)).all()) == len(CHECKS)


def test_collect_falls_back_to_ai_without_pages(
    session: Session, client: TestClient, company: Company
) -> None:
    """ページが1件も読めなければ source = "ai"（観点のみ）。出典は空になる。"""
    denied = FetchResult(
        url="https://alphatech.co.jp/",
        status="robots_denied",
        message="robots.txt がこのページの取得を許可していません",
    )

    with (
        patch("routers.research.fetch_company_pages", return_value=[denied]),
        patch.object(ai, "_get_client", return_value=_ai_client()),
    ):
        res = client.post("/api/research/collect", json={"company_id": company.id})

    body = res.json()
    assert body["source"] == "ai"
    assert body["report"]["source_urls"] == []
    assert body["fetched"][0]["status"] == "robots_denied"
    assert body["fetched"][0]["message"] == "robots.txt がこのページの取得を許可していません"


def test_collect_falls_back_to_template_without_ai(
    session: Session, client: TestClient, company: Company
) -> None:
    """AI の認証情報が無ければ seed のテンプレに落ちる。例外を投げない。"""
    with (
        patch("routers.research.fetch_company_pages", return_value=[]),
        patch.object(ai, "_get_client", return_value=None),
    ):
        res = client.post("/api/research/collect", json={"company_id": company.id})

    assert res.status_code == 200
    assert res.json()["source"] == "template"
    # テンプレの本文が入る（マークダウンの見出しを含む）
    assert "## 事業・製品" in res.json()["report"]["markdown"]
    assert res.json()["checks"]


def test_collect_keeps_other_company(session: Session, client: TestClient, company: Company) -> None:
    """他の企業のメモは触らない。"""
    other = session.exec(select(Company).where(Company.name == "ガンマ工業")).one()
    session.add(
        ResearchReport(
            company_id=other.id or 0,
            markdown="## 事業・製品\n- 制御ソフトを内製\n",
            source="seed",
            collected_at=datetime(2026, 7, 27, 19, 30),
        )
    )
    session.commit()

    with (
        patch("routers.research.fetch_company_pages", return_value=[_ok("https://alphatech.co.jp/")]),
        patch.object(ai, "_get_client", return_value=_ai_client()),
    ):
        client.post("/api/research/collect", json={"company_id": company.id})

    kept = session.exec(select(ResearchReport).where(ResearchReport.company_id == other.id)).one()
    assert kept.source == "seed"
    assert kept.markdown.startswith("## 事業・製品")


def test_collect_unknown_company(client: TestClient) -> None:
    res = client.post("/api/research/collect", json={"company_id": 9999})
    assert res.status_code == 404


def test_get_research_before_collect(client: TestClient, company: Company) -> None:
    """未収集でも 404 にしない（画面が落ちないように）。"""
    res = client.get("/api/research", params={"company_id": company.id})
    assert res.status_code == 200
    assert res.json()["report"] is None
    assert res.json()["checks"] == []
    assert res.json()["company_name"] == "アルファテック"


def test_company_list_shows_collected_state(
    session: Session, client: TestClient, company: Company
) -> None:
    """左カラムの企業一覧は、収集済みかどうかと未確認の観点の数を返す。"""
    with (
        patch("routers.research.fetch_company_pages", return_value=[_ok("https://alphatech.co.jp/")]),
        patch.object(ai, "_get_client", return_value=_ai_client()),
    ):
        client.post("/api/research/collect", json={"company_id": company.id})

    rows = client.get("/api/research/companies").json()
    by_name = {row["name"]: row for row in rows}

    assert by_name["アルファテック"]["source"] == "web"
    assert by_name["アルファテック"]["collected_at"] is not None
    assert by_name["アルファテック"]["unchecked"] == len(CHECKS)
    # 未収集の企業は collected_at が null
    assert by_name["ガンマ工業"]["collected_at"] is None
    assert by_name["ガンマ工業"]["unchecked"] == 0
    assert by_name["ガンマ工業"]["domain"] == "gamma-kogyo.jp"


def test_toggle_check(session: Session, client: TestClient, company: Company) -> None:
    with (
        patch("routers.research.fetch_company_pages", return_value=[]),
        patch.object(ai, "_get_client", return_value=_ai_client()),
    ):
        client.post("/api/research/collect", json={"company_id": company.id})

    check = session.exec(select(ResearchCheck)).first()
    assert check is not None

    res = client.patch(f"/api/research/checks/{check.id}", json={"is_done": True})
    assert res.status_code == 200
    assert res.json()["is_done"] is True

    body = client.get("/api/research", params={"company_id": company.id}).json()
    assert body["unchecked"] == len(CHECKS) - 1
    assert client.patch("/api/research/checks/9999", json={"is_done": True}).status_code == 404


def test_seed_loads_reports_and_checks(session: Session, client: TestClient, company: Company) -> None:
    """seed/research.json を投入すると企業ごとに1枚のメモが入り、2回投入しても増えない。

    app.db は触らず、conftest.py のインメモリ DB に投入して確かめる。
    """
    for _ in range(2):
        _load_research(session, SEED_DIR / "research.json")

    assert len(session.exec(select(ResearchReport)).all()) == 2

    body = client.get("/api/research", params={"company_id": company.id}).json()
    assert body["report"]["source"] == "seed"
    # マークダウンの4見出しが揃っている
    for heading in ("## 事業・製品", "## 求める人材", "## 働き方・制度", "## 最近の動き"):
        assert heading in body["report"]["markdown"]
    assert body["report"]["source_urls"]
    assert body["checks"]


def test_seed_companies_include_iota() -> None:
    """seed/companies.json にイオタテック（架空企業）が入っている。"""
    import json

    data = json.loads((SEED_DIR / "companies.json").read_text(encoding="utf-8"))
    iota = [c for c in data if c["domain"] == "iota-tech.jp"]
    assert iota, "iota-tech.jp が companies.json にありません"
    assert iota[0]["name"] == "イオタテック株式会社"
