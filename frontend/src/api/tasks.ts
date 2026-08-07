/** タスク・締め切りページの TanStack Query フック（`03-today-focus/FEATURE_PAGE_SPECS.md` §6）。
 *
 *  GET    /api/tasks?scope=today|week|all|done … 一覧 ＋ ヘッダの件数
 *  POST   /api/tasks        … 追加（内容・期限・重要度）
 *  PATCH  /api/tasks/{id}   … 変更
 *  DELETE /api/tasks/{id}   … 削除
 *
 *  チェックボックスの反転は api/today.ts の useToggleTask を使い回す（同じ
 *  PATCH /api/tasks/{id} なので2つ作らない）。
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import type { TodayTask } from './today'

/** §6 のセグメント。バックエンドの Literal と同じ4値。 */
export type TaskScope = 'today' | 'week' | 'all' | 'done'

export const SCOPES: { value: TaskScope; label: string }[] = [
  { value: 'today', label: '今日' },
  { value: 'week', label: '今週' },
  { value: 'all', label: 'すべて' },
  { value: 'done', label: '完了' },
]

/** ページヘッダの「今日 5件・期限切れ 1件・今週 12件」。絞り込みを変えても動かない。 */
export type TaskCounts = {
  today: number
  overdue: number
  week: number
}

export type TaskListResponse = {
  scope: TaskScope
  date: string
  /** 期限切れ判定の基準時刻。期限タグの色分けもこれと比較する */
  now: string
  counts: TaskCounts
  tasks: TodayTask[]
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

export async function getTasks(scope: TaskScope): Promise<TaskListResponse> {
  const res = await fetch(`/api/tasks?scope=${scope}`)
  if (!res.ok) {
    throw new Error(await errorMessage(res))
  }
  return (await res.json()) as TaskListResponse
}

export function useTasks(scope: TaskScope) {
  return useQuery({ queryKey: ['tasks', scope], queryFn: () => getTasks(scope) })
}

/** 重要度（度合い）。docs/spec.md §6 の priority。既定は「中」。 */
export type Priority = '高' | '中' | '低'

export const PRIORITIES: Priority[] = ['高', '中', '低']

/** 表示タグ（行動の種類）。docs/spec.md §6 の badge。重要度とは別の軸なので混ぜない。 */
export type Badge = '最優先' | '要返信' | '準備'

export const BADGES: Badge[] = ['最優先', '要返信', '準備']

/** 追加・変更フォームの中身。期限は datetime-local の値（2026-07-31T18:00）をそのまま渡す。 */
export type TaskInput = {
  title: string
  due_at: string
  /** 見積り分。空き時間の算出に効く（docs/spec.md §5.3）。既定 30 */
  estimate_min: number
  priority: Priority
  badge: Badge | null
}

/** 追加・変更・削除のあとは一覧と今日画面の両方を取り直す（指標が変わるため）。 */
function useInvalidateTasks() {
  const queryClient = useQueryClient()
  return () => {
    void queryClient.invalidateQueries({ queryKey: ['tasks'] })
    void queryClient.invalidateQueries({ queryKey: ['today'] })
  }
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

export function useCreateTask() {
  const invalidate = useInvalidateTasks()

  return useMutation({
    mutationFn: async (input: TaskInput): Promise<TodayTask> => {
      const res = await send('/api/tasks', 'POST', input)
      return (await res.json()) as TodayTask
    },
    onSuccess: invalidate,
  })
}

export function useUpdateTask() {
  const invalidate = useInvalidateTasks()

  return useMutation({
    mutationFn: async ({ id, ...input }: TaskInput & { id: number }): Promise<TodayTask> => {
      const res = await send(`/api/tasks/${id}`, 'PATCH', input)
      return (await res.json()) as TodayTask
    },
    onSuccess: invalidate,
  })
}

export function useDeleteTask() {
  const invalidate = useInvalidateTasks()

  return useMutation({
    mutationFn: async (id: number): Promise<void> => {
      await send(`/api/tasks/${id}`, 'DELETE')
    },
    onSuccess: invalidate,
  })
}
