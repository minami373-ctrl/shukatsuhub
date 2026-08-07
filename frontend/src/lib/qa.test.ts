/** 想定問答の純ロジック（spec.md §4.5 / §5.6 の導出値と文言）。 */

import { describe, expect, it } from 'vitest'

import {
  canSaveAnswer,
  heroSentence,
  preparedRate,
  sourceLabel,
  unpreparedCount,
  type QAItem,
} from './qa'

function items(prepared: boolean[]): QAItem[] {
  return prepared.map((is_prepared, i) => ({
    id: i + 1,
    company_id: 1,
    question: `質問${i}`,
    answer_draft: `回答${i}`,
    category: '志望動機',
    is_prepared,
    source: 'ai',
    generated_at: '2026-07-30T12:20:00',
  }))
}

describe('回答の保存可否', () => {
  it('空欄と空白のみは保存できない（未入力を準備済みと数えないため）', () => {
    expect(canSaveAnswer('')).toBe(false)
    expect(canSaveAnswer('   ')).toBe(false)
    expect(canSaveAnswer('\n\t ')).toBe(false)
  })

  it('1文字でも本文があれば保存できる', () => {
    expect(canSaveAnswer('研究室での役割を軸に話す')).toBe(true)
    expect(canSaveAnswer('  前後に空白があっても中身があればよい  ')).toBe(true)
  })
})

describe('準備率', () => {
  it('6件のうち2件が準備済みなら 33%（未準備は 4件）', () => {
    const list = items([true, true, false, false, false, false])

    expect(preparedRate(list)).toBe(33)
    expect(unpreparedCount(list)).toBe(4)
  })

  it('0件なら 0%（0除算にしない）', () => {
    expect(preparedRate([])).toBe(0)
    expect(unpreparedCount([])).toBe(0)
  })

  it('全件準備済みなら 100%', () => {
    expect(preparedRate(items([true, true, true]))).toBe(100)
  })

  it('1件も準備していなければ 0%', () => {
    expect(preparedRate(items([false, false, false]))).toBe(0)
  })

  it('端数は四捨五入する（バックエンドの prepared_rate と同じ規則）', () => {
    // 1/3 = 33.33% → 33、2/3 = 66.67% → 67
    expect(preparedRate(items([true, false, false]))).toBe(33)
    expect(preparedRate(items([true, true, false]))).toBe(67)
  })
})

describe('ヒーローの1文', () => {
  it('未生成なら企業を選んで生成するよう促す', () => {
    expect(heroSentence('アルファテック', [])).toBe(
      '想定問答はまだありません。企業を選んで生成してください。',
    )
  })

  it('生成済みなら企業名・総数・未準備数を出す', () => {
    expect(heroSentence('アルファテック', items([true, false, false]))).toBe(
      'アルファテック の想定問答は 3問。未準備は 2問です。',
    )
  })
})

describe('生成元の表示', () => {
  it('AI 生成とテンプレを取り違えないよう文言を分ける', () => {
    expect(sourceLabel('ai')).toBe('AI生成')
    expect(sourceLabel('template')).toBe('テンプレ（APIキー未設定）')
  })

  it('未生成のうちは何も出さない', () => {
    expect(sourceLabel(null)).toBeNull()
  })
})
