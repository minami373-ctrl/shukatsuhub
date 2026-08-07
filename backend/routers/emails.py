from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from db import get_session
from models import Company, Email
from services.grouping import group_by_thread, representative_category

router = APIRouter(prefix="/api/emails", tags=["emails"])


@router.get("")
def list_emails(category: str | None = None, session: Session = Depends(get_session)) -> dict:
    query = select(Email)
    if category is not None:
        query = query.where(Email.category == category)
    emails = session.exec(query).all()

    companies = {c.id: c for c in session.exec(select(Company)).all()}

    groups = group_by_thread(emails)
    group_list = []
    for thread_key, members in groups.items():
        members_sorted = sorted(members, key=lambda e: e.received_at, reverse=True)
        latest = members_sorted[0]
        company = companies.get(latest.company_id)
        group_list.append(
            {
                "thread_key": thread_key,
                "company_name": company.name if company else None,
                "domain": company.domain if company else latest.from_address.split("@", 1)[-1],
                "subject": latest.subject,
                "count": len(members_sorted),
                "latest_received_at": latest.received_at,
                "category": representative_category(members_sorted),
                "accounts": sorted({e.account for e in members_sorted}),
                "has_ai_decided": any(e.decided_by == "ai" for e in members_sorted),
                "emails": members_sorted,
            }
        )
    group_list.sort(key=lambda g: g["latest_received_at"], reverse=True)

    return {
        "groups": group_list,
        "ai_decided_count": sum(1 for e in emails if e.decided_by == "ai"),
        "needs_reply_count": sum(1 for e in emails if e.needs_reply),
        "total_count": len(emails),
    }
