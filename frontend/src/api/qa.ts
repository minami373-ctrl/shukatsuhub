/** 想定問答 API の TanStack Query フック（spec.md §6 API 一覧）。
 *
 *  GET   /api/companies    … 企業セレクトの選択肢
 *  GET   /api/qa           … クエリ company_id の一覧 ＋ source ＋ prepared_rate
 *  POST  /api/qa/generate  … 生成（既存を入れ替える）
 *  PATCH /api/qa/{id}      … 回答骨子の保存（保存すると準備済みになる）
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import type { CompanyOption, QAItem, QASheet } from '../lib/qa'

export const companiesQueryKey = ['companies'] as const

export function qaQueryKey(companyId: number | null) {
  return ['qa', companyId] as const
}

async function readBody(res: Response): Promise<unknown> {
  return res.json().catch(() => null)
}

/** サーバーが返した detail をそのまま画面のエラー表示に使う。 */
function errorMessage(body: unknown, fallback: string): string {
  if (body && typeof body === 'object' && 'detail' in body) {
    const detail = (body as { detail: unknown }).detail
    if (typeof detail === 'string') return detail
  }
  return fallback
}

export async function fetchCompanies(): Promise<CompanyOption[]> {
  const res = await fetch('/api/companies')
  const body = await readBody(res)
  if (!res.ok) throw new Error(errorMessage(body, '企業一覧を取得できませんでした'))
  return body as CompanyOption[]
}

export async function fetchQA(companyId: number): Promise<QASheet> {
  const res = await fetch(`/api/qa?company_id=${companyId}`)
  const body = await readBody(res)
  if (!res.ok) throw new Error(errorMessage(body, '想定問答を取得できませんでした'))
  return body as QASheet
}

export async function postGenerateQA(companyId: number): Promise<QASheet> {
  const res = await fetch('/api/qa/generate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ company_id: companyId }),
  })
  const body = await readBody(res)
  if (!res.ok) throw new Error(errorMessage(body, '想定問答を生成できませんでした'))
  return body as QASheet
}

export async function patchQAAnswer(id: number, answerDraft: string): Promise<QAItem> {
  const res = await fetch(`/api/qa/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ answer_draft: answerDraft }),
  })
  const body = await readBody(res)
  if (!res.ok) throw new Error(errorMessage(body, '回答を保存できませんでした'))
  return body as QAItem
}

export function useCompanies() {
  return useQuery({ queryKey: companiesQueryKey, queryFn: fetchCompanies })
}

/** 企業が決まるまでは投げない（company_id が必須クエリなので 422 になる）。 */
export function useQASheet(companyId: number | null) {
  return useQuery({
    queryKey: qaQueryKey(companyId),
    queryFn: () => fetchQA(companyId as number),
    enabled: companyId !== null,
  })
}

export function useGenerateQA() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: postGenerateQA,
    onSuccess: (sheet) => {
      // 生成結果をそのままキャッシュに反映する（再取得の往復を1回省く）
      queryClient.setQueryData(qaQueryKey(sheet.company_id), sheet)
    },
  })
}

/** 回答を保存したら一覧を取り直して準備率とヒーローの指標を再計算させる（§4.5）。 */
export function useSaveQAAnswer(companyId: number | null) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, answerDraft }: { id: number; answerDraft: string }) =>
      patchQAAnswer(id, answerDraft),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: qaQueryKey(companyId) })
    },
  })
}
