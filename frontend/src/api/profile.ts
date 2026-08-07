/** プロフィール API の TanStack Query フック（spec.md §6 API 一覧）。 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import type { ProfileFields, ProfileResponse } from '../lib/profile'

export const profileQueryKey = ['profile'] as const

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

export async function fetchProfile(): Promise<ProfileResponse> {
  const res = await fetch('/api/profile')
  const body = await readBody(res)
  if (!res.ok) throw new Error(errorMessage(body, 'プロフィールを取得できませんでした'))
  return body as ProfileResponse
}

export async function putProfile(fields: ProfileFields): Promise<ProfileResponse> {
  const res = await fetch('/api/profile', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(fields),
  })
  const body = await readBody(res)
  if (!res.ok) throw new Error(errorMessage(body, 'プロフィールを保存できませんでした'))
  return body as ProfileResponse
}

export function useProfile() {
  return useQuery({ queryKey: profileQueryKey, queryFn: fetchProfile })
}

export function useSaveProfile() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: putProfile,
    onSuccess: (saved) => {
      // 保存結果をそのままキャッシュに反映する（リロードしても同じ内容が出る）
      queryClient.setQueryData(profileQueryKey, saved)
    },
  })
}
