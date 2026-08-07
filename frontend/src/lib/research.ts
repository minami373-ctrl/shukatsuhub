/** 企業研究ページの表示ロジック（純関数）。Vitest でテストするのはこのファイル。
 *
 *  API（GET /api/research）は素材だけを返し、「AI収集」「8/5 10:42 収集」のような
 *  文言はここで組み立てる。
 */

import type { FetchOutcome, ReportSource, ResearchCompany } from '../api/research'
import { formatMd } from './tasks'
import { formatHm } from './today'

/** 由来のラベル。何を根拠にした情報かを取り違えないよう言い換える。 */
export function sourceLabel(source: ReportSource): string {
  if (source === 'web') return 'AI収集'
  if (source === 'ai') return 'AI（調べる観点）'
  if (source === 'template') return 'テンプレ'
  return 'サンプル'
}

/** 由来タグの CSS クラス。公開ページを根拠にしたものだけティールにする（DESIGN_RULES §3）。 */
export function sourceTagClass(source: ReportSource): string {
  return source === 'web' ? 'tag' : 'tag cls'
}

/** URL のホスト部分。出典リンクのラベルに使う（長い URL を1行に入れないため）。 */
export function hostOf(url: string): string {
  try {
    return new URL(url).host
  } catch {
    return url
  }
}

/** 出典リンクの表示名。同じホストが並ぶのでパスまで出す。 */
export function sourceLinkLabel(url: string): string {
  try {
    const parsed = new URL(url)
    return `${parsed.host}${parsed.pathname === '/' ? '' : parsed.pathname}`
  } catch {
    return url
  }
}

/** 企業一覧1行の補足。収集済みならいつ集めたか、未収集ならそう出す。 */
export function companyMeta(company: ResearchCompany): string {
  if (company.collected_at === null) return `${company.domain}・未収集`
  return `${formatMd(company.collected_at)} ${formatHm(company.collected_at)} 収集`
}

/** メモの見出し右に出す収集時刻。 */
export function collectedAtLabel(collectedAt: string): string {
  return `${formatMd(collectedAt)} ${formatHm(collectedAt)} 収集`
}

/** 収集を実行したあとの状態表示。何が起きたかを言葉で残す。 */
export function collectToast(
  source: 'web' | 'ai' | 'template',
  fetched: FetchOutcome[],
): string {
  const ok = fetched.filter((f) => f.status === 'ok').length
  if (source === 'web') {
    const denied = fetched.filter((f) => f.status === 'robots_denied').length
    const skipped = denied > 0 ? `（robots で ${denied}件は読まず）` : ''
    return `公開ページ ${ok}件を読んでまとめました${skipped}。`
  }
  if (source === 'ai') {
    const denied = fetched.some((f) => f.status === 'robots_denied')
    return denied
      ? 'robots.txt が許可していないため本文は読めませんでした。調べる観点だけをまとめました。'
      : '公開ページを読めなかったので、調べる観点だけをまとめました。'
  }
  return 'AI が使えないため、テンプレの観点を入れました（AZURE_OPENAI_API_KEY 未設定）。'
}

/** ヒーローの1文。件数の羅列ではなく行動を促す文にする（PROMPT.md）。 */
export function heroSentence(
  companyName: string | null,
  hasReport: boolean,
  unchecked: number,
): string {
  if (companyName === null) return '企業が登録されていません。まず企業を追加してください。'
  if (!hasReport) {
    return `${companyName} はまだ調べていません。「AI で情報を集める」を押してください。`
  }
  if (unchecked > 0) {
    return `${companyName} の研究メモができています。未確認の観点が ${unchecked}点あります。`
  }
  return `${companyName} は確認観点まで済んでいます。次の企業に進めます。`
}
