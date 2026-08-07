/** 選考ステータス管理ボードの表示ロジック（純関数）。Vitest でテストするのはこのファイル。
 *
 *  `03-today-focus/FEATURE_PAGE_SPECS.md` §7。API は素材（次のタスク・次の予定）だけを返し、
 *  `ES 本日` `今日 15:00` のような状態タグと緊急度はここで組み立てる。
 *
 *  緊急度（§7）：当日 = danger ／ 3日以内 = warn ／ それ以外は色帯を出さない。
 */

import type { CompanyCard } from '../api/pipeline'
import { formatMd } from './tasks'
import { formatHm } from './today'

export type Urgency = 'danger' | 'warn' | 'none'

export type StatusTag = { label: string; urgency: Urgency }

/** ISO 文字列を日付だけの通し番号にする。時刻の影響を受けずに日数差を出すため。 */
function dayNumber(iso: string): number {
  const [year, month, day] = iso.slice(0, 10).split('-').map(Number)
  return Date.UTC(year, month - 1, day) / 86_400_000
}

function urgencyOf(iso: string, now: string): Urgency {
  const days = dayNumber(iso) - dayNumber(now)
  if (days <= 0) return 'danger'
  if (days <= 3) return 'warn'
  return 'none'
}

/** 色帯の CSS クラス。色はリテラルで書かず既存語彙に寄せる。 */
export function urgencyClass(urgency: Urgency): string {
  if (urgency === 'danger') return 'co-card urgent'
  if (urgency === 'warn') return 'co-card soon'
  return 'co-card'
}

/** カードの状態タグ。予定が先か締切が先かで、近いほうを見せる。
 *
 *  予定（面接）と締切（ES）の両方がある企業では、**日付が近いほう**を出す。
 *  同じ日なら予定を優先する（時刻が決まっている方が行動が決まるため）。
 *  どちらも無ければ null（タグを出さない）。
 */
export function statusTag(card: CompanyCard, now: string): StatusTag | null {
  const event = card.next_event_at
  const task = card.next_task_at

  if (event === null && task === null) return null

  const useEvent =
    event !== null && (task === null || dayNumber(event) <= dayNumber(task))

  if (useEvent && event !== null) {
    const sameDay = dayNumber(event) === dayNumber(now)
    return {
      label: sameDay ? `今日 ${formatHm(event)}` : `${formatMd(event)} ${formatHm(event)}`,
      urgency: urgencyOf(event, now),
    }
  }

  // 締切側。§7 の例に合わせて「{短縮名} 本日」の形にする
  const label =
    dayNumber(task!) === dayNumber(now)
      ? `${card.next_task_label ?? '締切'} 本日`
      : `${card.next_task_label ?? '締切'} ${formatMd(task!)}`
  return { label, urgency: urgencyOf(task!, now) }
}

/** ヒーローの1文。件数の羅列ではなく行動を促す文にする（PROMPT.md）。 */
export function heroSentence(inProgress: number, urgentName: string | null): string {
  if (urgentName !== null) {
    return `本日動きがあるのは ${urgentName}。まずここを確認してください。`
  }
  if (inProgress === 0) {
    return '選考中の企業はありません。気になる企業をエントリーに進めましょう。'
  }
  return `選考中は ${inProgress}社。本日締切や面接はありません。`
}

/** 当日の動きがある企業のうち先頭の名前。ヒーローの1文に使う。 */
export function mostUrgentName(cards: CompanyCard[], now: string): string | null {
  const urgent = cards.filter((c) => {
    const tag = statusTag(c, now)
    return tag !== null && tag.urgency === 'danger'
  })
  return urgent.length === 0 ? null : urgent[0].name
}
