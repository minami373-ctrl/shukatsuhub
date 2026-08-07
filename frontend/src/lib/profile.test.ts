/** 充実度とヒーローの1文の純ロジック（spec.md §7「充実度の算出」）。 */

import { describe, expect, it } from 'vitest'

import {
  EMPTY_PROFILE,
  PROFILE_FIELDS,
  completeness,
  filledFields,
  heroSentence,
  isSameProfile,
  unfilledLabels,
  type ProfileFields,
} from './profile'

function profile(overrides: Partial<ProfileFields> = {}): ProfileFields {
  return { ...EMPTY_PROFILE, ...overrides }
}

/** 先頭 n 項目だけ埋めたプロフィール。 */
function withFilledCount(n: number): ProfileFields {
  const filled = Object.fromEntries(
    PROFILE_FIELDS.slice(0, n).map(({ name }) => [name, '入力あり']),
  )
  return profile(filled)
}

describe('completeness', () => {
  it('9項目のうち6項目が空でないとき 67% になる', () => {
    expect(completeness(withFilledCount(6))).toBe(67)
  })

  it.each([
    [0, 0],
    [1, 11],
    [2, 22],
    [3, 33],
    [4, 44],
    [5, 56],
    [6, 67],
    [7, 78],
    [8, 89],
    [9, 100],
  ])('入力済み %i 項目なら %i%%', (count, expected) => {
    expect(completeness(withFilledCount(count))).toBe(expected)
  })

  it('空白のみの入力は未入力として数える', () => {
    expect(completeness(profile({ gakuchika: '   ', strengths: '　' }))).toBe(0)
  })
})

describe('filledFields / unfilledLabels', () => {
  it('空でない項目だけを spec の表示順で返す', () => {
    expect(filledFields(profile({ self_pr: 'あ', gakuchika: 'い' }))).toEqual([
      'gakuchika',
      'self_pr',
    ])
  })

  it('未入力項目を日本語ラベルで返す', () => {
    expect(unfilledLabels(withFilledCount(8))).toEqual(['就活軸'])
  })
})

describe('heroSentence', () => {
  it('未入力があるときは、その項目名を挙げて次の行動を示す', () => {
    expect(heroSentence(withFilledCount(8))).toBe(
      '未入力は「就活軸」だけ。埋めれば想定問答が作れます。',
    )
  })

  it('未入力が複数あるときは中黒で並べる', () => {
    expect(heroSentence(withFilledCount(7))).toBe(
      '未入力は「キャリアプラン・就活軸」だけ。埋めれば想定問答が作れます。',
    )
  })

  it('全項目埋まっていれば想定問答へ促す', () => {
    expect(heroSentence(withFilledCount(9))).toBe(
      'プロフィールは埋まっています。想定問答の準備に進めます。',
    )
  })

  it('件数の羅列ではなく行動を促す文になっている', () => {
    expect(heroSentence(withFilledCount(7))).toContain('埋めれば')
  })
})

describe('isSameProfile', () => {
  it('9項目すべて一致すれば true', () => {
    expect(isSameProfile(withFilledCount(3), withFilledCount(3))).toBe(true)
  })

  it('1項目でも違えば false', () => {
    expect(isSameProfile(profile({ job_axis: 'a' }), profile({ job_axis: 'b' }))).toBe(false)
  })
})
