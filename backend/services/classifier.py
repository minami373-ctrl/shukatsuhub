import re

from services import ai

IMPORTANT_PATTERN = re.compile(r"面接|日程|選考結果|内定|お祈り|最終", re.IGNORECASE)
AD_PATTERN = re.compile(r"配信停止|メルマガ|セミナー案内|PR|スカウト|おすすめ求人", re.IGNORECASE)
CHECK_PATTERN = re.compile(r"ES|エントリーシート|提出|期限|リマインド|説明会", re.IGNORECASE)
NEEDS_REPLY_PATTERN = re.compile(r"日程|要返信|ご連絡", re.IGNORECASE)


def classify_by_rule(subject: str) -> tuple[str, bool] | None:
    """件名の内容だけで分類できれば (category, needs_reply) を返す。保留なら None。

    送信元ドメインは判定に使わない（同じ企業からのメールでも件名次第でカテゴリが変わる）。
    """
    if IMPORTANT_PATTERN.search(subject):
        return "重要", bool(NEEDS_REPLY_PATTERN.search(subject))
    if AD_PATTERN.search(subject):
        return "広告", False
    if CHECK_PATTERN.search(subject):
        return "確認", False
    return None


def classify_email(from_address: str, subject: str) -> tuple[str, bool, str]:
    """件名内容によるルール優先＋AIフォールバックで (category, needs_reply, decided_by) を返す。"""
    rule_result = classify_by_rule(subject)
    if rule_result is not None:
        category, needs_reply = rule_result
        return category, needs_reply, "rule"

    return ai.classify_email_ai(from_address, subject)
