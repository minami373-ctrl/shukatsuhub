/** Gmail 実連携の TanStack Query フック。
 *
 *  GET    /api/gmail/status  連携状態（トークン本体は返らない）
 *  GET    /api/gmail/auth    認可 URL を取り出す
 *  POST   /api/gmail/sync    Gmail から取り込む（未認可・失敗なら seed のまま）
 *  DELETE /api/gmail/auth    連携解除（メールは消えない）
 *
 *  `api/useEvents.ts` のカレンダー同期と同じ作法に揃えている。
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

export type GmailStatus = {
  connected: boolean
  configured: boolean
  scope: string | null
  expires_at: string | null
}

export type GmailSyncResult = {
  added: number
  updated: number
  ai_decided: number
  /** gmail = 実連携から取り込んだ / seed = 未認可・失敗でダミーデータのまま */
  source: 'gmail' | 'seed'
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

async function getJson<T>(url: string): Promise<T> {
  const res = await fetch(url)
  if (!res.ok) {
    throw new Error(await errorMessage(res))
  }
  return (await res.json()) as T
}

/** 連携状態を取得する。 */
export function useGmailStatus() {
  return useQuery({
    queryKey: ['gmail', 'status'],
    queryFn: () => getJson<GmailStatus>('/api/gmail/status'),
  })
}

/** Gmail から取り込む。成功したらメール一覧を再取得する。 */
export function useSyncGmail() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (): Promise<GmailSyncResult> => {
      const res = await fetch('/api/gmail/sync', { method: 'POST' })
      if (!res.ok) {
        throw new Error(await errorMessage(res))
      }
      return (await res.json()) as GmailSyncResult
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['emails'] })
    },
  })
}

/** 認可 URL を取り出して Google の同意画面へ遷移する。 */
export function useStartGmailAuth() {
  return useMutation({
    mutationFn: async (): Promise<void> => {
      const { auth_url } = await getJson<{ auth_url: string }>('/api/gmail/auth')
      window.location.assign(auth_url)
    },
  })
}
