/** 選考ステータス管理ボードの表示ロジック（`03-today-focus/FEATURE_PAGE_SPECS.md` §7）。
 *
 *  基準時刻は seed の 2026-07-30T12:20:00（spec.md §5.3 の SEED_NOW_TIME）。
 */

import { describe, expect, it } from 'vitest'

import type { CompanyCard } from '../api/pipeline'
import { heroSentence, mostUrgentName, statusTag, urgencyClass } from './pipeline'

const NOW = '2026-07-30T12:20:00'

function card(over: Partial<CompanyCard>): CompanyCard {
  return {
    id: 1,
    name: 'アルファテック',
    domain: 'alphatech.co.jp',
    stage: '面接',
    is_watched: true,
    job_type: 'ソフトウェアエンジニア',
    location: '東京',
    remote_ok: true,
    tags: '成長環境',
    salary_min: 450,
    holidays_per_year: 125,
    next_task_at: null,
    next_task_label: null,
    next_event_at: null,
    next_event_title: null,
    ...over,
  }
}

describe('statusTag', () => {
  it('当日の予定は「今日 HH:MM」で danger', () => {
    expect(statusTag(card({ next_event_at: '2026-07-30T15:00:00' }), NOW)).toEqual({
      label: '今日 15:00',
      urgency: 'danger',
    })
  })

  it('当日の締切は「{短縮名} 本日」で danger', () => {
    const c = card({ next_task_at: '2026-07-30T23:59:00', next_task_label: 'ES提出' })
    expect(statusTag(c, NOW)).toEqual({ label: 'ES提出 本日', urgency: 'danger' })
  })

  it('3日以内は warn、4日以上先は色帯を出さない', () => {
    expect(statusTag(card({ next_event_at: '2026-08-02T10:00:00' }), NOW)?.urgency).toBe('warn')
    expect(statusTag(card({ next_event_at: '2026-08-03T10:00:00' }), NOW)?.urgency).toBe('none')
  })

  it('予定と締切の両方があれば日付が近いほうを出す', () => {
    const c = card({
      next_event_at: '2026-08-03T10:00:00',
      next_task_at: '2026-07-30T23:59:00',
      next_task_label: 'ES提出',
    })
    expect(statusTag(c, NOW)?.label).toBe('ES提出 本日')
  })

  it('同じ日なら予定を優先する（時刻が決まっている方が行動が決まる）', () => {
    const c = card({
      next_event_at: '2026-07-30T15:00:00',
      next_task_at: '2026-07-30T23:59:00',
      next_task_label: 'ES提出',
    })
    expect(statusTag(c, NOW)?.label).toBe('今日 15:00')
  })

  it('どちらも無ければタグを出さない（推測でひも付けない）', () => {
    expect(statusTag(card({}), NOW)).toBeNull()
  })

  it('色帯は既存のクラス語彙に対応する', () => {
    expect(urgencyClass('danger')).toBe('co-card urgent')
    expect(urgencyClass('warn')).toBe('co-card soon')
    expect(urgencyClass('none')).toBe('co-card')
  })
})

describe('mostUrgentName', () => {
  it('当日の動きがある企業の名前を返す', () => {
    const cards = [
      card({ id: 1, name: 'シータ電機' }),
      card({ id: 2, name: 'アルファテック', next_event_at: '2026-07-30T15:00:00' }),
    ]
    expect(mostUrgentName(cards, NOW)).toBe('アルファテック')
  })

  it('当日の動きが無ければ null', () => {
    expect(mostUrgentName([card({ next_event_at: '2026-08-10T10:00:00' })], NOW)).toBeNull()
  })
})

describe('heroSentence', () => {
  it('当日動きがある企業があればそれを促す', () => {
    expect(heroSentence(3, 'アルファテック')).toBe(
      '本日動きがあるのは アルファテック。まずここを確認してください。',
    )
  })

  it('動きが無ければ選考中の件数を出す', () => {
    expect(heroSentence(3, null)).toBe('選考中は 3社。本日締切や面接はありません。')
  })

  it('選考中が0社なら次の行動を促す（件数0を出さない）', () => {
    expect(heroSentence(0, null)).toBe(
      '選考中の企業はありません。気になる企業をエントリーに進めましょう。',
    )
  })
})
