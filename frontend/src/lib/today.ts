/** 今日画面の表示ロジック（純関数）。Vitest でテストするのはこのファイル。
 *
 *  docs/spec.md §4.1。API（GET /api/today）は数値と素材だけを返し、
 *  「今日やることは 5件。まず ES提出 から。」のような文言はここで組み立てる。
 */

import type { TodayEvent, TodayFreeSlot, TodayResearchSlot } from '../api/today'

export type TimelineRow = {
  key: string
  /** 左端に出す時刻（翌日の1件だけ「明日」） */
  time: string
  label: string
  /** 補足（場所・終了時刻）。無ければ null */
  note: string | null
  /** ティール＝就活／グレー＝学業／研究＝研究枠の空き／斜線＝就活にあてられる空き */
  variant: 'brand' | 'class' | 'research' | 'free'
}

/** ISO 文字列（2026-07-30T15:00:00）から HH:MM を取り出す。 */
export function formatHm(iso: string): string {
  return iso.slice(11, 16)
}

/** 分を表示用の長さにする。1時間以上は h、それ未満は分で出す。 */
export function formatDuration(minutes: number): string {
  if (minutes < 60) return `${minutes}分`
  const hours = minutes / 60
  // 2h / 1.5h のように、割り切れないときだけ小数第1位を出す
  return `${Number.isInteger(hours) ? hours : hours.toFixed(1)}h`
}

/** ヒーローの1文（§4.1 の生成規則）。件数の羅列ではなく行動を促す文にする。 */
export function heroSentence(openTaskCount: number, nearestTaskLabel: string | null): string {
  if (openTaskCount === 0 || nearestTaskLabel === null) {
    return '今日の就活タスクはありません。研究に集中できます。'
  }
  return `今日やることは ${openTaskCount}件。まず ${nearestTaskLabel} から。`
}

/** 空きスロットの文言。差し込むタスクが無ければ長さだけを出す（§5.3 エラー時）。 */
export function freeSlotLabel(slot: TodayFreeSlot): string {
  const length = `空き ${formatDuration(slot.minutes)}`
  return slot.suggested_task_label === null
    ? length
    : `${length} ― ${slot.suggested_task_label} をここに`
}

function eventNote(event: TodayEvent): string {
  const end = `〜${formatHm(event.end_at)}`
  return event.location ? `${event.location}・${end}` : end
}

/** 研究にあてられる区間の文言。 */
export function researchSlotLabel(slot: TodayResearchSlot): string {
  return `研究 ${formatDuration(slot.minutes)}`
}

/** 予定・研究枠の空き・就活の空きを時刻順に1本にし、末尾に翌日の先頭予定を足す（§4.1）。 */
export function buildTimeline(
  events: TodayEvent[],
  freeSlots: TodayFreeSlot[],
  tomorrowEvent: TodayEvent | null,
  researchSlots: TodayResearchSlot[] = [],
): TimelineRow[] {
  const rows: (TimelineRow & { sortKey: string })[] = [
    ...researchSlots.map((slot) => ({
      key: `research-${slot.start}`,
      sortKey: slot.start,
      time: formatHm(slot.start),
      label: researchSlotLabel(slot),
      note: null,
      variant: 'research' as const,
    })),
    ...events.map((event) => ({
      key: `event-${event.id}`,
      sortKey: event.start_at,
      time: formatHm(event.start_at),
      label: event.title,
      note: eventNote(event),
      // 学業はグレー、就活はティール（§4.0）
      variant: event.kind === '学業' ? ('class' as const) : ('brand' as const),
    })),
    ...freeSlots.map((slot) => ({
      key: `free-${slot.start}`,
      sortKey: slot.start,
      time: formatHm(slot.start),
      label: freeSlotLabel(slot),
      note: null,
      variant: 'free' as const,
    })),
  ]

  rows.sort((a, b) => a.sortKey.localeCompare(b.sortKey))

  const timeline: TimelineRow[] = rows.map(({ sortKey: _sortKey, ...row }) => row)

  if (tomorrowEvent) {
    timeline.push({
      key: `tomorrow-${tomorrowEvent.id}`,
      time: '明日',
      label: `${formatHm(tomorrowEvent.start_at)} ${tomorrowEvent.title}`,
      note: null,
      variant: tomorrowEvent.kind === '学業' ? 'class' : 'brand',
    })
  }
  return timeline
}

/** タスク行の補足（締切）。完了済みは締切ではなく完了として見せる。 */
export function taskNote(dueAt: string, isDone: boolean, day: string): string {
  const time = formatHm(dueAt)
  if (isDone) return `完了 ${time}`
  const isToday = dueAt.slice(0, 10) === day
  return isToday ? `締切 本日 ${time}` : `締切 ${dueAt.slice(5, 10).replace('-', '/')} ${time}`
}
