"""空き時間・研究にあてられる時間の算出（docs/spec.md §5.3 / §7 受け入れ条件）。

純関数なので DB を使わない。日時は seed の基準日 2026-07-30 に合わせる。
"""

from datetime import date, datetime

from models import Event, Task
from services.freetime import (
    RESEARCH_MINUTES,
    build_free_slots,
    busy_minutes,
    free_hours,
    free_spans,
    research_hours,
    research_spans,
    resolve_day,
)

DAY = date(2026, 7, 30)


def event(external_id: str, start: str, end: str, kind: str = "選考") -> Event:
    return Event(
        id=abs(hash(external_id)) % 10000,
        external_id=external_id,
        title=external_id,
        kind=kind,
        start_at=datetime.fromisoformat(f"2026-07-30T{start}"),
        end_at=datetime.fromisoformat(f"2026-07-30T{end}"),
    )


def task(task_id: int, due: str, estimate: int, *, done: bool = False, label: str = "") -> Task:
    return Task(
        id=task_id,
        title=label or f"タスク{task_id}",
        short_label=label or None,
        due_at=datetime.fromisoformat(f"2026-07-30T{due}"),
        estimate_min=estimate,
        is_done=done,
    )


class TestBusyMinutes:
    def test_可処分時間の外は数えない(self):
        # 07:00〜09:00 のうち 08:00 以降の 1 時間だけを数える
        assert busy_minutes([event("early", "07:00:00", "09:00:00")], DAY) == 60

    def test_重なるイベントを二重に数えない(self):
        events = [
            event("interview", "15:00:00", "16:00:00"),
            event("seminar", "15:30:00", "17:00:00", kind="学業"),
        ]
        # 15:00〜17:00 の 2 時間ぶんだけ
        assert busy_minutes(events, DAY) == 120

    def test_別の日のイベントは数えない(self):
        other_day = Event(
            id=1,
            external_id="tomorrow",
            title="翌日の説明会",
            kind="選考",
            start_at=datetime(2026, 7, 31, 10, 0),
            end_at=datetime(2026, 7, 31, 11, 30),
        )
        assert busy_minutes([other_day], DAY) == 0


class TestResearchHours:
    """研究にあてられる時間＝10:00〜17:00 のうち予定が入っていない時間（2026-08-03 の決定）。"""

    def test_予定が無ければ研究枠まるごと7h(self):
        assert research_hours([], DAY) == RESEARCH_MINUTES / 60

    def test_研究枠に入っている予定だけを引く(self):
        events = [
            event("seminar", "10:30:00", "12:00:00", kind="学業"),  # 1.5h（枠内）
            event("interview", "15:00:00", "16:00:00"),  # 1h（枠内）
            event("report", "18:00:00", "20:00:00", kind="学業"),  # 枠外なので引かない
        ]
        assert research_hours(events, DAY) == 4.5

    def test_枠をまたぐ予定は枠に重なる分だけ引く(self):
        # 09:00〜11:00 のうち研究枠に入るのは 10:00〜11:00 の 1h だけ
        assert research_hours([event("a", "09:00:00", "11:00:00")], DAY) == 6.0

    def test_タスクの見積りでは減らない(self):
        """タスクにチェックを付けても研究時間は動かない（2026-08-03 の決定）。"""
        events = [event("seminar", "10:30:00", "12:00:00", kind="学業")]
        assert research_hours(events, DAY) == 5.5

    def test_研究枠が予定で埋まれば0(self):
        assert research_hours([event("a", "10:00:00", "17:00:00")], DAY) == 0.0

    def test_0_5h刻みに丸める(self):
        # 420 − 20 = 400 分 = 6.666…h → 6.5h
        assert research_hours([event("a", "10:00:00", "10:20:00")], DAY) == 6.5


