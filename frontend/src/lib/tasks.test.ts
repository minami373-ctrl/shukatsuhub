/** タスク・締め切りページの表示ロジック（`03-today-focus/FEATURE_PAGE_SPECS.md` §6）。
 *
 *  基準時刻は seed の 2026-07-30T12:20:00（spec.md §5.3 の SEED_NOW_TIME）。
 */

import { describe, expect, it } from 'vitest'

import {
  countdownLabel,
  dueTag,
  dueTagClass,
  formatMd,
  heroSentence,
  isVisibleInScope,
  taskMeta,
} from './tasks'

const NOW = '2026-07-30T12:20:00'

describe('dueTag', () => {
  it('締切を過ぎた未完了は期限切れ（danger）', () => {
    expect(dueTag('2026-07-30T12:00:00', false, NOW)).toEqual({ tone: 'danger', label: '期限切れ' })
    expect(dueTag('2026-07-24T18:00:00', false, NOW)).toEqual({ tone: 'danger', label: '期限切れ' })
  })

  it('当日でまだ時刻前なら「本日 HH:MM」（danger）', () => {
    expect(dueTag('2026-07-30T23:59:00', false, NOW)).toEqual({
      tone: 'danger',
      label: '本日 23:59',
    })
  })

  it('翌日は「明日まで」（warn）', () => {
    expect(dueTag('2026-07-31T10:00:00', false, NOW)).toEqual({ tone: 'warn', label: '明日まで' })
  })

  it('3日以内は warn、4日以上先は plain', () => {
    // 3日後 = 08/02 が境界。ここまでが warn
    expect(dueTag('2026-08-02T10:00:00', false, NOW)).toEqual({ tone: 'warn', label: '8/2 まで' })
    expect(dueTag('2026-08-03T10:00:00', false, NOW)).toEqual({ tone: 'plain', label: '8/3 まで' })
  })

  it('完了済みには期限タグを出さない（打ち消し線で完了を表す）', () => {
    expect(dueTag('2026-07-30T09:12:00', true, NOW)).toBeNull()
  })

  it('色は既存のタグ語彙に対応する', () => {
    expect(dueTagClass('danger')).toBe('tag d')
    expect(dueTagClass('warn')).toBe('tag w')
    expect(dueTagClass('plain')).toBe('tag')
  })
})

describe('countdownLabel', () => {
  it('1時間未満は分、1日未満は時間、それ以上は日で出す', () => {
    expect(countdownLabel('2026-07-30T12:50:00', NOW)).toBe('あと 30分')
    expect(countdownLabel('2026-07-30T23:59:00', NOW)).toBe('あと 11時間')
    expect(countdownLabel('2026-08-02T10:00:00', NOW)).toBe('あと 2日')
  })

  it('過ぎているものは超過', () => {
    expect(countdownLabel('2026-07-30T12:00:00', NOW)).toBe('超過')
  })
})

describe('taskMeta', () => {
  it('企業名があれば必ず前に出す', () => {
    expect(taskMeta('アルファテック', '2026-07-30T23:59:00')).toBe(
      'アルファテック・締切 7/30 23:59',
    )
  })

  it('企業に紐づかないタスクは締切だけ（推測でひも付けない）', () => {
    expect(taskMeta(null, '2026-07-30T09:12:00')).toBe('締切 7/30 09:12')
  })

  it('見積りを渡すと添える（空き時間の算出に効く値だと分かるように）', () => {
    expect(taskMeta('アルファテック', '2026-07-30T23:59:00', 240)).toBe(
      'アルファテック・締切 7/30 23:59・見積り 4h',
    )
    expect(taskMeta(null, '2026-07-30T09:12:00', 15)).toBe('締切 7/30 09:12・見積り 15分')
  })
})

describe('heroSentence', () => {
  it('期限切れがあればそれを先に促す', () => {
    expect(heroSentence(3, 2, 'レポート')).toBe(
      '期限切れが 2件あります。まず レポート を片付けてください。',
    )
  })

  it('期限切れが無ければ今日の締切件数を出す', () => {
    expect(heroSentence(3, 0, 'ES提出')).toBe('今日の締切は 3件。まず ES提出 から。')
  })

  it('0件なら研究に向かわせる（空状態を件数0で見せない）', () => {
    expect(heroSentence(0, 0, null)).toBe('締切が迫ったタスクはありません。研究に集中できます。')
  })
})

describe('formatMd', () => {
  it('ゼロ埋めしない', () => {
    expect(formatMd('2026-08-02T10:00:00')).toBe('8/2')
  })
})

describe('isVisibleInScope', () => {
  // 基準日は seed の 2026-07-30（木）。この週は 07/27（月）〜08/02（日）
  const REF = '2026-07-30'

  it('today は基準日以前の締切だけ', () => {
    expect(isVisibleInScope('today', '2026-07-30T23:59:00', false, REF)).toBe(true)
    expect(isVisibleInScope('today', '2026-07-24T18:00:00', false, REF)).toBe(true)
    // 実日付で入れた締切は「今日」に出ない。これが「追加したのに出ない」の原因
    expect(isVisibleInScope('today', '2026-08-04T14:47:00', false, REF)).toBe(false)
  })

  it('week は基準日を含む暦の週（月曜〜日曜）', () => {
    expect(isVisibleInScope('week', '2026-07-27T00:00:00', false, REF)).toBe(true)
    expect(isVisibleInScope('week', '2026-08-02T23:59:00', false, REF)).toBe(true)
    expect(isVisibleInScope('week', '2026-07-26T23:59:00', false, REF)).toBe(false)
    expect(isVisibleInScope('week', '2026-08-03T00:00:00', false, REF)).toBe(false)
  })

  it('all は必ず出る。done は完了済みだけ', () => {
    expect(isVisibleInScope('all', '2026-12-31T00:00:00', false, REF)).toBe(true)
    expect(isVisibleInScope('done', '2026-07-30T09:12:00', false, REF)).toBe(false)
    expect(isVisibleInScope('done', '2026-07-30T09:12:00', true, REF)).toBe(true)
  })
})
