/** 受信箱画面の Gmail 連携表示。
 *
 *  バックエンドは fetch をモックする（認可・取得そのものの検証は pytest 側の test_gmail.py）。
 *  ここで見るのは「連携状態がバッジで分かるか」「同期の結果が seed か Gmail か画面で分かるか」。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { InboxPage } from './InboxPage'

const EMAILS = {
  groups: [
    {
      thread_key: '1|一次面接のご案内',
      company_name: 'アルファテック',
      domain: 'alphatech.co.jp',
      subject: '一次面接のご案内',
      count: 1,
      latest_received_at: '2026-07-30T14:20:00',
      category: '重要',
      accounts: ['gmail'],
      has_ai_decided: false,
      emails: [
        {
          id: 1,
          account: 'gmail',
          from_address: 'recruit@alphatech.co.jp',
          from_name: '採用担当',
          subject: '一次面接のご案内',
          body: '',
          received_at: '2026-07-30T14:20:00',
          category: '重要',
          needs_reply: true,
          decided_by: 'rule',
          company_id: 1,
          thread_key: '1|一次面接のご案内',
        },
      ],
    },
  ],
  ai_decided_count: 0,
  needs_reply_count: 1,
  total_count: 1,
}

type SyncBody = { added: number; updated: number; ai_decided: number; source: 'gmail' | 'seed' }

function mockServer(options: { connected: boolean; sync?: SyncBody }) {
  const json = (body: unknown, status = 200) =>
    new Response(JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json' },
    })

  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    // Shell（受信箱バッジ・通知バナー）と右パネルが出すリクエスト
    if (url === '/api/profile') return json({ completeness: 0 })
    if (url === '/api/companies') return json([])
    if (url.startsWith('/api/qa?')) {
      return json({ company_id: 1, source: null, items: [], prepared_rate: 0 })
    }
    if (url === '/api/today') return json({ research_hours: 4.5, free_slots: [] })

    if (url.startsWith('/api/emails')) return json(EMAILS)
    if (url === '/api/gmail/status') {
      return json({
        connected: options.connected,
        configured: true,
        scope: options.connected ? 'https://www.googleapis.com/auth/gmail.metadata' : null,
        expires_at: null,
      })
    }
    if (url === '/api/gmail/auth') return json({ auth_url: 'https://accounts.google.com/o/oauth2/auth?x=1' })
    if (url === '/api/gmail/sync' && init?.method === 'POST') {
      return json(options.sync ?? { added: 0, updated: 0, ai_decided: 0, source: 'seed' })
    }

    throw new Error(`想定外のリクエスト: ${url}`)
  })

  vi.stubGlobal('fetch', fetchMock)
  return { fetchMock }
}

function renderPage(initialPath = '/inbox') {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[initialPath]}>
        <InboxPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

/** jsdom は location.assign が未実装なので差し替える。 */
function stubLocationAssign() {
  const assign = vi.fn()
  Object.defineProperty(window, 'location', {
    configurable: true,
    value: { ...window.location, assign },
  })
  return assign
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('連携状態のバッジ', () => {
  it('未連携なら「Gmail 未連携」が出て、押すと認可画面へ遷移する', async () => {
    mockServer({ connected: false })
    const assign = stubLocationAssign()
    renderPage()

    const badge = await screen.findByText('Gmail 未連携')
    expect(screen.queryByText('Gmail 連携中')).toBeNull()

    await userEvent.click(badge)

    await waitFor(() =>
      expect(assign).toHaveBeenCalledWith('https://accounts.google.com/o/oauth2/auth?x=1'),
    )
  })

  it('連携済みなら「Gmail 連携中」が出る', async () => {
    mockServer({ connected: true })
    renderPage()

    expect(await screen.findByText('Gmail 連携中')).toBeTruthy()
    expect(screen.queryByText('Gmail 未連携')).toBeNull()
  })

  it('認可から戻った直後はトーストで連携完了を伝える', async () => {
    mockServer({ connected: true })
    renderPage('/inbox?connected=1')

    expect(await screen.findByText('Gmail と連携しました')).toBeTruthy()
  })
})

describe('同期', () => {
  it('主要アクションのボタンは「同期」1つだけ（案03のルール）', async () => {
    mockServer({ connected: true })
    const { container } = renderPage()

    await screen.findByText('Gmail 連携中')
    const primaries = container.querySelectorAll('.primary')
    expect(primaries.length).toBe(1)
    expect(primaries[0].textContent).toBe('同期')
  })

  it('Gmail から取り込めたら件数と AI判定数をトーストに出す', async () => {
    mockServer({
      connected: true,
      sync: { added: 3, updated: 1, ai_decided: 2, source: 'gmail' },
    })
    renderPage()

    await userEvent.click(await screen.findByRole('button', { name: '同期' }))

    expect(
      await screen.findByText('Gmail から 追加 3件 / 更新 1件（AI判定 2件）'),
    ).toBeTruthy()
  })

  it('未連携のまま同期しても止まらず、seed のままだと分かる', async () => {
    mockServer({
      connected: false,
      sync: { added: 0, updated: 0, ai_decided: 0, source: 'seed' },
    })
    stubLocationAssign()
    renderPage()

    await userEvent.click(await screen.findByRole('button', { name: '同期' }))

    expect(
      await screen.findByText('Gmail 未連携のため seed のメールを表示しています'),
    ).toBeTruthy()
    // メール一覧は seed のまま表示され続ける（デモが止まらない）
    expect(screen.getByText('一次面接のご案内')).toBeTruthy()
  })
})
