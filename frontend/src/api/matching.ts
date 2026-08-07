/** 企業の発見・マッチングの TanStack Query フック（`03-today-focus/FEATURE_PAGE_SPECS.md` §12）。
 *
 *  POST /api/matching                … テンプレ質問の回答から、条件に合う企業をマッチ率つきで返す
 *  GET  /api/companies/suggestions   … 受信箱からの企業登録の提案（docs/spec.md §5.11）
 *  POST /api/companies/from-emails   … 提案されたドメインを企業として登録
 *
 *  **マッチ率は AI ではなくプログラム計算**（docs/spec.md §5.9）。同じ条件なら常に同じ結果になる。
 *  「気になるに追加」は既存の PATCH /api/companies/{id} で stage を変えるだけ（api/pipeline.ts）。
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import type { CompanyCard } from './pipeline'

/** セグメント（§12 のフィルタ）。 */
export type MatchScope = 'recommended' | 'search' | 'watched'

export const MATCH_SCOPES: { value: MatchScope; label: string }[] = [
  { value: 'recommended', label: 'おすすめ' },
  { value: 'search', label: '条件検索' },
  { value: 'watched', label: '気になる' },
]

/** テンプレ質問の回答。すべて任意だが、1つも無いと 422 になる。 */
export type MatchCriteria = {
  job_type: string
  location: string
  remote_only: boolean
  /** 希望年収の下限（万円）。入力欄の生の文字列。空なら条件に数えない */
  salary_min: string
  /** 希望する年間休日の下限（日）。空なら条件に数えない */
  holidays_min: string
  /** 就活軸。null を渡すとプロフィールの job_axis が使われる */
  axes: string[] | null
  scope: MatchScope
}

export type MatchedCompany = {
  id: number
  name: string
  domain: string
  stage: string
  is_watched: boolean
  job_type: string | null
  location: string | null
  remote_ok: boolean
  /** 企業側の登録値。null は未登録＝その条件では合致しない */
  salary_min: number | null
  holidays_per_year: number | null
  /** 0〜100 */
  rate: number
  /** 合致した条件だけ。合致しなかったものは入っていない */
  reasons: string[]
}

export type MatchResponse = {
  /** 企業一覧の取得元。実データ移行後は 'api' などになる（docs/spec.md §5.10） */
  source: string
  axes: string[]
  recommended_count: number
  total_count: number
  items: MatchedCompany[]
}

async function errorMessage(res: Response): Promise<string> {
  try {
    const body = (await res.json()) as { detail?: unknown }
    if (typeof body.detail === 'string') return body.detail
  } catch {
    // JSON でないときは下のフォールバックを使う
  }
  return `${res.status} ${res.statusText}`
}

/** 数値の入力欄を API の値に直す。空・数値でないものは「指定なし」として null にする。 */
function toNumberOrNull(value: string): number | null {
  const trimmed = value.trim()
  if (trimmed === '') return null
  const parsed = Number(trimmed)
  // 負数や NaN を送ると 422 になるだけなので、ここで「指定なし」に倒す
  return Number.isFinite(parsed) && parsed >= 0 ? Math.round(parsed) : null
}

export async function postMatching(criteria: MatchCriteria): Promise<MatchResponse> {
  const res = await fetch('/api/matching', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    // 空文字は「条件なし」。null / 空文字はバックエンドで条件に数えない
    body: JSON.stringify({
      job_type: criteria.job_type.trim() || null,
      location: criteria.location.trim() || null,
      remote_only: criteria.remote_only,
      salary_min: toNumberOrNull(criteria.salary_min),
      holidays_min: toNumberOrNull(criteria.holidays_min),
      axes: criteria.axes,
      scope: criteria.scope,
    }),
  })
  if (!res.ok) throw new Error(await errorMessage(res))
  return (await res.json()) as MatchResponse
}

/** 検索はユーザーが押したときだけ走らせたいので useMutation を使う（useQuery にしない）。 */
export function useMatching() {
  return useMutation({ mutationFn: postMatching })
}

// ===== 受信箱からの企業登録の提案（docs/spec.md §5.11） =====

/** 未登録ドメインからの受信メールをまとめた登録候補。
 *
 *  **メールから分かるのはドメインと送信者表示名だけ。**職種・勤務地・リモート可否・年収・休日は
 *  メールに書いていないので登録時は未登録のまま作る（推測で埋めない。CLAUDE.md §E）。
 *  条件は登録後に企業ダイアログ（/pipeline）で人が入れる。
 */
export type CompanySuggestion = {
  domain: string
  /** 送信者表示名の最頻値。無ければドメイン。登録後に名前を直せる */
  suggested_name: string
  email_count: number
  latest_received_at: string
  categories: string[]
}

export type FromEmailsResponse = {
  created: CompanyCard[]
  /** 既に登録済みで読み飛ばしたドメイン */
  skipped: string[]
  /** 企業に紐づけ直したメールの件数 */
  linked_emails: number
}

export async function getCompanySuggestions(): Promise<CompanySuggestion[]> {
  const res = await fetch('/api/companies/suggestions')
  if (!res.ok) throw new Error(await errorMessage(res))
  return ((await res.json()) as { items: CompanySuggestion[] }).items
}

export function useCompanySuggestions() {
  return useQuery({ queryKey: ['company-suggestions'], queryFn: getCompanySuggestions })
}

export function useCreateCompaniesFromEmails() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (domains: string[]): Promise<FromEmailsResponse> => {
      const res = await fetch('/api/companies/from-emails', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ domains }),
      })
      if (!res.ok) throw new Error(await errorMessage(res))
      return (await res.json()) as FromEmailsResponse
    },
    // 企業が増えると受信箱の企業名・選考ボード・候補一覧がまとめて変わる
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['company-suggestions'] })
      void queryClient.invalidateQueries({ queryKey: ['pipeline'] })
      void queryClient.invalidateQueries({ queryKey: ['emails'] })
    },
  })
}
