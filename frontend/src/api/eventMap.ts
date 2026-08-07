/** イベントの表示ロジック（純関数）。Vitest でテストするのはこのファイル。
 *
 *  docs/spec.md §4.2（カレンダー）と §5.3（研究にあてられる時間）に対応。
 */

export type EventKind = '選考' | '学業'

/** GET /api/events のレスポンス1件（backend/models.py の Event と対応）。 */
export type ApiEvent = {
  id: number
  external_id: string
  title: string
  kind: EventKind
  start_at: string
  end_at: string
  location: string | null
  company_id: number | null
}

/** FullCalendar に渡す形（依存を持ち込まないため自前で定義する）。 */
export type CalendarEvent = {
  id: string
  title: string
  start: string
  end: string
  classNames: string[]
  extendedProps: { kind: EventKind; location: string | null }
}

/** カレンダーに表示する時間帯。08:00〜22:00。 */
export const DAY_START_HOUR = 8
export const DAY_END_HOUR = 22

/** 研究にあてられる時間を数える範囲。研究は大学院に居る 10:00〜17:00 でしかできない。
 *  backend/services/freetime.py の RESEARCH_START_HOUR / RESEARCH_END_HOUR と同じ値にする。 */
export const RESEARCH_START_HOUR = 10
export const RESEARCH_END_HOUR = 17
const RESEARCH_MINUTES = (RESEARCH_END_HOUR - RESEARCH_START_HOUR) * 60

const WEEKDAYS = ['日', '月', '火', '水', '木', '金', '土']

/** 画面に出す種別のラベル（docs/spec.md §4.2）。
 *  DB・API の値は `選考` のままにし、表示だけ `就活` と言い換える。
 *  画面側で分岐を書かないため、変換はここに集約する。 */
export const KIND_LABEL: Record<EventKind, string> = {
  選考: '就活',
  学業: '学業',
}

export function toCalendarEvents(events: ApiEvent[]): CalendarEvent[] {
  return events.map((e) => ({
    id: String(e.id),
    title: e.title,
    start: e.start_at,
    end: e.end_at,
    // 就活＝ティール／学業＝グレー（components.css の .ev-senko / .ev-gakugyo）
    classNames: [e.kind === '選考' ? 'ev-senko' : 'ev-gakugyo'],
    extendedProps: { kind: e.kind, location: e.location },
  }))
}

/** date（YYYY-MM-DD）に始まるイベントだけを取り出す。 */
export function eventsOn(events: ApiEvent[], date: string): ApiEvent[] {
  return events.filter((e) => e.start_at.slice(0, 10) === date)
}

function minutesFromMidnight(iso: string): number {
  const [, time = '00:00:00'] = iso.split('T')
  const [h, m] = time.split(':').map(Number)
  return h * 60 + m
}

/** 指定した時間帯に収まる占有時間（分）。重なりは二重に数えない（§5.3）。
 *  既定はカレンダーの表示範囲（08:00〜22:00）。 */
export function busyMinutes(
  events: ApiEvent[],
  date: string,
  startHour = DAY_START_HOUR,
  endHour = DAY_END_HOUR,
): number {
  const windowStart = startHour * 60
  const windowEnd = endHour * 60

  const spans = eventsOn(events, date)
    .map((e) => ({
      start: Math.max(minutesFromMidnight(e.start_at), windowStart),
      end: Math.min(minutesFromMidnight(e.end_at), windowEnd),
    }))
    .filter((s) => s.end > s.start)
    .sort((a, b) => a.start - b.start)

  let total = 0
  let cursor = -1
  for (const span of spans) {
    const start = Math.max(span.start, cursor)
    if (span.end > start) {
      total += span.end - start
      cursor = span.end
    }
  }
  return total
}

/** 研究にあてられる時間（h）。10:00〜17:00 のうち予定が入っていない時間。
 *
 *  タスクの見積りは引かない（2026-08-03 の決定）。今日画面の GET /api/today と
 *  同じ定義にしてあるので、カレンダーと今日画面で数字が食い違わない。
 *  丸めは半数切り上げ（Math.round と違い、backend の実装と揃えてある）。
 */
export function researchHours(events: ApiEvent[], date: string): number {
  const remaining =
    RESEARCH_MINUTES - busyMinutes(events, date, RESEARCH_START_HOUR, RESEARCH_END_HOUR)
  if (remaining <= 0) return 0
  return Math.floor(remaining / 30 + 0.5) / 2
}

/** 就活と学業が時間的に重なっている組（§4.2 の衝突）。 */
export function conflicts(events: ApiEvent[], date: string): [ApiEvent, ApiEvent][] {
  const target = eventsOn(events, date)
  const found: [ApiEvent, ApiEvent][] = []

  for (let i = 0; i < target.length; i += 1) {
    for (let j = i + 1; j < target.length; j += 1) {
      const a = target[i]
      const b = target[j]
      if (a.kind === b.kind) continue
      const overlap =
        minutesFromMidnight(a.start_at) < minutesFromMidnight(b.end_at) &&
        minutesFromMidnight(b.start_at) < minutesFromMidnight(a.end_at)
      if (overlap) found.push([a, b])
    }
  }
  return found
}

export function formatJaDate(date: string): string {
  const [y, m, d] = date.split('-').map(Number)
  const weekday = WEEKDAYS[new Date(y, m - 1, d).getDay()]
  return `${y}年${m}月${d}日（${weekday}）`
}

/** 詳細モーダルに出す日時（§4.2）。例 `7/30（木）15:00〜16:00`。
 *
 *  minutesFromMidnight と同じ方針で、Date に通さず文字列を切り出して組む
 *  （API は naive な日時を返すので、new Date に渡すとタイムゾーンでずれる）。
 *  日をまたぐ予定は終了側にも日付を付ける。
 */
export function formatEventRange(startAt: string, endAt: string): string {
  const startDate = startAt.slice(0, 10)
  const endDate = endAt.slice(0, 10)
  const head = `${formatJaShortDate(startDate)}${startAt.slice(11, 16)}`
  const tail =
    startDate === endDate
      ? endAt.slice(11, 16)
      : `${formatJaShortDate(endDate)}${endAt.slice(11, 16)}`
  return `${head}〜${tail}`
}

/** `2026-07-30` → `7/30（木）`。 */
function formatJaShortDate(date: string): string {
  const [y, m, d] = date.split('-').map(Number)
  const weekday = WEEKDAYS[new Date(y, m - 1, d).getDay()]
  return `${m}/${d}（${weekday}）`
}

/** ヒーローの1文（§4.2）。件数の羅列ではなく状況を伝える文にする。 */
export function heroSentence(events: ApiEvent[], date: string): string {
  const found = conflicts(events, date)
  if (found.length === 0) {
    return `${formatJaDate(date)} は衝突はありません。`
  }
  return `${formatJaDate(date)} は${found[0][0].title}と${found[0][1].title}が重なっています。`
}

export function countKind(events: ApiEvent[], kind: EventKind): number {
  return events.filter((e) => e.kind === kind).length
}

/** Date をタイムゾーン無しの ISO 文字列にする（例 2026-07-30T00:00:00）。
 *
 *  API に UTC（末尾 Z）を送ると SQLite の naive な日時と比較できないため、
 *  ローカル時刻のまま渡す。
 */
export function toLocalIso(date: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  return (
    `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}` +
    `T${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
  )
}
