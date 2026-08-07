/** 想定問答の純ロジック（spec.md §4.5 / §5.6）。
 *  準備率・未準備数・ヒーローの1文はここだけで組み立てる。Vitest の検証対象。 */

export type QACategory = '志望動機' | 'ガクチカ' | '逆質問'

/** 生成元。ユーザーが AI とテンプレを取り違えないよう画面に明示する（§4.5）。 */
export type QASource = 'ai' | 'template'

export type QAItem = {
  id: number
  company_id: number
  question: string
  answer_draft: string
  category: QACategory
  is_prepared: boolean
  source: QASource
  generated_at: string
}

export type QASheet = {
  company_id: number
  /** 1件も生成されていなければ null */
  source: QASource | null
  items: QAItem[]
  prepared_rate: number
}

export type CompanyOption = { id: number; name: string; tags: string | null }

/** 準備済み（回答を保存済み）でない件数（ヒーローの「未準備」）。 */
export function unpreparedCount(items: QAItem[]): number {
  return items.filter((item) => !item.is_prepared).length
}

/** 回答を保存できるか（前後の空白を除いて空なら保存させない。§4.5）。 */
export function canSaveAnswer(draft: string): boolean {
  return draft.trim() !== ''
}

/** 準備率%（is_prepared が true の件数 ÷ 総件数）。0件なら 0。
 *  バックエンドの prepared_rate() と同じ規則にする（表示中の一覧と必ず一致させるため）。 */
export function preparedRate(items: QAItem[]): number {
  if (items.length === 0) return 0
  const prepared = items.length - unpreparedCount(items)
  return Math.round((prepared / items.length) * 100)
}

/** ヒーローの1文（spec.md §4.5）。件数の羅列ではなく次の行動を示す。 */
export function heroSentence(companyName: string | null, items: QAItem[]): string {
  if (items.length === 0) {
    return '想定問答はまだありません。企業を選んで生成してください。'
  }
  return `${companyName ?? '選択中の企業'} の想定問答は ${items.length}問。未準備は ${unpreparedCount(items)}問です。`
}

/** 生成元の表示ラベル（§4.5）。文言は仕様書のまま使う。 */
export function sourceLabel(source: QASource | null): string | null {
  if (source === 'ai') return 'AI生成'
  if (source === 'template') return 'テンプレ（APIキー未設定）'
  return null
}

/** カテゴリタグの色。志望動機＝ティール／ガクチカ＝黄系／逆質問＝グレー。
 *  受信箱の重要（赤系 .tag.d）と competing しないよう、赤は使わない。 */
export const CATEGORY_TAG_CLASS: Record<QACategory, string> = {
  志望動機: 'tag',
  ガクチカ: 'tag w',
  逆質問: 'tag g',
}
