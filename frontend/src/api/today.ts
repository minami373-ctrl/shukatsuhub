/** 今日画面の TanStack Query フック（docs/spec.md §4.1 / API 一覧）。
 *
 *  GET   /api/today        … 指標・タスク・要返信メール・予定・空きスロット
 *  PATCH /api/tasks/{id}   … チェックボックス（is_done の反転）
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

export type TodayTask = {
  id: number
  title: string
  short_label: string | null
  due_at: string
  estimate_min: number
  is_done: boolean
  /** 重要度（度合い）。高 / 中 / 低 */
  priority: string
  /** 表示タグ（行動の種類）。重要度とは別の軸 */
  badge: string | null
  company_id: number | null
  company_name: string | null
  /** 締切を過ぎているのに未完了。画面では黄色文字にする */
  is_overdue: boolean
}

export type TodayEvent = {
  id: number
  title: string
  kind: '選考' | '学業'
  start_at: string
  end_at: string
  location: string | null
}

export type TodayFreeSlot = {
  start: string
  end: string
  minutes: number
  suggested_task_id: number | null
  suggested_task_label: string | null
}

/** 研究にあてられる区間（10:00〜17:00 のうち予定が入っていない時間）。 */
export type TodayResearchSlot = {
  start: string
  end: string
  minutes: number
}

export type TodayEmail = {
  id: number
  subject: string
  category: string
  from_name: string | null
  company_name: string | null
  received_at: string
}

export type TodayResponse = {
  date: string
  /** 10:00〜17:00 のうち予定が入っていない時間 */
  research_hours: number
  /** 研究枠の外（08:00〜10:00 / 17:00〜22:00）の空き時間 */
  free_hours: number
  open_task_count: number
  event_count: number
  needs_reply_count: number
  nearest_task_label: string | null
  tasks: TodayTask[]
  emails: TodayEmail[]
  events: TodayEvent[]
  free_slots: TodayFreeSlot[]
  research_slots: TodayResearchSlot[]
  tomorrow_event: TodayEvent | null
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

export async function getToday(): Promise<TodayResponse> {
  const res = await fetch('/api/today')
  if (!res.ok) {
    throw new Error(await errorMessage(res))
  }
  return (await res.json()) as TodayResponse
}

export function useToday() {
  return useQuery({ queryKey: ['today'], queryFn: getToday })
}

/** チェックボックス。成功したら今日画面とタスク一覧を取り直して指標を再計算させる（§4.1）。 */
export function useToggleTask() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({ id, isDone }: { id: number; isDone: boolean }): Promise<TodayTask> => {
      const res = await fetch(`/api/tasks/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ is_done: isDone }),
      })
      if (!res.ok) {
        throw new Error(await errorMessage(res))
      }
      return (await res.json()) as TodayTask
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['today'] })
      // タスク・締め切りページ（/tasks）も同じ is_done を見ているので一緒に取り直す
      void queryClient.invalidateQueries({ queryKey: ['tasks'] })
    },
  })
}
