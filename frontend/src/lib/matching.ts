/** 企業の発見・マッチングの表示ロジック（純関数）。Vitest でテストするのはこのファイル。
 *
 *  `03-today-focus/FEATURE_PAGE_SPECS.md` §12。マッチ率の計算はバックエンド（§5.9）で、
 *  ここは色分けと文言だけを担当する。
 *
 *  マッチ率の色（§12）：90%以上 = --ok ／ 70〜89% = --brand ／ それ未満は色を付けない。
 */

import type { CompanySuggestion, MatchedCompany } from '../api/matching'

export type RateTone = 'ok' | 'brand' | 'plain'

export function rateTone(rate: number): RateTone {
  if (rate >= 90) return 'ok'
  if (rate >= 70) return 'brand'
  return 'plain'
}

/** マッチ率タグの CSS クラス。色はリテラルで書かず既存語彙に寄せる。 */
export function rateClass(tone: RateTone): string {
  if (tone === 'ok') return 'tag ok'
  if (tone === 'brand') return 'tag'
  return 'tag g'
}

/** カードの補足行。職種・勤務地・リモートを1行にまとめる。
 *
 *  会社側が空の項目は出さない（推測で埋めない。CLAUDE.md §E）。
 */
export function companyMeta(company: MatchedCompany): string {
  const parts = [company.job_type, company.location].filter(
    (v): v is string => typeof v === 'string' && v.trim() !== '',
  )
  if (company.remote_ok) parts.push('リモート可')
  // 年収・休日は AI に生成させず、企業に保存した値をそのまま並記する（docs/spec.md §5.9）。
  // マッチ率の根拠を目で照合できるようにするため、未登録なら何も出さない
  if (company.salary_min !== null) parts.push(`年収${company.salary_min}万〜`)
  if (company.holidays_per_year !== null) parts.push(`休日${company.holidays_per_year}日`)
  return parts.length === 0 ? '条件は未登録' : parts.join('・')
}

/** ヒーローの1文。件数の羅列ではなく行動を促す文にする（PROMPT.md）。 */
export function heroSentence(
  searched: boolean,
  recommendedCount: number,
  topName: string | null,
): string {
  if (!searched) {
    return '条件を入力すると、合いそうな企業が出ます。'
  }
  if (recommendedCount === 0 || topName === null) {
    return '条件に強く合う企業はありませんでした。条件をゆるめてみてください。'
  }
  return `おすすめは ${recommendedCount}社。まず ${topName} を見てください。`
}

/** 「気になるに追加」を出すか。既に気になる以降の段階なら出さない。 */
export function canWatch(company: MatchedCompany): boolean {
  return !company.is_watched && company.stage === '気になる'
}

/** 追加済みのときにカードへ出す文言。 */
export function watchedLabel(company: MatchedCompany): string {
  if (company.is_watched) return '登録済み'
  return company.stage === '気になる' ? '' : `選考中（${company.stage}）`
}

/** 登録候補の補足行（docs/spec.md §5.11）。何件のどんなメールが根拠かを出す。
 *
 *  候補の根拠は**受信済みのメールだけ**。ここに書いていないこと（職種・年収など）は
 *  メールから分からないので、登録後に人が入れる。
 */
export function suggestionMeta(suggestion: CompanySuggestion): string {
  const categories = suggestion.categories.join('・')
  const kinds = categories === '' ? '' : `（${categories}）`
  return `${suggestion.domain}／メール${suggestion.email_count}件${kinds}`
}

/** 登録候補セクションの見出し。0件なら出さない判断は呼び出し側で行う。 */
export function suggestionHeading(count: number): string {
  return `📥 受信箱から見つけた未登録の企業 ${count}件`
}
