/** 企業の発見・マッチングの表示ロジック（`03-today-focus/FEATURE_PAGE_SPECS.md` §12）。 */

import { describe, expect, it } from 'vitest'

import type { CompanySuggestion, MatchedCompany } from '../api/matching'
import {
  canWatch,
  companyMeta,
  heroSentence,
  rateClass,
  rateTone,
  suggestionHeading,
  suggestionMeta,
  watchedLabel,
} from './matching'

function company(over: Partial<MatchedCompany> = {}): MatchedCompany {
  return {
    id: 1,
    name: 'アルファテック',
    domain: 'alphatech.co.jp',
    stage: '気になる',
    is_watched: false,
    job_type: 'ソフトウェアエンジニア',
    location: '東京',
    remote_ok: true,
    salary_min: null,
    holidays_per_year: null,
    rate: 100,
    reasons: [],
    ...over,
  }
}

function suggestion(over: Partial<CompanySuggestion> = {}): CompanySuggestion {
  return {
    domain: 'sigma-denshi.jp',
    suggested_name: 'シグマ電子 採用担当',
    email_count: 2,
    latest_received_at: '2026-07-30T08:40:00',
    categories: ['重要', '確認'],
    ...over,
  }
}

describe('rateTone', () => {
  it('90%以上は ok、70〜89% は brand、それ未満は色を付けない', () => {
    expect(rateTone(100)).toBe('ok')
    expect(rateTone(90)).toBe('ok')
    expect(rateTone(89)).toBe('brand')
    expect(rateTone(70)).toBe('brand')
    expect(rateTone(69)).toBe('plain')
    expect(rateTone(0)).toBe('plain')
  })

  it('色は既存のタグ語彙に対応する', () => {
    expect(rateClass('ok')).toBe('tag ok')
    expect(rateClass('brand')).toBe('tag')
    expect(rateClass('plain')).toBe('tag g')
  })
})

describe('companyMeta', () => {
  it('職種・勤務地・リモートを1行にまとめる', () => {
    expect(companyMeta(company())).toBe('ソフトウェアエンジニア・東京・リモート可')
  })

  it('リモート不可なら書かない', () => {
    expect(companyMeta(company({ remote_ok: false }))).toBe('ソフトウェアエンジニア・東京')
  })

  it('空の項目は出さない（推測で埋めない）', () => {
    expect(companyMeta(company({ job_type: null, location: '  ', remote_ok: false }))).toBe(
      '条件は未登録',
    )
  })

  it('年収・休日は登録されていれば並記する（マッチ率の根拠を照合できるように）', () => {
    expect(companyMeta(company({ salary_min: 450, holidays_per_year: 125 }))).toBe(
      'ソフトウェアエンジニア・東京・リモート可・年収450万〜・休日125日',
    )
  })

  it('年収・休日が未登録なら出さない', () => {
    expect(companyMeta(company({ salary_min: null, holidays_per_year: 125 }))).toBe(
      'ソフトウェアエンジニア・東京・リモート可・休日125日',
    )
  })
})

describe('suggestionMeta / suggestionHeading', () => {
  it('候補の根拠（ドメイン・件数・分類）を1行で出す', () => {
    expect(suggestionMeta(suggestion())).toBe('sigma-denshi.jp／メール2件（重要・確認）')
  })

  it('分類が無ければ括弧を出さない', () => {
    expect(suggestionMeta(suggestion({ categories: [] }))).toBe('sigma-denshi.jp／メール2件')
  })

  it('見出しに件数を出す', () => {
    expect(suggestionHeading(2)).toBe('📥 受信箱から見つけた未登録の企業 2件')
  })
})

describe('heroSentence', () => {
  it('検索前は入力を促す', () => {
    expect(heroSentence(false, 0, null)).toBe('条件を入力すると、合いそうな企業が出ます。')
  })

  it('おすすめがあれば先頭の企業名を出す', () => {
    expect(heroSentence(true, 4, 'アルファテック')).toBe(
      'おすすめは 4社。まず アルファテック を見てください。',
    )
  })

  it('0件なら件数ではなく次の行動を促す', () => {
    expect(heroSentence(true, 0, null)).toBe(
      '条件に強く合う企業はありませんでした。条件をゆるめてみてください。',
    )
  })
})

describe('canWatch / watchedLabel', () => {
  it('未登録かつ「気になる」段階のときだけ追加できる', () => {
    expect(canWatch(company())).toBe(true)
    expect(canWatch(company({ is_watched: true }))).toBe(false)
    expect(canWatch(company({ stage: '面接' }))).toBe(false)
  })

  it('追加済み・選考中はその旨を出す', () => {
    expect(watchedLabel(company({ is_watched: true }))).toBe('登録済み')
    expect(watchedLabel(company({ stage: '面接' }))).toBe('選考中（面接）')
    expect(watchedLabel(company())).toBe('')
  })
})
