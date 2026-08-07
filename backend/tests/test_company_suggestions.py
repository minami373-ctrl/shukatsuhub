"""受信箱からの企業登録の提案（docs/spec.md §5.11）と `/api/companies/from-emails`。

**AI もスクレイピングも使わない。**既に受信しているメールだけを材料にするので、
同じメールなら常に同じ候補になることを前提にテストできる。
"""

from datetime import datetime

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from models import Company, Email
from services.company_source import suggest_from_emails


def make_email(
    address: str,
    subject: str = "件名",
    *,
    from_name: str | None = None,
    category: str = "重要",
    received_at: str = "2026-07-30T09:00:00",
    company_id: int | None = None,
) -> Email:
    return Email(
        account="gmail",
        from_address=address,
        from_name=from_name,
        subject=subject,
        body=None,
        received_at=datetime.fromisoformat(received_at),
        category=category,
        needs_reply=False,
        decided_by="rule",
        company_id=company_id,
        thread_key=f"{address}|{subject}",
    )


def test_suggests_only_unregistered_domains(session: Session) -> None:
    """登録済みの企業から届いたメールは候補にしない。"""
    companies = [Company(id=1, name="アルファテック", domain="alphatech.co.jp")]
    emails = [
        make_email("hr@alphatech.co.jp", company_id=1),
        make_email("saiyo@sigma-denshi.jp", from_name="シグマ電子 採用担当"),
    ]

    suggestions = suggest_from_emails(emails, companies)

    assert [s.domain for s in suggestions] == ["sigma-denshi.jp"]
    assert suggestions[0].suggested_name == "シグマ電子 採用担当"


def test_registered_domain_is_excluded_even_without_company_id(session: Session) -> None:
    """company_id が空でも、同じドメインの企業が既にあれば候補にしない（二重登録の防止）。"""
    companies = [Company(id=1, name="アルファテック", domain="alphatech.co.jp")]

    assert suggest_from_emails([make_email("hr@alphatech.co.jp")], companies) == []


def test_ads_are_excluded(session: Session) -> None:
    """`広告` は候補にしない。エージェント・メルマガ配信元を企業にすると選考ボードが埋まる。"""
    emails = [
        make_email("scout@jobscout-example.jp", from_name="就活エージェント", category="広告"),
        make_email("recruit@omega-shoji.co.jp", from_name="オメガ商事", category="確認"),
    ]

    suggestions = suggest_from_emails(emails, [])

    assert [s.domain for s in suggestions] == ["omega-shoji.co.jp"]
    assert suggestions[0].categories == ["確認"]


def test_name_is_the_most_frequent_from_name(session: Session) -> None:
    """企業名の候補は送信者表示名の最頻値。件数・最新受信日時もまとめて返す。"""
    emails = [
        make_email("a@sigma-denshi.jp", from_name="シグマ電子 採用担当", received_at="2026-07-28T15:30:00"),
        make_email("b@sigma-denshi.jp", from_name="シグマ電子 採用担当", received_at="2026-07-30T08:40:00"),
        make_email("c@sigma-denshi.jp", from_name="シグマ電子 人事部", received_at="2026-07-29T10:00:00"),
    ]

    suggestion = suggest_from_emails(emails, [])[0]

    assert suggestion.suggested_name == "シグマ電子 採用担当"
    assert suggestion.email_count == 3
    assert suggestion.latest_received_at == datetime(2026, 7, 30, 8, 40)


def test_domain_is_used_when_no_from_name(session: Session) -> None:
    """表示名が無ければドメインをそのまま候補にする（ドメインから企業名を推測しない）。"""
    suggestion = suggest_from_emails([make_email("info@omega-shoji.co.jp")], [])[0]

    assert suggestion.suggested_name == "omega-shoji.co.jp"


def test_sorted_by_latest_received(session: Session) -> None:
    """受信の新しい順に並べる。"""
    emails = [
        make_email("a@old-example.jp", received_at="2026-07-20T09:00:00"),
        make_email("b@new-example.jp", received_at="2026-07-30T09:00:00"),
    ]

    assert [s.domain for s in suggest_from_emails(emails, [])] == [
        "new-example.jp",
        "old-example.jp",
    ]


