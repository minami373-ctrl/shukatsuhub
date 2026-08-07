/** lib/research.ts の表示ロジック（企業研究ページ）。 */

import { describe, expect, it } from 'vitest'

import type { FetchOutcome, ResearchCompany } from '../api/research'
import {
  collectToast,
  collectedAtLabel,
  companyMeta,
  heroSentence,
  hostOf,
  sourceLabel,
  sourceLinkLabel,
  sourceTagClass,
} from './research'

const COMPANY: ResearchCompany = {
  id: 5,
  name: 'サイオステクノロジー株式会社',
  domain: 'sios.com',
  collected_at: null,
  source: null,
  unchecked: 0,
}

const ok = (url: string): FetchOutcome => ({ url, status: 'ok', message: null })
const denied = (url: string): FetchOutcome => ({
  url,
  status: 'robots_denied',
  message: 'robots.txt がこのページの取得を許可していません',
})

describe('sourceLabel / sourceTagClass', () => {
  it('由来ごとに言い換え、公開ページ由来だけをティールにする', () => {
    expect(sourceLabel('web')).toBe('AI収集')
    expect(sourceTagClass('web')).toBe('tag')

    expect(sourceLabel('ai')).toBe('AI（調べる観点）')
    expect(sourceTagClass('ai')).toBe('tag cls')

    expect(sourceLabel('template')).toBe('テンプレ')
    expect(sourceLabel('seed')).toBe('サンプル')
    expect(sourceTagClass('seed')).toBe('tag cls')
  })
})

describe('hostOf / sourceLinkLabel', () => {
  it('ホストとパスで出典を見分けられるようにする', () => {
    expect(hostOf('https://sios.com/recruit/')).toBe('sios.com')
    expect(sourceLinkLabel('https://sios.com/recruit/')).toBe('sios.com/recruit/')
    // トップページはホストだけ
    expect(sourceLinkLabel('https://sios.com/')).toBe('sios.com')
  })

  it('URL として読めない文字列はそのまま返す', () => {
    expect(hostOf('not a url')).toBe('not a url')
    expect(sourceLinkLabel('not a url')).toBe('not a url')
  })
})

describe('companyMeta / collectedAtLabel', () => {
  it('未収集ならドメインと未収集を出す', () => {
    expect(companyMeta(COMPANY)).toBe('sios.com・未収集')
  })

  it('収集済みならいつ集めたかを出す', () => {
    expect(companyMeta({ ...COMPANY, collected_at: '2026-08-05T10:42:00' })).toBe('8/5 10:42 収集')
    expect(collectedAtLabel('2026-08-05T10:42:00')).toBe('8/5 10:42 収集')
  })
})

describe('collectToast', () => {
  it('読めたページ数を出す', () => {
    expect(collectToast('web', [ok('https://sios.com/'), ok('https://sios.com/company/')])).toBe(
      '公開ページ 2件を読んでまとめました。',
    )
  })

  it('robots で読まなかったページがあれば添える', () => {
    expect(collectToast('web', [ok('https://sios.com/'), denied('https://sios.com/news/')])).toBe(
      '公開ページ 1件を読んでまとめました（robots で 1件は読まず）。',
    )
  })

  it('robots で全部読めなかったときはその理由を出す', () => {
    expect(collectToast('ai', [denied('https://sios.com/')])).toContain('robots.txt が許可していない')
  })

  it('ページを読めなかったときは観点だけと明示する', () => {
    expect(collectToast('ai', [])).toBe(
      '公開ページを読めなかったので、調べる観点だけをまとめました。',
    )
  })

  it('AI が使えないときはテンプレだと明示する', () => {
    expect(collectToast('template', [])).toContain('AZURE_OPENAI_API_KEY 未設定')
  })
})

describe('heroSentence', () => {
  it('未収集なら収集を促す', () => {
    expect(heroSentence('サイオステクノロジー株式会社', false, 0)).toBe(
      'サイオステクノロジー株式会社 はまだ調べていません。「AI で情報を集める」を押してください。',
    )
  })

  it('未確認の観点があれば残り点数を出す', () => {
    expect(heroSentence('アルファテック', true, 2)).toBe(
      'アルファテック の研究メモができています。未確認の観点が 2点あります。',
    )
  })

  it('観点まで済んでいれば次へ進めると言う', () => {
    expect(heroSentence('アルファテック', true, 0)).toBe(
      'アルファテック は確認観点まで済んでいます。次の企業に進めます。',
    )
  })

  it('企業が無ければ企業の追加を促す', () => {
    expect(heroSentence(null, false, 0)).toBe('企業が登録されていません。まず企業を追加してください。')
  })
})
