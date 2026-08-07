"""タスク API（docs/spec.md §4.1 / API 一覧、`03-today-focus/FEATURE_PAGE_SPECS.md` §6）。

GET    /api/tasks        … タスク・締め切りページの一覧（今日 / 今週 / すべて / 完了）
GET    /api/tasks/today  … 締切が対象日以前かつ未完了 ＋ 当日締切の完了分
POST   /api/tasks        … 追加（内容・期限・重要度）
PATCH  /api/tasks/{id}   … is_done の反転、および内容・期限・重要度の変更
DELETE /api/tasks/{id}   … 削除

対象日は既定で seed の基準日（services.freetime.SEED_TODAY）。
クエリ `date` で明示できるようにしてあるのは、実データ連携後に今日の日付を渡すため。

「重要度」は `docs/spec.md` §6 の `badge`（最優先 / 要返信 / 準備）で表す。
専用のカラムを足すと仕様書の変更になるため、既存の3値をそのまま重要度として使う。
"""

from datetime import date, datetime, time, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field, field_validator
from sqlmodel import Session, select

from db import get_session
from models import Company, Task
from services.freetime import resolve_day, resolve_now

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


class TaskOut(BaseModel):
    """一覧の1行。company_name は表示用なので Task には保存しない導出値。"""

    id: int
    title: str
    short_label: str | None
    due_at: datetime
    estimate_min: int
    is_done: bool
    #: 重要度（度合い）。高 / 中 / 低
    priority: str
    #: 表示タグ（行動の種類）。重要度とは別の軸
    badge: str | None
    company_id: int | None
    company_name: str | None
    #: 締切を過ぎているのに未完了。画面では黄色文字にして気付けるようにする
    is_overdue: bool


#: 重要度（度合い）。`docs/spec.md` §6 の priority。既定は「中」
Priority = Literal["高", "中", "低"]

#: 表示タグ（行動の種類）。`docs/spec.md` §6 の badge。重要度とは別の軸なので混ぜない
Badge = Literal["最優先", "要返信", "準備"]

#: タイトルの上限。spec.md に規定が無いので、1行に収まる長さとしてここで決める
TITLE_MAX = 200
SHORT_LABEL_MAX = 40


def _require_text(value: str) -> str:
    """前後の空白を落として空なら弾く。空白だけの入力を通すと一覧に空行が並ぶため。"""
    stripped = value.strip()
    if not stripped:
        raise ValueError("空にできません")
    return stripped


