/** 企業研究ページの TanStack Query フック（画面は /interview）。
 *
 *  GET   /api/research/companies    … 左カラムの企業一覧（収集済みか・未確認の観点）
 *  GET   /api/research?company_id=  … その企業のメモ（マークダウン）＋ 出典 ＋ 確認観点
 *  POST  /api/research/collect      … 企業ドメインの公開ページを読み、AI に整理させる
 *  PATCH /api/research/checks/{id}  … 確認観点の完了を反転
 *
 *  収集元 URL の登録は持たない（読むのは企業ドメイン配下の定番ページだけ）。
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

/** 情報の由来。web=公開ページから整理／ai=ページが読めず観点のみ／template=AI 未設定／seed=サンプル。 */
export type ReportSource = 'web' | 'ai' | 'template' | 'seed'

/** 公開ページ取得の結果。 */
export type FetchStatus = 'ok' | 'robots_denied' | 'error'

export type ResearchCheck = {
  id: number
  company_id: number
  label: string
  is_done: boolean
  source: ReportSource
}

export type ResearchReport = {
  company_id: number
  markdown: string
  source_urls: string[]
  source: ReportSource
  collected_at: string
}

/** 左カラムの企業1行。 */
export type ResearchCompany = {
  id: number
  name: string
  domain: string
  collected_at: string | null
  source: ReportSource | null
  unchecked: number
}

export type ResearchResponse = {
  company_id: number
  company_name: string
  /** 未収集なら null */
  report: ResearchReport | null
  checks: ResearchCheck[]
  unchecked: number
}

export type FetchOutcome = {
  url: string
  status: FetchStatus
  message: string | null
}

export type CollectResponse = {
  company_id: number
  source: 'web' | 'ai' | 'template'
  report: ResearchReport
  checks: ResearchCheck[]
  fetched: FetchOutcome[]
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

async function send(url: string, method: string, body?: unknown): Promise<Response> {
  const res = await fetch(url, {
    method,
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!res.ok) {
    throw new Error(await errorMessage(res))
  }
  return res
}

export async function getResearchCompanies(): Promise<ResearchCompany[]> {
  const res = await fetch('/api/research/companies')
  if (!res.ok) throw new Error(await errorMessage(res))
  return (await res.json()) as ResearchCompany[]
}

export function useResearchCompanies() {
  return useQuery({ queryKey: ['research', 'companies'], queryFn: getResearchCompanies })
}

export async function getResearch(companyId: number): Promise<ResearchResponse> {
  const res = await fetch(`/api/research?company_id=${companyId}`)
  if (!res.ok) throw new Error(await errorMessage(res))
  return (await res.json()) as ResearchResponse
}

/** 企業が決まるまでは投げない（company_id が必須クエリなので 422 になる）。 */
export function useResearch(companyId: number | null) {
  return useQuery({
    queryKey: ['research', 'report', companyId],
    queryFn: () => getResearch(companyId as number),
    enabled: companyId !== null,
  })
}

/** 収集・確認観点の変更のあとは企業一覧とメモの両方を取り直す。 */
function useInvalidateResearch() {
  const queryClient = useQueryClient()
  return () => {
    void queryClient.invalidateQueries({ queryKey: ['research'] })
  }
}

/** 公開ページを読んで AI に整理させる（このページの主要アクション）。 */
export function useCollect() {
  const invalidate = useInvalidateResearch()

  return useMutation({
    mutationFn: async (companyId: number): Promise<CollectResponse> => {
      const res = await send('/api/research/collect', 'POST', { company_id: companyId })
      return (await res.json()) as CollectResponse
    },
    onSuccess: invalidate,
  })
}

export function useToggleCheck() {
  const invalidate = useInvalidateResearch()

  return useMutation({
    mutationFn: async ({ id, isDone }: { id: number; isDone: boolean }): Promise<ResearchCheck> => {
      const res = await send(`/api/research/checks/${id}`, 'PATCH', { is_done: isDone })
      return (await res.json()) as ResearchCheck
    },
    onSuccess: invalidate,
  })
}
