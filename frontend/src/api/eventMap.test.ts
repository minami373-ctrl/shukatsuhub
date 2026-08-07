import { describe, expect, it } from 'vitest'

import {
  type ApiEvent,
  KIND_LABEL,
  busyMinutes,
  conflicts,
  countKind,
  formatEventRange,
  formatJaDate,
  heroSentence,
  researchHours,
  toCalendarEvents,
  toLocalIso,
} from './eventMap'

function ev(partial: Partial<ApiEvent> & Pick<ApiEvent, 'title' | 'kind' | 'start_at' | 'end_at'>): ApiEvent {
  return {
    id: 1,
    external_id: 'x',
    location: null,
    company_id: null,
    ...partial,
  }
}

const SEMINAR = ev({
  id: 1,
  title: '研究室ゼミ',
  kind: '学業',
  start_at: '2026-07-30T10:30:00',
  end_at: '2026-07-30T12:00:00',
  location: 'B棟 402',
})
const INTERVIEW = ev({
  id: 2,
  title: 'アルファテック 一次面接',
  kind: '選考',
  start_at: '2026-07-30T15:00:00',
  end_at: '2026-07-30T16:00:00',
})
const REPORT = ev({
  id: 3,
  title: '課題レポート作成',
  kind: '学業',
  start_at: '2026-07-30T18:00:00',
  end_at: '2026-07-30T20:00:00',
})
const TOMORROW = ev({
  id: 4,
  title: 'ベータ社 説明会',
  kind: '選考',
  start_at: '2026-07-31T10:00:00',
  end_at: '2026-07-31T11:30:00',
})

const ALL = [SEMINAR, INTERVIEW, REPORT, TOMORROW]

describe('toCalendarEvents', () => {
  it('選考と学業でクラスを分ける（色の区別）', () => {
    const [seminar, interview] = toCalendarEvents([SEMINAR, INTERVIEW])

    expect(seminar.classNames).toEqual(['ev-gakugyo'])
    expect(interview.classNames).toEqual(['ev-senko'])
  })

  it('場所と種別を extendedProps に持たせる', () => {
    const [seminar] = toCalendarEvents([SEMINAR])

    expect(seminar.extendedProps).toEqual({ kind: '学業', location: 'B棟 402' })
    expect(seminar.start).toBe('2026-07-30T10:30:00')
  })
})

describe('busyMinutes', () => {
  it('その日のイベントだけを合計する', () => {
    // ゼミ 90分 + 面接 60分 + レポート 120分 = 270分
    expect(busyMinutes(ALL, '2026-07-30')).toBe(270)
    expect(busyMinutes(ALL, '2026-07-31')).toBe(90)
  })

  it('重なりを二重に数えない', () => {
    const overlapping = [
      ev({ title: 'A', kind: '学業', start_at: '2026-07-30T10:00:00', end_at: '2026-07-30T12:00:00' }),
      ev({ title: 'B', kind: '選考', start_at: '2026-07-30T11:00:00', end_at: '2026-07-30T13:00:00' }),
    ]

    expect(busyMinutes(overlapping, '2026-07-30')).toBe(180)
  })

  it('08:00〜22:00 の外は数えない', () => {
    const earlyAndLate = [
      ev({ title: '早朝', kind: '学業', start_at: '2026-07-30T06:00:00', end_at: '2026-07-30T09:00:00' }),
      ev({ title: '深夜', kind: '学業', start_at: '2026-07-30T21:00:00', end_at: '2026-07-30T23:30:00' }),
    ]

    // 08:00-09:00 の 60分 + 21:00-22:00 の 60分
    expect(busyMinutes(earlyAndLate, '2026-07-30')).toBe(120)
  })

  it('イベントが無い日は 0', () => {
    expect(busyMinutes(ALL, '2026-08-01')).toBe(0)
  })
})

