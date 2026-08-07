/** プロフィール画面（spec.md §7「プロフィールの永続化とコピー」「充実度の算出」）。
 *
 *  バックエンドは fetch をモックして代替する（API 自体の検証は pytest 側）。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  EMPTY_PROFILE,
  PROFILE_FIELDS,
  type ProfileFields,
  type ProfileResponse,
} from '../lib/profile'
import { ProfilePage } from './Profile'

/** 6項目だけ埋まった状態（受け入れ条件の 67% ケース）。 */
const SIX_FILLED: ProfileFields = {
  ...EMPTY_PROFILE,
  gakuchika: '研究室の輪講運営を担当しました。',
  strengths: '散らばった情報を1か所に集めることです。',
  self_pr: '手を動かして課題を切り分けます。',
  academics: '時系列データの異常検知を研究しています。',
  teamwork: '3人チームで前処理を担当しました。',
  skills: '基本情報技術者。Python と PyTorch。',
}

function completenessOf(fields: ProfileFields): number {
  const filled = Object.values(fields).filter((v) => v.trim() !== '').length
  return Math.round((filled / PROFILE_FIELDS.length) * 100)
}

/** サーバー側のプロフィールを1件だけ持つ、最小の fetch モック。 */
function mockServer(initial: ProfileFields) {
  const store: { current: ProfileFields } = { current: initial }
  const put = vi.fn()

  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const respond = (body: ProfileResponse) =>
      new Response(JSON.stringify(body), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })

    if (url !== '/api/profile') throw new Error(`想定外のリクエスト: ${url}`)

    if (init?.method === 'PUT') {
      const sent = JSON.parse(String(init.body)) as ProfileFields
      put(sent)
      store.current = sent
    }
    return respond({ ...store.current, completeness: completenessOf(store.current) })
  })

  vi.stubGlobal('fetch', fetchMock)
  return { store, put, fetchMock }
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  })
  // ヒーローの「← 今日」は react-router の Link なので、実行時と同じく Router 内で描画する
  const view = render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <ProfilePage onCompletenessChange={() => {}} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return { ...view, queryClient }
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('充実度の算出', () => {
  it('9項目のうち6項目が空でないとき 67% と表示される', async () => {
    mockServer(SIX_FILLED)
    renderPage()

    await waitFor(() => expect(screen.getAllByText('67%').length).toBeGreaterThan(0))
    // 内訳は「入力済み / 未入力」の指標で見せる
    expect(screen.getByText('6項目')).toBeInTheDocument()
    expect(screen.getByText('3項目')).toBeInTheDocument()
  })

  it('入力すると充実度が即座に上がる', async () => {
    const user = userEvent.setup()
    mockServer(SIX_FILLED)
    renderPage()
    await screen.findByDisplayValue(SIX_FILLED.gakuchika)

    await user.type(screen.getByLabelText('就活軸'), '裁量')

    await waitFor(() => expect(screen.getAllByText('78%').length).toBeGreaterThan(0))
  })

  it('未入力項目はヒーローの1文に挙がる', async () => {
    mockServer(SIX_FILLED)
    renderPage()

    expect(
      await screen.findByText(
        '未入力は「志望動機テンプレ・キャリアプラン・就活軸」だけ。埋めれば想定問答が作れます。',
      ),
    ).toBeInTheDocument()
  })
})

describe('永続化', () => {
  it('編集して保存すると、その内容が PUT される', async () => {
    const user = userEvent.setup()
    const { put } = mockServer(SIX_FILLED)
    renderPage()
    await screen.findByDisplayValue(SIX_FILLED.gakuchika)

    await user.type(screen.getByLabelText('就活軸'), '裁量,技術力')
    await user.click(screen.getByRole('button', { name: '保存' }))

    await waitFor(() => expect(put).toHaveBeenCalledTimes(1))
    expect(put.mock.calls[0][0]).toEqual({ ...SIX_FILLED, job_axis: '裁量,技術力' })
  })

  it('保存後にリロードしても内容が残っている', async () => {
    const user = userEvent.setup()
    const { store } = mockServer(SIX_FILLED)
    const first = renderPage()
    await screen.findByDisplayValue(SIX_FILLED.gakuchika)

    await user.type(screen.getByLabelText('志望動機テンプレ'), '貴社の')
    await user.click(screen.getByRole('button', { name: '保存' }))
    await waitFor(() => expect(store.current.motivation_template).toBe('貴社の'))

    // リロード相当：アンマウントして、キャッシュを持たない新しいクライアントで描き直す
    first.unmount()
    renderPage()

    expect(await screen.findByDisplayValue('貴社の')).toBeInTheDocument()
  })

  it('取得が終わるまで textarea は編集できない（取得済みの内容を空で上書きしないため）', () => {
    // fetch を解決させないことで「取得中」を再現する
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>(() => {})))
    renderPage()

    expect(screen.getByLabelText('ガクチカ')).toBeDisabled()
    expect(screen.getByRole('button', { name: '保存' })).toBeDisabled()
  })

  it('保存に失敗したらエラー内容を画面に出す', async () => {
    const user = userEvent.setup()
    vi.stubGlobal(
      'fetch',
      vi.fn(async (_url: string, init?: RequestInit) => {
        if (init?.method === 'PUT') {
          return new Response(JSON.stringify({ detail: 'ガクチカ は8000文字以内で入力してください' }), {
            status: 422,
            headers: { 'Content-Type': 'application/json' },
          })
        }
        return new Response(JSON.stringify({ ...EMPTY_PROFILE, completeness: 0 }), { status: 200 })
      }),
    )
    renderPage()
    await waitFor(() => expect(screen.getByLabelText('ガクチカ')).toBeEnabled())

    await user.click(screen.getByRole('button', { name: '保存' }))

    expect(await screen.findByText(/ガクチカ は8000文字以内で入力してください/)).toBeInTheDocument()
  })
})

describe('コピーボタン', () => {
  // ラベルが2秒後に戻ることは CopyButton 単体（components/CopyButton.test.tsx）で検証する。
  // ここでは「画面の各項目の本文が正しくコピーされるか」だけを見る。
  it('押すとその項目の本文がクリップボードに入り、ラベルが「コピー済」に変わる', async () => {
    const user = userEvent.setup()
    mockServer(SIX_FILLED)
    renderPage()
    await waitFor(() => expect(screen.getByLabelText('ガクチカ')).toBeEnabled())

    await user.click(screen.getByRole('button', { name: 'ガクチカをコピー' }))

    expect(await navigator.clipboard.readText()).toBe(SIX_FILLED.gakuchika)
    expect(screen.getByRole('button', { name: 'ガクチカをコピー' })).toHaveTextContent('コピー済')
  })

  it('コピーするのは押した項目の本文だけ', async () => {
    const user = userEvent.setup()
    mockServer(SIX_FILLED)
    renderPage()
    await waitFor(() => expect(screen.getByLabelText('ガクチカ')).toBeEnabled())

    await user.click(screen.getByRole('button', { name: '自己PRをコピー' }))

    expect(await navigator.clipboard.readText()).toBe(SIX_FILLED.self_pr)
  })

  it('本文が空の項目はコピーできない', async () => {
    mockServer(SIX_FILLED)
    renderPage()
    await waitFor(() => expect(screen.getByLabelText('ガクチカ')).toBeEnabled())

    expect(screen.getByRole('button', { name: '就活軸をコピー' })).toBeDisabled()
  })
})