def test_no_candidates_is_empty(session: Session) -> None:
    """候補が0件でもエラーにしない。"""
    assert suggest_from_emails([], []) == []


# ===== API =====


def seed_inbox(session: Session) -> None:
    session.add(Company(name="アルファテック", domain="alphatech.co.jp"))
    session.commit()
    company = session.exec(select(Company)).one()
    session.add_all(
        [
            make_email("hr@alphatech.co.jp", company_id=company.id),
            make_email("saiyo@sigma-denshi.jp", subject="面接", from_name="シグマ電子 採用担当"),
            make_email(
                "info@sigma-denshi.jp",
                subject="ES提出",
                from_name="シグマ電子 採用担当",
                category="確認",
                received_at="2026-07-28T15:30:00",
            ),
            make_email("scout@jobscout-example.jp", from_name="就活エージェント", category="広告"),
        ]
    )
    session.commit()


def test_suggestions_api(session: Session, client: TestClient) -> None:
    """未登録ドメインだけが候補に出る。広告は出ない。"""
    seed_inbox(session)

    payload = client.get("/api/companies/suggestions").json()

    assert [i["domain"] for i in payload["items"]] == ["sigma-denshi.jp"]
    assert payload["items"][0]["email_count"] == 2
    assert payload["items"][0]["categories"] == ["重要", "確認"]


def test_from_emails_creates_company_with_no_conditions(
    session: Session, client: TestClient
) -> None:
    """メールから分かるのはドメインと表示名だけ。条件は未登録のまま作る（推測で埋めない）。"""
    seed_inbox(session)

    payload = client.post(
        "/api/companies/from-emails", json={"domains": ["sigma-denshi.jp"]}
    ).json()

    created = payload["created"][0]
    assert created["name"] == "シグマ電子 採用担当"
    assert created["stage"] == "気になる"
    # 条件は人が企業ダイアログで入れる。ここで推測して埋めない
    assert created["job_type"] is None
    assert created["location"] is None
    assert created["remote_ok"] is False
    assert created["tags"] is None
    assert created["salary_min"] is None
    assert created["holidays_per_year"] is None


def test_from_emails_links_existing_emails(session: Session, client: TestClient) -> None:
    """登録後、そのドメインの既存メールの company_id を埋め直す（受信箱が企業名に変わる）。"""
    seed_inbox(session)

    payload = client.post(
        "/api/companies/from-emails", json={"domains": ["sigma-denshi.jp"]}
    ).json()

    assert payload["linked_emails"] == 2
    created_id = payload["created"][0]["id"]
    linked = session.exec(select(Email).where(Email.from_address == "saiyo@sigma-denshi.jp")).one()
    assert linked.company_id == created_id
    # thread_key も企業 ID 基準に作り直す（§5.2）
    assert linked.thread_key.startswith(f"{created_id}|")


def test_from_emails_skips_registered_domain(session: Session, client: TestClient) -> None:
    """既に登録済みのドメインは黙って読み飛ばす（二重登録しない）。"""
    seed_inbox(session)

    payload = client.post(
        "/api/companies/from-emails", json={"domains": ["alphatech.co.jp"]}
    ).json()

    assert payload["created"] == []
    assert payload["skipped"] == ["alphatech.co.jp"]
    assert len(session.exec(select(Company)).all()) == 1


def test_from_emails_rejects_domain_without_candidate(
    session: Session, client: TestClient
) -> None:
    """候補に無いドメインは受け付けない（根拠の無いものを企業にしない）。"""
    seed_inbox(session)

    res = client.post("/api/companies/from-emails", json={"domains": ["jobscout-example.jp"]})

    assert res.status_code == 422
    assert len(session.exec(select(Company)).all()) == 1


def test_from_emails_requires_a_domain(session: Session, client: TestClient) -> None:
    """空配列は 422。"""
    seed_inbox(session)

    assert client.post("/api/companies/from-emails", json={"domains": []}).status_code == 422
