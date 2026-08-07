/** タスク・締め切りページの表示ロジック（純関数）。Vitest でテストするのはこのファイル。
 *
 *  `03-today-focus/FEATURE_PAGE_SPECS.md` §6。API（GET /api/tasks）は件数と素材だけを返し、
 *  「本日 23:59」「あと 11時間」のような文言はここで組み立てる。
 *
 *  期限タグの色（§6）：当日・超過 = danger ／ 3日以内 = warn ／ それ以外 = plain。
 *  色そのものは CSS 変数経由（.tag.d / .tag.w / .tag）なので、ここは意味だけを返す。
 */

import type { TaskScope } from '../api/tasks'
import { formatDuration, formatHm } from './today'

export type DueTone = 'danger' | 'warn' | 'plain'

export type DueTag = { tone: DueTone; label: string }

/** ISO 文字列（2026-07-30T12:20:00）を日付だけの通し番号にする。時刻の影響を受けずに日数差を出すため。 */
function dayNumber(iso: string): number {
  const [year, month, day] = iso.slice(0, 10).split('-').map(Number)
  return Date.UTC(year, month - 1, day) / 86_400_000
}

/** M/D 形式（2026-08-02 → 8/2）。 */
export function formatMd(iso: string): string {
  const [, month, day] = iso.slice(0, 10).split('-')
  return `${Number(month)}/${Number(day)}`
}

/** 期限タグ。完了済みは締切を急かす意味がないので出さない（打ち消し線で完了を表す）。 */
export function dueTag(dueAt: string, isDone: boolean, now: string): DueTag | null {
  if (isDone) return null

  const days = dayNumber(dueAt) - dayNumber(now)

  // 締切を過ぎている。当日でも時刻を過ぎていればこちらを先に見せる
  if (dueAt < now) return { tone: 'danger', label: '期限切れ' }
  if (days <= 0) return { tone: 'danger', label: `本日 ${formatHm(dueAt)}` }
  if (days === 1) return { tone: 'warn', label: '明日まで' }
  if (days <= 3) return { tone: 'warn', label: `${formatMd(dueAt)} まで` }
  return { tone: 'plain', label: `${formatMd(dueAt)} まで` }
}

/** タグの CSS クラス。色はリテラルで書かず既存語彙に寄せる（DESIGN_RULES R3）。 */
export function dueTagClass(tone: DueTone): string {
  if (tone === 'danger') return 'tag d'
  if (tone === 'warn') return 'tag w'
  return 'tag'
}

/** 締切カウントダウン（§6 右カラム①）。粒度を分→時間→日と粗くして、残りの体感に合わせる。 */
export function countdownLabel(dueAt: string, now: string): string {
  const minutes = Math.floor((new Date(dueAt).getTime() - new Date(now).getTime()) / 60_000)

  if (minutes < 0) return '超過'
  if (minutes < 60) return `あと ${minutes}分`
  if (minutes < 60 * 24) return `あと ${Math.floor(minutes / 60)}時間`
  return `あと ${Math.floor(minutes / (60 * 24))}日`
}

/** タスク行の補足。企業名を必ず出す（§6「企業名を必ず表示する」）。
 *
 *  見積りを添えるのは、それが空き時間の算出に効く値だと分かるようにするため（spec.md §5.3）。
 */
export function taskMeta(
  companyName: string | null,
  dueAt: string,
  estimateMin?: number,
): string {
  const parts = [`締切 ${formatMd(dueAt)} ${formatHm(dueAt)}`]
  if (estimateMin !== undefined) parts.push(`見積り ${formatDuration(estimateMin)}`)
  return [companyName, ...parts].filter(Boolean).join('・')
}

/** その締切のタスクが、いま選んでいる絞り込みに現れるか。
 *
 *  このアプリの「今日」は seed の基準日（docs/spec.md §5.3 の SEED_TODAY = 2026-07-30）で
 *  固定されている。実日付で締切を入れると「今日」「今週」から外れて、追加したのに
 *  一覧に出ない＝更新されていないように見える。それを事前に判定して案内するために使う。
 *
 *  範囲の定義はバックエンド（routers/tasks.py）と同じ：
 *  - today … 締切が基準日の終わりまで
 *  - week  … 基準日を含む暦の週（月曜〜日曜）
 */
export function isVisibleInScope(
  scope: TaskScope,
  dueAt: string,
  isDone: boolean,
  referenceDate: string,
): boolean {
  const due = dueAt.slice(0, 10)

  if (scope === 'all') return true
  if (scope === 'done') return isDone
  if (scope === 'today') return due <= referenceDate

  // week：基準日の週の月曜〜日曜。getUTCDay() は日曜=0 なので月曜起点にずらす
  const ref = new Date(`${referenceDate}T00:00:00Z`)
  const mondayOffset = (ref.getUTCDay() + 6) % 7
  const monday = new Date(ref.getTime() - mondayOffset * 86_400_000)
  const sunday = new Date(monday.getTime() + 6 * 86_400_000)
  return due >= monday.toISOString().slice(0, 10) && due <= sunday.toISOString().slice(0, 10)
}

/** ヒーローの1文。件数の羅列ではなく行動を促す文にする（PROMPT.md）。 */
export function heroSentence(
  todayCount: number,
  overdueCount: number,
  nearestLabel: string | null,
): string {
  if (overdueCount > 0) {
    return `期限切れが ${overdueCount}件あります。まず ${nearestLabel ?? '期限切れのタスク'} を片付けてください。`
  }
  if (todayCount === 0 || nearestLabel === null) {
    return '締切が迫ったタスクはありません。研究に集中できます。'
  }
  return `今日の締切は ${todayCount}件。まず ${nearestLabel} から。`
}
