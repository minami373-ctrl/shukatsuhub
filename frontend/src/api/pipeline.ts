/** 選考ステータス管理ボードの TanStack Query フック（`03-today-focus/FEATURE_PAGE_SPECS.md` §7）。
 *
 *  GET    /api/pipeline        … 5列カンバン ＋ ヘッダ件数
 *  POST   /api/companies       … 企業を追加
 *  PATCH  /api/companies/{id}  … 選考段階の変更（列の移動）
 *  DELETE /api/companies/{id}  … 削除（タスク・予定が紐づく企業は 422）
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

/** 選考段階。docs/spec.md §6 の stage。カンバンの列と1対1。 */
export type Stage = '気になる' | 'エントリー' | '書類選考' | '面接' | '最終・内定'

export const STAGES: Stage[] = ['気になる', 'エントリー', '書類選考', '面接', '最終・内定']

export type CompanyCard = {
  id: number
  name: string
  domain: string
  stage: string
  is_watched: boolean
  /** マッチング用（docs/spec.md §5.9）。空なら未登録＝その条件では合致しない */
  job_type: string | null
  location: string | null
  remote_ok: boolean
  tags: string | null
  /** 想定年収の下限（万円）と年間休日（日）。null は未登録＝マッチ率で合致しない */
  salary_min: number | null
  holidays_per_year: number | null
  /** 直近の未完了タスクの締切。無ければ null（推測でひも付けない） */
  next_task_at: string | null
  next_task_label: string | null
  /** 基準時刻以降で直近の予定。無ければ null */
  next_event_at: string | null
  next_event_title: string | null
}

export type PipelineColumn = {
  stage: string
  count: number
  companies: CompanyCard[]
}

export type PipelineResponse = {
  /** 緊急度（当日 / 3日以内）の判定に使う基準時刻 */
  now: string
  counts: { total: number; in_progress: number; offer: number }
  columns: PipelineColumn[]
}

/** 追加・変更フォームの中身。
 *
 *  締切は `Company` の列ではなく `Task` として登録される（バックエンド側で作る）。
 *  同じ意味の期限が2箇所に分かれるのを避けるため（docs/spec.md §6 の注記）。
 *  登録した締切はタスク一覧・今日画面・空き時間算出にもそのまま効く。
 */
export type CompanyInput = {
  name: string
  domain: string
  stage: Stage
  /** 登録企業フラグ。stage（カンバンの列）とは別物（docs/spec.md §6）。
   *  「気になるに追加」はこれを立てる。追加時は省略するとバックエンド側が true にする */
  is_watched?: boolean
  /** マッチング用（§5.9）。空文字なら未登録に戻す */
  job_type?: string | null
  location?: string | null
  remote_ok?: boolean
  tags?: string | null
  /** 年収（万円）・年間休日（日）。null なら未登録に戻す。AI に生成させない値（§5.9） */
  salary_min?: number | null
  holidays_per_year?: number | null
  /** 次の締切。空文字なら登録しない */
  deadline_at?: string | null
  /** 締切の名前（例「ES提出」）。省略時はバックエンドが「選考の締切」を使う */
  deadline_label?: string | null
  deadline_estimate_min?: number
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
  if (!res.ok) throw new Error(await errorMessage(res))
  return res
}

export async function getPipeline(): Promise<PipelineResponse> {
  const res = await send('/api/pipeline', 'GET')
  return (await res.json()) as PipelineResponse
}

export function usePipeline() {
  return useQuery({ queryKey: ['pipeline'], queryFn: getPipeline })
}

/** 企業を変えると受信箱の企業名やタスクの表示も変わるので、まとめて取り直す。 */
function useInvalidatePipeline() {
  const queryClient = useQueryClient()
  return () => {
    void queryClient.invalidateQueries({ queryKey: ['pipeline'] })
    void queryClient.invalidateQueries({ queryKey: ['tasks'] })
    void queryClient.invalidateQueries({ queryKey: ['today'] })
    void queryClient.invalidateQueries({ queryKey: ['emails'] })
  }
}

export function useCreateCompany() {
  const invalidate = useInvalidatePipeline()

  return useMutation({
    mutationFn: async (input: CompanyInput): Promise<CompanyCard> => {
      const res = await send('/api/companies', 'POST', input)
      return (await res.json()) as CompanyCard
    },
    onSuccess: invalidate,
  })
}

/** 選考段階の変更（列の移動）。名前の変更にも同じ口を使う。 */
export function useUpdateCompany() {
  const invalidate = useInvalidatePipeline()

  return useMutation({
    mutationFn: async ({
      id,
      ...changes
    }: { id: number } & Partial<CompanyInput>): Promise<CompanyCard> => {
      const res = await send(`/api/companies/${id}`, 'PATCH', changes)
      return (await res.json()) as CompanyCard
    },
    onSuccess: invalidate,
  })
}

export function useDeleteCompany() {
  const invalidate = useInvalidatePipeline()

  return useMutation({
    mutationFn: async (id: number): Promise<void> => {
      await send(`/api/companies/${id}`, 'DELETE')
    },
    onSuccess: invalidate,
  })
}
