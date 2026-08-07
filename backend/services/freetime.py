"""空き時間・研究にあてられる時間の算出（docs/spec.md §5.3）。

純関数だけを置く。DB もリクエストも触らない（pytest で単体テストするため）。

計算の前提（時間帯が2つあるので混同しないこと）

1日を「研究できる時間帯」と「それ以外」に分けて数える（2026-08-03 の決定）。
研究は大学院に居る間しかできないため、その時間帯の空きは就活タスクに使わない。

可処分時間は 08:00〜22:00 の 14h（spec.md §5.3）。その内訳を2つに分ける。

| 枠 | 範囲 | 意味 |
|---|---|---|
| 研究枠 | 10:00〜17:00（7h） | ここの空き＝**研究にあてられる時間** |
| 研究枠の外 | 08:00〜10:00 / 17:00〜22:00（計 7h） | ここの空き＝**空き時間**（就活タスクを差し込む） |

1. 研究にあてられる時間 = 7h − 研究枠に入っているイベントの占有時間
   - **タスクの見積りは引かない。**研究できる時間帯は予定だけで決まる
2. 空き時間 = 14h − 研究枠 7h − 研究枠の外の予定 − **未完了タスクの見積り合計**
   - タスクを引くのは「連絡対応の手間を減らすと浮く時間が増える」というペルソナの
     訴求を数字にするため。チェックを付けると見積り分だけ空き時間が増える
3. どちらも重なり合うイベントは重複を除いた実占有時間で数え、負なら 0、0.5h 刻みに丸める
4. タスクを差し込む空きスロットは**研究枠の外**の 30 分以上の区間だけ。
   締切が最も近い未完了タスクを1つずつ割り当てる（同じタスクを使い回さない）
"""

import math
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from models import Event, Task

#: 空きスロットを出す範囲。カレンダーの表示範囲（eventMap.ts）とも同じ値。
DAY_START_HOUR = 8
DAY_END_HOUR = 22
DISPOSABLE_MINUTES = (DAY_END_HOUR - DAY_START_HOUR) * 60

#: 研究にあてられる時間を数える範囲。研究室に居られる時間帯として 10:00〜17:00 に絞る。
#: 空きスロット（08:00〜22:00）とは意図的に別の枠にしている。
RESEARCH_START_HOUR = 10
RESEARCH_END_HOUR = 17
RESEARCH_MINUTES = (RESEARCH_END_HOUR - RESEARCH_START_HOUR) * 60

#: 空きスロットとして扱う最小の長さ（分）。これ未満の隙間は表示しない。
MIN_SLOT_MINUTES = 30

#: seed の基準日（docs/spec.md 付録「ダミーデータの一貫性」）。デモの固定表示用に残す。
#: 2026-08-05 にチームで合意の上、既定の対象日は実際の date.today() に切り替えた。
SEED_TODAY = date(2026, 7, 30)

#: 基準時刻（docs/spec.md 付録「基準日時 2026-07-30 12:20」）。
#: 「締切を過ぎているのに未完了」の判定で、当日以外の日付と組み合わせる際に使う
#: （当日は resolve_now() が実際の現在時刻を返すため使われない）。
SEED_NOW_TIME = time(hour=12, minute=20)


@dataclass(frozen=True)
class FreeSlot:
    """空きスロット1件。suggested_task は差し込むタスクが無ければ None（§5.3 エラー時）。"""

    start: datetime
    end: datetime
    suggested_task: Task | None

    @property
    def minutes(self) -> int:
        return int((self.end - self.start).total_seconds() // 60)


def resolve_day(value: date | None = None) -> date:
    """対象日を決める。未指定なら実際の今日の日付を使う（2026-08-05〜）。"""
    return value if value is not None else date.today()


def resolve_now(day: date) -> datetime:
    """対象日の「現在時刻」。当日なら実際の現在時刻、それ以外の日付は基準時刻で代用する
    （タスクの締切日など、当日以外の日付と比較するために呼ばれることがあるため）。
    """
    if day == date.today():
        return datetime.now()
    return datetime.combine(day, SEED_NOW_TIME)


def day_window(day: date) -> tuple[datetime, datetime]:
    """空きスロットを出す範囲（08:00〜22:00）を返す。"""
    return (
        datetime.combine(day, time(hour=DAY_START_HOUR)),
        datetime.combine(day, time(hour=DAY_END_HOUR)),
    )


def research_window(day: date) -> tuple[datetime, datetime]:
    """研究にあてられる時間を数える範囲（10:00〜17:00）を返す。"""
    return (
        datetime.combine(day, time(hour=RESEARCH_START_HOUR)),
        datetime.combine(day, time(hour=RESEARCH_END_HOUR)),
    )


def merged_busy_spans(
    events: list[Event],
    day: date,
    window: tuple[datetime, datetime] | None = None,
) -> list[tuple[datetime, datetime]]:
    """枠に収まる占有区間を、重なりを潰して開始順に返す。

    window を省略すると空きスロットの枠（08:00〜22:00）で数える。
    重なりを潰すのは、面接とゼミが重なっている日に同じ時間を二重に引かないため。
    """
    window_start, window_end = window if window is not None else day_window(day)

    clipped: list[tuple[datetime, datetime]] = []
    for event in events:
        start = max(event.start_at, window_start)
        end = min(event.end_at, window_end)
        if end > start:
            clipped.append((start, end))
    clipped.sort()

    merged: list[list[datetime]] = []
    for start, end in clipped:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(start, end) for start, end in merged]


