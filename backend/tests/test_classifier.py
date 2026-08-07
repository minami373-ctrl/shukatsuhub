from unittest.mock import patch

from services.classifier import classify_by_rule, classify_email


def test_keyword_priority_important_then_ad_then_check():
    assert classify_by_rule("一次面接のご案内") == ("重要", False)
    assert classify_by_rule("スカウトのお知らせ") == ("広告", False)
    assert classify_by_rule("ES提出のお願い") == ("確認", False)


def test_needs_reply_true_only_for_important_with_matching_subject():
    assert classify_by_rule("一次面接 日程調整のご連絡") == ("重要", True)
    assert classify_by_rule("内定のご連絡") == ("重要", True)
    # 「最終」は重要に一致するが needs_reply 対象キーワード（日程|要返信|ご連絡）は含まない
    assert classify_by_rule("最終選考のお知らせ") == ("重要", False)


def test_no_rule_matches_returns_none():
    assert classify_by_rule("いつもお世話になっております") is None


def test_same_domain_different_subject_yields_different_category():
    # 送信元ドメインではなく件名の内容だけで判定されることの確認
    important = classify_by_rule("一次面接のご案内")
    ad = classify_by_rule("メルマガ：新着情報のお知らせ")

    assert important == ("重要", False)
    assert ad == ("広告", False)


def test_same_input_is_deterministic_and_does_not_call_ai():
    with patch("services.classifier.ai.classify_email_ai") as mock_ai:
        first = classify_email("hr@alphatech.co.jp", "その他の連絡はご確認ください面接")
        second = classify_email("hr@alphatech.co.jp", "その他の連絡はご確認ください面接")

    assert first == second == ("重要", False, "rule")
    mock_ai.assert_not_called()


def test_unresolved_email_falls_back_to_ai():
    with patch("services.classifier.ai.classify_email_ai", return_value=("確認", False, "ai")) as mock_ai:
        result = classify_email("info@example.com", "いつもお世話になっております")

    assert result == ("確認", False, "ai")
    mock_ai.assert_called_once_with("info@example.com", "いつもお世話になっております")


def test_unresolved_email_reports_decided_by_rule_when_ai_itself_falls_back():
    # ai.classify_email_ai がAPIキー未設定等で内部フォールバックした場合、
    # 実際にはAIが判定していないため decided_by は "ai" ではなく "rule" になる
    with patch("services.classifier.ai.classify_email_ai", return_value=("確認", False, "rule")):
        result = classify_email("info@example.com", "いつもお世話になっております")

    assert result == ("確認", False, "rule")
