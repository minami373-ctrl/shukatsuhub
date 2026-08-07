from models import Company, Email
from services.grouping import build_thread_key, group_by_thread, normalize_subject, representative_category


def test_normalize_subject_strips_reply_and_forward_prefixes_repeatedly():
    assert normalize_subject("Re: Re: Fwd: 一次面接のご案内") == "一次面接のご案内"
    assert normalize_subject("返信: 転送: ES提出について") == "ES提出について"
    assert normalize_subject("RE:件名") == "件名"


def test_normalize_subject_trims_and_unifies_fullwidth_space():
    assert normalize_subject("　件名　") == "件名"


def test_build_thread_key_uses_company_id_when_domain_matches():
    companies = [Company(id=1, name="アルファテック", domain="alphatech.co.jp", is_watched=True)]

    key = build_thread_key("hr@alphatech.co.jp", "Re: 一次面接のご案内", companies)

    assert key == "1|一次面接のご案内"


def test_build_thread_key_falls_back_to_domain_when_unmatched():
    key = build_thread_key("news@mailmaga-example.com", "メルマガ", [])

    assert key == "mailmaga-example.com|メルマガ"


def test_group_by_thread_groups_same_company_and_normalized_subject():
    e1 = Email(
        id=1, account="icloud", from_address="info@delta-corp.co.jp", subject="一次面接 日程候補のご連絡",
        received_at="2026-07-29T16:00:00", category="重要", thread_key="1|一次面接 日程候補のご連絡",
    )
    e2 = Email(
        id=2, account="icloud", from_address="info@delta-corp.co.jp", subject="Re: 一次面接 日程候補のご連絡",
        received_at="2026-07-30T09:30:00", category="重要", thread_key="1|一次面接 日程候補のご連絡",
    )
    e3 = Email(
        id=3, account="gmail", from_address="other@example.com", subject="別件",
        received_at="2026-07-30T09:30:00", category="確認", thread_key="example.com|別件",
    )

    groups = group_by_thread([e1, e2, e3])

    assert len(groups) == 2
    assert {e.id for e in groups["1|一次面接 日程候補のご連絡"]} == {1, 2}


def test_representative_category_picks_strongest():
    assert representative_category(
        [type("E", (), {"category": "広告"})(), type("E", (), {"category": "重要"})()]
    ) == "重要"
