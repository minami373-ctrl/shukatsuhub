"""今日画面 API（docs/spec.md §4.1 / §5.3 / API 一覧）。

GET /api/today … ヒーロー指標・今日やること・今日返すべきメール・タイムラインの材料

ヒーローの1文と「空き Nh ― {タスク名} をここに」の文言はフロント側（表示ロジック）で
組み立てる。ここが返すのは数値と素材だけにして、pytest では計算の正しさだけを見る。
"""

from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlmodel import Session, select

from db import get_session
from models import Company, Email, Event
from routers.tasks import TaskOut, _company_names, _to_out, open_tasks, tasks_for_today
from services.freetime import (
    build_free_slots,
    free_hours,
    research_hours,
    research_spans,
    resolve_day,
    resolve_now,
)

router = APIRouter(prefix="/api", tags=["today"])


class TodayEvent(BaseModel):
    id: int
    title: str
    kind: str  # 選考 / 学業（表示色を決める）
    start_at: datetime
    end_at: datetime
    location: str | None


class TodayFreeSlot(BaseModel):
    """空きスロット1件。suggested_task_label は差し込むタスクの短縮名（無ければ None）。"""

    start: datetime
    end: datetime
    minutes: int
    suggested_task_id: int | None
    suggested_task_label: str | None


class TodayEmail(BaseModel):
    id: int
    subject: str
    category: str
    from_name: str | None
    company_name: str | None
    received_at: datetime


class TodayResearchSlot(BaseModel):
    """研究にあてられる区間（10:00〜17:00 のうち予定が入っていない時間）。"""

    start: datetime
    end: datetime
    minutes: int


class TodayResponse(BaseModel):
    date: date
    #: ヒーローの指標（§4.1）
    research_hours: float
    #: 研究枠の外（08:00〜10:00 / 17:00〜22:00）の空き時間
    free_hours: float
    open_task_count: int
    event_count: int
    needs_reply_count: int
    #: 締切が最も近い未完了タスクの短縮名。1文の「まず ○○ から。」に使う
    nearest_task_label: str | None
    tasks: list[TaskOut]
    emails: list[TodayEmail]
    events: list[TodayEvent]
    free_slots: list[TodayFreeSlot]
    research_slots: list[TodayResearchSlot]
    #: タイムライン末尾に出す翌日の先頭イベント1件（無ければ None）
    tomorrow_event: TodayEvent | None


def _events_on(session: Session, day: date) -> list[Event]:
    """対象日に重なるイベントを開始順に返す（日をまたぐ予定も拾う）。"""
    day_start = datetime.combine(day, time.min)
    day_end = datetime.combine(day, time.max)
    statement = (
        select(Event)
        .where(Event.start_at <= day_end, Event.end_at >= day_start)
        .order_by(Event.start_at)
    )
    return list(session.exec(statement))


def _to_event_out(event: Event) -> TodayEvent:
    return TodayEvent(
        id=event.id or 0,
        title=event.title,
        kind=event.kind,
        start_at=event.start_at,
        end_at=event.end_at,
        location=event.location,
    )


def _needs_reply_emails(session: Session) -> list[TodayEmail]:
    """要返信メールを受信日時の新しい順に返す。

    日付で絞らないのは、返していないメールは翌日以降も「返すべきメール」だから。
    表示件数（2件まで）は画面側で切る（§4.1）。
    """
    names = {c.id: c.name for c in session.exec(select(Company)) if c.id is not None}
    statement = (
        select(Email)
        .where(Email.needs_reply == True)  # noqa: E712
        .order_by(Email.received_at.desc())
    )
    return [
        TodayEmail(
            id=mail.id or 0,
            subject=mail.subject,
            category=mail.category,
            from_name=mail.from_name,
            company_name=names.get(mail.company_id) if mail.company_id else None,
            received_at=mail.received_at,
        )
        for mail in session.exec(statement)
    ]


@router.get("/today", response_model=TodayResponse)
def get_today(
    day: date | None = Query(default=None, alias="date", description="対象日（省略時は seed の基準日）"),
    session: Session = Depends(get_session),
) -> TodayResponse:
    target = resolve_day(day)

    events = _events_on(session, target)
    pending = open_tasks(session, target)
    names = _company_names(session)
    emails = _needs_reply_emails(session)

    slots = build_free_slots(events, pending, target)
    nearest = pending[0] if pending else None

    tomorrow = _events_on(session, target + timedelta(days=1))

    return TodayResponse(
        date=target,
        research_hours=research_hours(events, target),
        free_hours=free_hours(events, pending, target),
        open_task_count=len(pending),
        event_count=len(events),
        needs_reply_count=len(emails),
        nearest_task_label=(nearest.short_label or nearest.title) if nearest else None,
        tasks=[
            _to_out(task, names, resolve_now(target))
            for task in tasks_for_today(session, target)
        ],
        emails=emails,
        events=[_to_event_out(event) for event in events],
        free_slots=[
            TodayFreeSlot(
                start=slot.start,
                end=slot.end,
                minutes=slot.minutes,
                suggested_task_id=slot.suggested_task.id if slot.suggested_task else None,
                suggested_task_label=(
                    (slot.suggested_task.short_label or slot.suggested_task.title)
                    if slot.suggested_task
                    else None
                ),
            )
            for slot in slots
        ],
        research_slots=[
            TodayResearchSlot(
                start=start,
                end=end,
                minutes=int((end - start).total_seconds() // 60),
            )
            for start, end in research_spans(events, target)
        ],
        tomorrow_event=_to_event_out(tomorrow[0]) if tomorrow else None,
    )
