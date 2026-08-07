/** イベント取得とカレンダー同期の TanStack Query フック。
 *
 *  GET  /api/events?from=&to=
 *  POST /api/calendar/sync
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import type { ApiEvent } from './eventMap'

export type SyncResult = { added: number; updated: number }

async function getJson<T>(url: string): Promise<T> {
  const res = await fetch(url)
  if (!res.ok) {
    throw new Error(await errorMessage(res))
  }
  return (await res.json()) as T
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

/** 期間（ISO 文字列）に重なるイベントを取得する。 */
export function useEvents(from: string | null, to: string | null) {
  return useQuery({
    queryKey: ['events', from, to],
    // from / to が決まるのはカレンダーの表示範囲が確定した後
    enabled: from !== null && to !== null,
    queryFn: () =>
      getJson<ApiEvent[]>(`/api/events?from=${encodeURIComponent(from!)}&to=${encodeURIComponent(to!)}`),
  })
}

/** seed からの同期。成功したらイベントを再取得する。 */
export function useSyncCalendar() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (): Promise<SyncResult> => {
      const res = await fetch('/api/calendar/sync', { method: 'POST' })
      if (!res.ok) {
        throw new Error(await errorMessage(res))
      }
      return (await res.json()) as SyncResult
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['events'] })
    },
  })
}
