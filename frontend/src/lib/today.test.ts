import { describe, expect, it } from 'vitest'

import type { TodayEvent, TodayFreeSlot, TodayResearchSlot } from '../api/today'
import {
  buildTimeline,
  formatDuration,
  formatHm,
  freeSlotLabel,
  heroSentence,
  researchSlotLabel,
  taskNote,
} from './today'

const DAY = '2026-07-30'

function event(id: number, start: string, end: string, title: string, kind: '選考' | '学業'): TodayEvent {
  return {
    id,
    title,
    kind,
    start_at: `${DAY}T${start}:00`,
    end_at: `${DAY}T${end}:00`,
    location: null,
  }
}

function slot(start: string, end: string, minutes: number, label: string | null): TodayFreeSlot {
  return {
    start: `${DAY}T${start}:00`,
    end: `${DAY}T${end}:00`,
    minutes,
    suggested_task_id: label ? 1 : null,
    suggested_task_label: label,
  }
}

describe('formatHm', () => {
  it('ISO 文字列から時刻だけを取り出す', () => {
    expect(formatHm('2026-07-30T15:00:00')).toBe('15:00')
  })
})

describe('formatDuration', () => {
  it.each([
    [30, '30分'],
    [45, '45分'],
    [60, '1h'],
    [90, '1.5h'],
    [120, '2h'],
    [150, '2.5h'],
  ])('%i 分は %s', (minutes, expected) => {
    expect(formatDuration(minutes)).toBe(expected)
  })
})

describe('heroSentence', () => {
  it('未完了があれば件数と最優先タスクを出す（spec §4.1）', () => {
    expect(heroSentence(5, 'ES提出')).toBe('今日やることは 5件。まず ES提出 から。')
  })

  it('未完了が0件なら研究に集中できると伝える', () => {
    expect(heroSentence(0, null)).toBe('今日の就活タスクはありません。研究に集中できます。')
  })

  it('件数があってもタスク名が無ければ0件と同じ文にする', () => {
    // API が nearest_task_label を返せない場合に「まず null から。」と出さないため
    expect(heroSentence(3, null)).toBe('今日の就活タスクはありません。研究に集中できます。')
  })
})

describe('freeSlotLabel', () => {
  it('差し込むタスクがあれば「空き 2h ― ES提出 をここに」（spec §4.1）', () => {
    expect(freeSlotLabel(slot('13:00', '15:00', 120, 'ES提出'))).toBe('空き 2h ― ES提出 をここに')
  })

  it('タスクが無ければ長さだけ出す（spec §5.3 エラー時）', () => {
    expect(freeSlotLabel(slot('20:00', '22:00', 120, null))).toBe('空き 2h')
  })
})

describe('researchSlotLabel', () => {
  it('研究にあてられる区間は長さだけ出す', () => {
    expect(researchSlotLabel({ start: '', end: '', minutes: 180 })).toBe('研究 3h')
  })
})

describe('buildTimeline', () => {
  const events = [
    event(1, '10:30', '12:00', '研究室ゼミ', '学業'),
    event(2, '15:00', '16:00', 'アルファテック 一次面接', '選考'),
  ]
  // 空きスロットは研究枠（10:00〜17:00）の外だけに出る
  const slots = [slot('08:00', '10:00', 120, '日程回答'), slot('17:00', '22:00', 300, 'ES提出')]
  const researchSlots: TodayResearchSlot[] = [
    { start: `${DAY}T12:00:00`, end: `${DAY}T15:00:00`, minutes: 180 },
    { start: `${DAY}T16:00:00`, end: `${DAY}T17:00:00`, minutes: 60 },
  ]

  it('予定・研究・空きを時刻順に1本に並べる', () => {
    const rows = buildTimeline(events, slots, null, researchSlots)
    expect(rows.map((r) => r.time)).toEqual(['08:00', '10:30', '12:00', '15:00', '16:00', '17:00'])
  })

  it('学業＝グレー・就活＝ティール・研究＝research・空き＝斜線で区別する（spec §4.0）', () => {
    const rows = buildTimeline(events, slots, null, researchSlots)
    expect(rows.map((r) => r.variant)).toEqual([
      'free',
      'class',
      'research',
      'brand',
      'research',
      'free',
    ])
  })

  it('研究の行は「研究 Nh」と出る', () => {
    const rows = buildTimeline(events, slots, null, researchSlots)
    expect(rows.filter((r) => r.variant === 'research').map((r) => r.label)).toEqual([
      '研究 3h',
      '研究 1h',
    ])
  })

  it('末尾に翌日の先頭予定を1件だけ足す（spec §4.1）', () => {
    const tomorrow: TodayEvent = {
      id: 9,
      title: 'ベータ社 説明会',
      kind: '選考',
      start_at: '2026-07-31T10:00:00',
      end_at: '2026-07-31T11:30:00',
      location: null,
    }
    const rows = buildTimeline(events, slots, tomorrow, researchSlots)

    expect(rows).toHaveLength(7)
    expect(rows[6]).toMatchObject({ time: '明日', label: '10:00 ベータ社 説明会' })
  })

  it('同じタスクが2つの空きスロットに出ない（spec §7 受け入れ条件）', () => {
    // 差し込みはバックエンドが決めるが、表示側で取り違えていないことも押さえる
    const rows = buildTimeline(events, slots, null, researchSlots)
    const suggested = rows.filter((r) => r.variant === 'free').map((r) => r.label)
    expect(new Set(suggested).size).toBe(suggested.length)
  })

  it('予定が無ければ研究枠と前後の空きだけになる', () => {
    const rows = buildTimeline(
      [],
      [slot('08:00', '10:00', 120, null), slot('17:00', '22:00', 300, null)],
      null,
      [{ start: `${DAY}T10:00:00`, end: `${DAY}T17:00:00`, minutes: 420 }],
    )

    expect(rows.map((r) => [r.time, r.label])).toEqual([
      ['08:00', '空き 2h'],
      ['10:00', '研究 7h'],
      ['17:00', '空き 5h'],
    ])
  })
})

describe('taskNote', () => {
  it('当日締切は「締切 本日 23:59」', () => {
    expect(taskNote(`${DAY}T23:59:00`, false, DAY)).toBe('締切 本日 23:59')
  })

  it('別日の締切は日付を出す', () => {
    expect(taskNote('2026-08-03T09:00:00', false, DAY)).toBe('締切 08/03 09:00')
  })

  it('完了済みは完了時刻として出す', () => {
    expect(taskNote(`${DAY}T09:12:00`, true, DAY)).toBe('完了 09:12')
  })
})