class TaskCreate(BaseModel):
    """追加フォームの入力（§6「＋ タスクを追加」）。内容・期限・重要度の3つが本体。"""

    title: str = Field(max_length=TITLE_MAX)
    due_at: datetime
    #: 空き時間の算出に使う見積り（spec.md §5.3）。既定 30 分
    estimate_min: int = Field(default=30, ge=0)
    #: 重要度（度合い）。省略時は「中」
    priority: Priority = "中"
    #: 表示タグ（行動の種類）。未選択は None（タグを出さない）
    badge: Badge | None = None
    #: ヒーローの1文に使う短縮名。省略時は title をそのまま使う
    short_label: str | None = Field(default=None, max_length=SHORT_LABEL_MAX)
    company_id: int | None = None

    @field_validator("title")
    @classmethod
    def _title_not_blank(cls, value: str) -> str:
        return _require_text(value)

    @field_validator("short_label")
    @classmethod
    def _short_label_blank_to_none(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class TaskPatch(BaseModel):
    """変更。渡された項目だけを更新する（未指定と null を区別するため exclude_unset を使う）。

    `is_done` だけを渡す今日画面のチェックボックスとも互換を保つ。
    """

    is_done: bool | None = None
    title: str | None = Field(default=None, max_length=TITLE_MAX)
    due_at: datetime | None = None
    estimate_min: int | None = Field(default=None, ge=0)
    priority: Priority | None = None
    badge: Badge | None = None
    short_label: str | None = Field(default=None, max_length=SHORT_LABEL_MAX)
    company_id: int | None = None

    @field_validator("title")
    @classmethod
    def _title_not_blank(cls, value: str | None) -> str | None:
        return None if value is None else _require_text(value)


#: 一覧の絞り込み。FEATURE_PAGE_SPECS.md §6 のセグメント（既定は today）
Scope = Literal["today", "week", "all", "done"]


class TaskCounts(BaseModel):
    """ページヘッダの「今日 5件・期限切れ 1件・今週 12件」（§6）。

    絞り込みを切り替えても数字が動かないよう、scope とは独立に数える。
    """

    today: int
    overdue: int
    week: int


class TaskListResponse(BaseModel):
    scope: Scope
    date: date
    #: 期限切れ判定の基準時刻。フロントの期限タグもこれと比較する（§5.3 の SEED_NOW_TIME）
    now: datetime
    counts: TaskCounts
    tasks: list[TaskOut]


def _company_names(session: Session) -> dict[int, str]:
    return {c.id: c.name for c in session.exec(select(Company)) if c.id is not None}


def _to_out(task: Task, names: dict[int, str], now: datetime) -> TaskOut:
    return TaskOut(
        id=task.id or 0,
        title=task.title,
        short_label=task.short_label,
        due_at=task.due_at,
        estimate_min=task.estimate_min,
        is_done=task.is_done,
        priority=task.priority,
        badge=task.badge,
        company_id=task.company_id,
        company_name=names.get(task.company_id) if task.company_id else None,
        is_overdue=not task.is_done and task.due_at < now,
    )


def open_tasks(session: Session, day: date) -> list[Task]:
    """締切が対象日の終わりまでの未完了タスク。締切の近い順。

    研究にあてられる時間の計算に使うので、完了済みは含めない（§5.3）。
    """
    day_end = datetime.combine(day, time.max)
    statement = (
        select(Task)
        .where(Task.is_done == False, Task.due_at <= day_end)  # noqa: E712
        .order_by(Task.due_at, Task.id)
    )
    return list(session.exec(statement))


def done_tasks_on(session: Session, day: date) -> list[Task]:
    """対象日に締切がある完了済みタスク（§4.1「＋当日完了分」）。

    完了時刻のカラムは spec.md §6 に無いため、締切日で当日分を判定している。
    """
    day_start = datetime.combine(day, time.min)
    day_end = datetime.combine(day, time.max)
    statement = (
        select(Task)
        .where(Task.is_done == True, Task.due_at >= day_start, Task.due_at <= day_end)  # noqa: E712
        .order_by(Task.due_at, Task.id)
    )
    return list(session.exec(statement))


def tasks_for_today(session: Session, day: date) -> list[Task]:
    """画面に出す並び。**締切順に一列**にする。

    完了済みを末尾に寄せない。チェックを付けた行がその場に留まる方が、
    どれを片付けたかが分かりやすいため（打ち消し線で完了を表す）。
    """
    return sorted(
        open_tasks(session, day) + done_tasks_on(session, day),
        key=lambda t: (t.due_at, t.id or 0),
    )


def week_window(day: date) -> tuple[datetime, datetime]:
    """対象日を含む週（月曜〜日曜）の両端。

    「今週」を暦の週で数える。基準日 2026-07-30（木）なら 07/27〜08/02。
    対象日からの7日間にしないのは、日が進むと週の範囲が動いて件数の説明が付かなくなるため。
    """
    monday = day - timedelta(days=day.weekday())
    return (
        datetime.combine(monday, time.min),
        datetime.combine(monday + timedelta(days=6), time.max),
    )


def week_tasks(session: Session, day: date) -> list[Task]:
    """対象日を含む週に締切があるタスク（完了済みも含む）。締切順。"""
    start, end = week_window(day)
    statement = (
        select(Task).where(Task.due_at >= start, Task.due_at <= end).order_by(Task.due_at, Task.id)
    )
    return list(session.exec(statement))


def all_tasks(session: Session) -> list[Task]:
    """全タスク（完了済みも含む）。締切順。"""
    return list(session.exec(select(Task).order_by(Task.due_at, Task.id)))


def done_tasks(session: Session) -> list[Task]:
    """完了済みタスク。締切順。"""
    statement = (
        select(Task).where(Task.is_done == True).order_by(Task.due_at, Task.id)  # noqa: E712
    )
    return list(session.exec(statement))


def overdue_count(session: Session, day: date, now: datetime) -> int:
    """締切を過ぎているのに未完了の件数（ページヘッダの「期限切れ N件」）。"""
    return sum(1 for task in open_tasks(session, day) if task.due_at < now)


def tasks_for_scope(session: Session, scope: Scope, day: date) -> list[Task]:
    if scope == "today":
        return tasks_for_today(session, day)
    if scope == "week":
        return week_tasks(session, day)
    if scope == "done":
        return done_tasks(session)
    return all_tasks(session)


@router.get("", response_model=TaskListResponse)
def list_tasks(
    scope: Scope = Query(default="today", description="今日 / 今週 / すべて / 完了"),
    day: date | None = Query(default=None, alias="date", description="対象日（省略時は seed の基準日）"),
    session: Session = Depends(get_session),
) -> TaskListResponse:
    """タスク・締め切りページの一覧（FEATURE_PAGE_SPECS.md §6）。

    期限タグの色分けは表示側の判断なので、ここでは基準時刻 `now` を返すだけにする。
    """
    target = resolve_day(day)
    now = resolve_now(target)
    names = _company_names(session)

    return TaskListResponse(
        scope=scope,
        date=target,
        now=now,
        counts=TaskCounts(
            today=len(open_tasks(session, target)),
            overdue=overdue_count(session, target, now),
            week=len(week_tasks(session, target)),
        ),
        tasks=[_to_out(task, names, now) for task in tasks_for_scope(session, scope, target)],
    )


@router.get("/today", response_model=list[TaskOut])
def list_today_tasks(
    day: date | None = Query(default=None, alias="date", description="対象日（省略時は seed の基準日）"),
    session: Session = Depends(get_session),
) -> list[TaskOut]:
    target = resolve_day(day)
    names = _company_names(session)
    now = resolve_now(target)
    return [_to_out(task, names, now) for task in tasks_for_today(session, target)]


def _check_company(session: Session, company_id: int | None) -> None:
    """存在しない企業に紐づけさせない（表示で company_name が消えるだけの不整合を防ぐ）。"""
    if company_id is not None and session.get(Company, company_id) is None:
        raise HTTPException(status_code=422, detail="その企業は登録されていません")


@router.post("", response_model=TaskOut, status_code=status.HTTP_201_CREATED)
def create_task(body: TaskCreate, session: Session = Depends(get_session)) -> TaskOut:
    """タスクを追加する（§6「＋ タスクを追加」）。

    口頭で言われた予定をその場で入れられるように、内容・期限・重要度だけで登録できる。
    """
    _check_company(session, body.company_id)

    task = Task(
        title=body.title,
        short_label=body.short_label,
        due_at=body.due_at,
        estimate_min=body.estimate_min,
        priority=body.priority,
        badge=body.badge,
        company_id=body.company_id,
    )
    session.add(task)
    session.commit()
    session.refresh(task)
    return _to_out(task, _company_names(session), resolve_now(task.due_at.date()))


@router.patch("/{task_id}", response_model=TaskOut)
def update_task(
    task_id: int,
    body: TaskPatch,
    session: Session = Depends(get_session),
) -> TaskOut:
    """渡された項目だけを更新する。

    チェックボックスは `is_done` だけを送ってくる（§4.1）。編集フォームは内容・期限・
    重要度を送る（§6）。未指定の項目は触らないので、両方を1つの口で受けられる。
    """
    task = session.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="タスクが見つかりません")

    # 未指定と「null にする」を区別する。exclude_unset を外すと badge が毎回消える
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=422, detail="変更する項目がありません")

    if "company_id" in changes:
        _check_company(session, changes["company_id"])

    # priority は必須（既定「中」）。badge のように null で外せる項目ではない
    if "priority" in changes and changes["priority"] is None:
        raise HTTPException(status_code=422, detail="重要度は 高 / 中 / 低 のいずれかを指定してください")

    for field, value in changes.items():
        setattr(task, field, value)

    session.add(task)
    session.commit()
    session.refresh(task)
    return _to_out(task, _company_names(session), resolve_now(task.due_at.date()))


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_task(task_id: int, session: Session = Depends(get_session)) -> Response:
    """タスクを1件削除する（§6「削除」）。

    消すのは指定された1件だけ。テーブルの全件削除は行わない（CLAUDE.md §0-⑥）。
    """
    task = session.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="タスクが見つかりません")

    session.delete(task)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