class TestFreeHours:
    """空き時間＝14h − 研究枠 − 枠外の予定 − 未完了タスクの見積り。"""

    def test_予定もタスクも無ければ研究枠の外の7h(self):
        # 08:00〜10:00（2h）＋ 17:00〜22:00（5h）
        assert free_hours([], [], DAY) == 7.0

    def test_研究枠の中の予定は空き時間を減らさない(self):
        assert free_hours([event("seminar", "10:30:00", "12:00:00", kind="学業")], [], DAY) == 7.0

    def test_研究枠の外の予定は空き時間を減らす(self):
        assert free_hours([event("report", "18:00:00", "20:00:00", kind="学業")], [], DAY) == 5.0

    def test_未完了タスクの見積りを引く(self):
        tasks = [task(1, "12:00:00", 90), task(2, "23:59:00", 60)]
        # 7h − 2.5h = 4.5h
        assert free_hours([], tasks, DAY) == 4.5

    def test_受け入れ条件_タスクを1つ完了させると見積り分だけ増える(self):
        """ペルソナの「手間を減らすと浮く時間が増える」をそのまま数字にした条件。"""
        tasks = [task(1, "12:00:00", 90), task(2, "23:59:00", 60)]

        before = free_hours([], tasks, DAY)
        after = free_hours([], [tasks[0]], DAY)
        assert after - before == 1.0  # 60 分ぶん

    def test_タスクで使い切っても0未満にならない(self):
        assert free_hours([], [task(1, "12:00:00", 60 * 20)], DAY) == 0.0


class TestResearchSpans:
    def test_研究枠の空き区間を返す(self):
        events = [
            event("seminar", "10:30:00", "12:00:00", kind="学業"),
            event("interview", "15:00:00", "16:00:00"),
        ]
        spans = research_spans(events, DAY)
        assert [(s.strftime("%H:%M"), e.strftime("%H:%M")) for s, e in spans] == [
            ("10:00", "10:30"),
            ("12:00", "15:00"),
            ("16:00", "17:00"),
        ]

    def test_予定が無ければ10時から17時の1件(self):
        spans = research_spans([], DAY)
        assert [(s.strftime("%H:%M"), e.strftime("%H:%M")) for s, e in spans] == [("10:00", "17:00")]


class TestFreeSpans:
    def test_予定が無ければ研究枠の前後2件(self):
        spans = free_spans([], DAY)
        assert [(s.strftime("%H:%M"), e.strftime("%H:%M")) for s, e in spans] == [
            ("08:00", "10:00"),
            ("17:00", "22:00"),
        ]

    def test_研究枠の中には空きスロットを作らない(self):
        """研究枠の空きは研究にあてるので、就活タスクを差し込まない。"""
        spans = free_spans([event("seminar", "10:30:00", "12:00:00", kind="学業")], DAY)
        assert all(not (s.hour >= 10 and e.hour <= 17) for s, e in spans)

    def test_30分未満の隙間は空きにしない(self):
        events = [
            event("a", "08:00:00", "09:50:00"),  # 09:50〜10:00 の 10 分しか残らない
            event("b", "17:00:00", "22:00:00"),
        ]
        assert free_spans(events, DAY) == []


class TestBuildFreeSlots:
    def test_受け入れ条件_締切が近い順に1つずつ差し込み重複しない(self):
        """spec.md §7「空きスロットへのタスク差し込み」。同じタスクが2つのスロットに出ない。"""
        events = [
            event("seminar", "10:30:00", "12:00:00", kind="学業"),
            event("interview", "15:00:00", "16:00:00"),
            event("report", "18:00:00", "20:00:00", kind="学業"),
        ]
        tasks = [
            task(1, "12:00:00", 15, label="日程回答"),
            task(2, "17:00:00", 30, label="説明会予習"),
        ]

        slots = build_free_slots(events, tasks, DAY)

        # 研究枠の外だけ。08:00-10:00 / 17:00-18:00 / 20:00-22:00 の3件
        assert [(s.start.strftime("%H:%M"), s.end.strftime("%H:%M")) for s in slots] == [
            ("08:00", "10:00"),
            ("17:00", "18:00"),
            ("20:00", "22:00"),
        ]
        labels = [s.suggested_task.short_label if s.suggested_task else None for s in slots]
        assert labels == ["日程回答", "説明会予習", None]
        # 同じタスクが2回出ていない
        used = [label for label in labels if label is not None]
        assert len(used) == len(set(used))

    def test_タスクが無ければ差し込みなし(self):
        slots = build_free_slots([], [], DAY)
        assert [s.suggested_task for s in slots] == [None, None]
        assert [s.minutes for s in slots] == [120, 300]

    def test_締切が同じなら_id順で安定する(self):
        tasks = [task(2, "23:59:00", 30, label="後"), task(1, "23:59:00", 30, label="先")]
        slots = build_free_slots([], tasks, DAY)
        assert [s.suggested_task.short_label for s in slots] == ["先", "後"]


def test_resolve_day_は未指定なら今日の日付を返す():
    # 2026-08-05 にチームで合意の上、既定の対象日は固定値ではなく実際の今日にした
    assert resolve_day() == date.today()
    assert resolve_day(date(2026, 8, 3)) == date(2026, 8, 3)
