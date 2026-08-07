import re

REPLY_FORWARD_PREFIX = re.compile(r"^(?:re|fwd|fw)\s*[:：]\s*|^(?:返信|転送)\s*[:：]\s*", re.IGNORECASE)
CATEGORY_STRENGTH = {"重要": 3, "確認": 2, "広告": 1}


def domain_of(address: str) -> str:
    return address.split("@", 1)[1] if "@" in address else ""


def resolve_company_id(from_address: str, companies: list) -> int | None:
    domain = domain_of(from_address)
    for company in companies:
        if company.domain == domain:
            return company.id
    return None


def normalize_subject(subject: str) -> str:
    normalized = subject.replace("　", " ")
    while True:
        stripped = REPLY_FORWARD_PREFIX.sub("", normalized)
        if stripped == normalized:
            break
        normalized = stripped
    return normalized.strip()


def build_thread_key(from_address: str, subject: str, companies: list) -> str:
    company_id = resolve_company_id(from_address, companies)
    prefix = str(company_id) if company_id is not None else domain_of(from_address)
    return f"{prefix}|{normalize_subject(subject)}"


def group_by_thread(emails: list) -> dict:
    groups: dict[str, list] = {}
    for email in emails:
        groups.setdefault(email.thread_key, []).append(email)
    return groups


def representative_category(emails: list) -> str:
    return max((e.category for e in emails), key=lambda category: CATEGORY_STRENGTH.get(category, 0))