describe('researchHours', () => {
  it('10:00〜17:00 のうち予定が入っていない時間を返す', () => {
    // 09:00-11:00 のうち枠内は 1h、13:00-15:00 は 2h → 7 - 3 = 4h
    const events = [
      ev({ title: '面接', kind: '選考', start_at: '2026-07-30T09:00:00', end_at: '2026-07-30T11:00:00' }),
      ev({ title: 'ゼミ', kind: '学業', start_at: '2026-07-30T13:00:00', end_at: '2026-07-30T15:00:00' }),
    ]

    expect(researchHours(events, '2026-07-30')).toBe(4)
  })

  it('研究枠の外の予定は引かない', () => {
    const evening = [
      ev({ title: 'レポート', kind: '学業', start_at: '2026-07-30T18:00:00', end_at: '2026-07-30T20:00:00' }),
    ]

    expect(researchHours(evening, '2026-07-30')).toBe(7)
  })

  it('0.5h 刻みに丸める', () => {
    const fortyMinutes = [
      ev({ title: '面談', kind: '選考', start_at: '2026-07-30T10:00:00', end_at: '2026-07-30T10:40:00' }),
    ]

    // 7h - 40分 = 6.333h → 6.5h
    expect(researchHours(fortyMinutes, '2026-07-30')).toBe(6.5)
  })

  it('研究枠が予定で埋まれば 0', () => {
    const allDay = [
      ev({ title: '終日研修', kind: '選考', start_at: '2026-07-30T10:00:00', end_at: '2026-07-30T17:00:00' }),
    ]

    expect(researchHours(allDay, '2026-07-30')).toBe(0)
  })
})

describe('conflicts', () => {
  it('就活と学業が重なっている組を返す', () => {
    const clash = [
      SEMINAR,
      ev({ title: '一次面接', kind: '選考', start_at: '2026-07-30T11:00:00', end_at: '2026-07-30T12:30:00' }),
    ]

    expect(conflicts(clash, '2026-07-30')).toHaveLength(1)
  })

  it('同じ種別どうしは衝突として扱わない', () => {
    const sameKind = [
      SEMINAR,
      ev({ title: '講義', kind: '学業', start_at: '2026-07-30T11:00:00', end_at: '2026-07-30T12:30:00' }),
    ]

    expect(conflicts(sameKind, '2026-07-30')).toEqual([])
  })

  it('接しているだけ（終了＝開始）は衝突ではない', () => {
    const touching = [
      SEMINAR,
      ev({ title: '面接', kind: '選考', start_at: '2026-07-30T12:00:00', end_at: '2026-07-30T13:00:00' }),
    ]

    expect(conflicts(touching, '2026-07-30')).toEqual([])
  })
})

describe('heroSentence', () => {
  it('衝突が無ければそう伝える', () => {
    expect(heroSentence(ALL, '2026-07-30')).toBe('2026年7月30日（木） は衝突はありません。')
  })

  it('衝突があれば予定名を出す', () => {
    const clash = [
      SEMINAR,
      ev({ title: '一次面接', kind: '選考', start_at: '2026-07-30T11:00:00', end_at: '2026-07-30T12:30:00' }),
    ]

    expect(heroSentence(clash, '2026-07-30')).toBe(
      '2026年7月30日（木） は研究室ゼミと一次面接が重なっています。',
    )
  })
})

describe('formatJaDate / countKind', () => {
  it('曜日つきで整形する', () => {
    expect(formatJaDate('2026-07-30')).toBe('2026年7月30日（木）')
  })

  it('種別ごとに数える', () => {
    expect(countKind(ALL, '選考')).toBe(2)
    expect(countKind(ALL, '学業')).toBe(2)
  })

  it('ローカル時刻のまま ISO 文字列にする（末尾に Z を付けない）', () => {
    expect(toLocalIso(new Date(2026, 6, 30, 9, 5, 0))).toBe('2026-07-30T09:05:00')
  })
})

describe('KIND_LABEL / formatEventRange', () => {
  it('表示ラベルは 選考→就活・学業→学業（データ値は変えない）', () => {
    expect(KIND_LABEL['選考']).toBe('就活')
    expect(KIND_LABEL['学業']).toBe('学業')
  })

  it('同じ日なら終了側に日付を付けない', () => {
    expect(formatEventRange(INTERVIEW.start_at, INTERVIEW.end_at)).toBe('7/30（木）15:00〜16:00')
  })

  it('0分でない時刻もそのまま出す', () => {
    expect(formatEventRange(SEMINAR.start_at, SEMINAR.end_at)).toBe('7/30（木）10:30〜12:00')
  })

  it('日をまたぐ予定は終了側にも日付を付ける', () => {
    expect(formatEventRange('2026-07-30T23:00:00', '2026-07-31T01:00:00')).toBe(
      '7/30（木）23:00〜7/31（金）01:00',
    )
  })
})
