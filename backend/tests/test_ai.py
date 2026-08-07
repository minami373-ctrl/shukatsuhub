from unittest.mock import MagicMock, patch

from services import ai


def _mock_response(parsed=None, refusal=None, status="completed"):
    """openai の ParsedResponse（Responses API）相当のモックを組み立てる。"""
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


def test_classify_email_ai_without_api_key_falls_back_with_decided_by_rule():
    with patch("services.ai._get_client", return_value=None):
        result = ai.classify_email_ai("info@example.com", "件名")

    assert result == ("確認", False, "rule")


def test_classify_email_ai_returns_parsed_result_with_decided_by_ai():
    parsed = ai.EmailCategory(category="確認", needs_reply=False, reason="dummy")
    mock_client = MagicMock()
    mock_client.responses.parse.return_value = _mock_response(parsed=parsed)

    with patch("services.ai._get_client", return_value=mock_client):
        result = ai.classify_email_ai("info@example.com", "いつもお世話になっております")

    assert result == ("確認", False, "ai")
    mock_client.responses.parse.assert_called_once()


def test_classify_email_ai_retries_once_then_falls_back_with_decided_by_rule():
    mock_client = MagicMock()
    mock_client.responses.parse.side_effect = TimeoutError("timeout")

    with patch("services.ai._get_client", return_value=mock_client):
        result = ai.classify_email_ai("info@example.com", "件名")

    assert result == ("確認", False, "rule")
    assert mock_client.responses.parse.call_count == 2


def test_classify_email_ai_refusal_falls_back_with_decided_by_rule_without_reading_content():
    mock_client = MagicMock()
    mock_client.responses.parse.return_value = _mock_response(refusal="ポリシー違反のため拒否")

    with patch("services.ai._get_client", return_value=mock_client):
        result = ai.classify_email_ai("info@example.com", "件名")

    assert result == ("確認", False, "rule")
    mock_client.responses.parse.assert_called_once()


def test_classify_email_ai_incomplete_status_falls_back_with_decided_by_rule():
    mock_client = MagicMock()
    mock_client.responses.parse.return_value = _mock_response(status="incomplete")

    with patch("services.ai._get_client", return_value=mock_client):
        result = ai.classify_email_ai("info@example.com", "件名")

    assert result == ("確認", False, "rule")


TEMPLATE_ITEMS = [
    {"question": "テンプレ質問", "answer_draft": "テンプレ回答", "category": "志望動機"},
]


def _qa_sheet(count: int) -> "ai.QASheet":
    categories = ["志望動機", "ガクチカ", "逆質問"]
    return ai.QASheet(
        items=[
            ai.QAItem(
                question=f"質問{i}",
                answer_draft=f"回答{i}",
                category=categories[i % len(categories)],
            )
            for i in range(count)
        ]
    )


def test_generate_qa_without_api_key_falls_back_to_template():
    with patch("services.ai._get_client", return_value=None):
        items, source = ai.generate_qa({"gakuchika": "研究の話"}, "アルファテック", "", TEMPLATE_ITEMS)

    assert items == TEMPLATE_ITEMS
    assert source == "template"


def test_generate_qa_returns_six_structured_items_from_mock():
    mock_client = MagicMock()
    mock_client.responses.parse.return_value = _mock_response(parsed=_qa_sheet(6))

    with patch("services.ai._get_client", return_value=mock_client):
        items, source = ai.generate_qa({"gakuchika": "研究の話"}, "アルファテック", "IT", TEMPLATE_ITEMS)

    assert source == "ai"
    assert len(items) == 6
    assert all({"question", "answer_draft", "category"} <= item.keys() for item in items)
    mock_client.responses.parse.assert_called_once()


def test_generate_qa_retries_once_then_falls_back_to_template_on_repeated_failure():
    mock_client = MagicMock()
    mock_client.responses.parse.side_effect = ConnectionError("down")

    with patch("services.ai._get_client", return_value=mock_client):
        items, source = ai.generate_qa({"gakuchika": "研究の話"}, "アルファテック", "", TEMPLATE_ITEMS)

    assert items == TEMPLATE_ITEMS
    assert source == "template"
    assert mock_client.responses.parse.call_count == 2


def test_generate_qa_refusal_falls_back_to_template_without_reading_content():
    mock_client = MagicMock()
    mock_client.responses.parse.return_value = _mock_response(refusal="ポリシー違反のため拒否")

    with patch("services.ai._get_client", return_value=mock_client):
        items, source = ai.generate_qa({"gakuchika": "研究の話"}, "アルファテック", "", TEMPLATE_ITEMS)

    assert items == TEMPLATE_ITEMS
    assert source == "template"
    mock_client.responses.parse.assert_called_once()
