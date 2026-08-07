/** ナレッジ蓄積 API の TanStack Query フック（docs/spec.md §6 Knowledge / API 一覧）。
 *
 *  GET  /api/knowledge … クエリ category でフィルタしたメモ一覧（更新日時の新しい順）
 *  POST /api/knowledge … メモを1件追加
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

export type KnowledgeCategory = '面接振り返り' | '企業メモ' | 'テンプレート' | '学び'

export type KnowledgeNote = {
  id: number
  title: string
  category: KnowledgeCategory
  company_id: number | null
  company_name: string | null
  content: string
  updated_at: string
}

export type NewKnowledgeNote = {
  title: string
  category: KnowledgeCategory
  company_id: number | null
  content: string
}

export function knowledgeQueryKey(category?: string) {
  return ['knowledge', category] as const
}

async function readBody(res: Response): Promise<unknown> {
  return res.json().catch(() => null)
}

function errorMessage(body: unknown, fallback: string): string {
  if (body && typeof body === 'object' && 'detail' in body) {
    const detail = (body as { detail: unknown }).detail
    if (typeof detail === 'string') return detail
  }
  return fallback
}

export async function fetchKnowledge(category?: string): Promise<KnowledgeNote[]> {
  const query = category ? `?category=${encodeURIComponent(category)}` : ''
  const res = await fetch(`/api/knowledge${query}`)
  const body = await readBody(res)
  if (!res.ok) throw new Error(errorMessage(body, 'メモを取得できませんでした'))
  return body as KnowledgeNote[]
}

export async function postKnowledge(note: NewKnowledgeNote): Promise<KnowledgeNote> {
  const res = await fetch('/api/knowledge', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(note),
  })
  const body = await readBody(res)
  if (!res.ok) throw new Error(errorMessage(body, 'メモを追加できませんでした'))
  return body as KnowledgeNote
}

export function useKnowledge(category?: string) {
  return useQuery({ queryKey: knowledgeQueryKey(category), queryFn: () => fetchKnowledge(category) })
}

export function useAddKnowledge() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: postKnowledge,
    onSuccess: () => {
      // カテゴリ別のキャッシュも古くなるので、knowledge で始まるものをまとめて無効化する
      void queryClient.invalidateQueries({ queryKey: ['knowledge'] })
    },
  })
}