def busy_minutes(
    events: list[Event],
    day: date,
    window: tuple[datetime, datetime] | None = None,
) -> int:
    """枠に収まるイベントの実占有時間（分）。重なりは二重に数えない。"""
    return sum(
        int((end - start).total_seconds() // 60)
        for start, end in merged_busy_spans(events, day, window)
    )


def research_hours(events: list[Event], day: date) -> float:
    """研究にあてられる時間（h）。10:00〜17:00 のうち予定が入っていない時間。

    0.5h 刻みに丸め、予定で埋まっていれば 0。
    タスクの見積りは引かない（2026-08-03 の決定。冒頭の docstring を参照）。
    """
    remaining = RESEARCH_MINUTES - busy_minutes(events, day, research_window(day))
    if remaining <= 0:
        return 0.0
    # 30 分単位に丸めてから 2 で割る（0.5h 刻み・小数第1位まで）。
    # 組み込みの round() は偶数丸めなので使わない（7.25h が 7.0h、7.75h が 8.0h と
    # ちょうど半分のときの挙動が揺れて説明できなくなるため）。常に半数切り上げにする。
    return math.floor(remaining / 30 + 0.5) / 2


def free_hours(events: list[Event], open_tasks: list[Task], day: date) -> float:
    """空き時間（h）。可処分時間のうち、研究にも予定にも就活タスクにも取られていない時間。

    空き時間 = 14h − 研究枠 7h − 研究枠の外の予定 − 未完了タスクの見積り合計

    研究枠を除くのは、そこは研究にあてる前提で二重に数えないため。
    タスクの見積りをここから引くのは、「連絡対応の手間を減らすと浮く時間が増える」という
    ペルソナの訴求をそのまま数字にするため（チェックを付けると見積り分だけ増える）。
    """
    free = sum(
        int((end - start).total_seconds() // 60) for start, end in _free_spans_raw(events, day)
    )
    minutes = free - sum(task.estimate_min for task in open_tasks)
    if minutes <= 0:
        return 0.0
    return math.floor(minutes / 30 + 0.5) / 2


def _gaps(
    busy: list[tuple[datetime, datetime]],
    window: tuple[datetime, datetime],
    minimum: timedelta,
) -> list[tuple[datetime, datetime]]:
    """枠から占有区間を引いた連続区間のうち、minimum 以上のものを返す。"""
    window_start, window_end = window

    spans: list[tuple[datetime, datetime]] = []
    cursor = window_start
    for start, end in busy:
        if start - cursor >= minimum:
            spans.append((cursor, start))
        cursor = max(cursor, end)
    if window_end - cursor >= minimum:
        spans.append((cursor, window_end))
    return spans


def research_spans(events: list[Event], day: date) -> list[tuple[datetime, datetime]]:
    """研究にあてられる区間。10:00〜17:00 のうち予定が入っていない 30 分以上の区間。"""
    window = research_window(day)
    return _gaps(merged_busy_spans(events, day, window), window, timedelta(minutes=MIN_SLOT_MINUTES))


def _free_spans_raw(events: list[Event], day: date) -> list[tuple[datetime, datetime]]:
    """空き区間（長さの下限なし）。合計を出すのに使う。"""
    window = day_window(day)
    # 研究枠そのものを「埋まっている時間」として扱い、予定と一緒に潰す
    busy = merged_busy_spans([*events, _research_block(day)], day, window)
    return _gaps(busy, window, timedelta(0))


def free_spans(events: list[Event], day: date) -> list[tuple[datetime, datetime]]:
    """タスクを差し込む空きスロット。研究枠の外（08:00〜10:00 / 17:00〜22:00）の 30 分以上の区間。"""
    window = day_window(day)
    busy = merged_busy_spans([*events, _research_block(day)], day, window)
    return _gaps(busy, window, timedelta(minutes=MIN_SLOT_MINUTES))


def _research_block(day: date) -> Event:
    """研究枠を占有区間として扱うためのダミー。DB には入れない（計算の中だけで使う）。"""
    start, end = research_window(day)
    return Event(external_id="__research__", title="研究", kind="学業", start_at=start, end_at=end)


def build_free_slots(events: list[Event], open_tasks: list[Task], day: date) -> list[FreeSlot]:
    """空きスロットに未完了タスクを1つずつ差し込む（§5.3-4）。

    締切が近い順に、早い時間帯のスロットから割り当てる。
    同じタスクを2つのスロットに出さないため、割り当てたものは使い回さない。
    タスクが尽きたスロットは suggested_task = None（表示は「空き Nh」だけ）。
    """
    # 締切が同じときは id 順にして、同じ入力なら常に同じ結果になるようにする
    queue = sorted(open_tasks, key=lambda t: (t.due_at, t.id or 0))

    slots: list[FreeSlot] = []
    for index, (start, end) in enumerate(free_spans(events, day)):
        suggested = queue[index] if index < len(queue) else None
        slots.append(FreeSlot(start=start, end=end, suggested_task=suggested))
    return slots
