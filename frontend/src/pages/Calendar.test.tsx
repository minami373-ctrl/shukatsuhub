/** カレンダー画面（docs/spec.md §4.2）。
 *
 *  バックエンドは fetch をモックする（同期や期間取得そのものの検証は pytest 側）。
 *  ここで見るのは「表示ラベルが 就活 になっているか」と「予定をクリックすると詳細が出るか」。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { ApiEvent } from '../api/eventMap'
import CalendarPage from './Calendar'

const EVENTS: ApiEvent[] = [
  {
    id: 1,
    external_id: 'seed-1',
    // 枠に入りきらない長さ。全文が詳細モーダルで読めることを確かめる
    title: 'アルファテック 一次面接（Zoom・人事1名／技術1名）',
    kind: '選考',
    start_at: '2026-07-30T15:00:00',
    end_at: '2026-07-30T16:00:00',
    location: 'Zoom',
    company_id: 1,
  },
  {
    id: 2,
    external_id: 'seed-2',
    title: '研究室ゼミ',
    kind: '学業',
    start_at: '2026-07-30T10:30:00',
    end_at: '2026-07-30T12:00:00',
    location: 'B棟 402',
    company_id: null,
  },
]

function mockServer() {
  const json = (body: unknown, status = 200) =>
    new Response(JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json' },
    })

  const fetchMock = vi.fn(async (url: string) => {
    // Shell（受信箱バッジ・通知バナー）と右パネルが出すリクエスト
    if (url.startsWith('/api/emails')) return json({ needs_reply_count: 0, total_count: 0 })
    if (url === '/api/profile') return json({ completeness: 0 })
    if (url === '/api/companies') return json([])
    if (url.startsWith('/api/qa?')) {
      return json({ company_id: 1, source: null, items: [], prepared_rate: 0 })
    }
    if (url === '/api/today') return json({ research_hours: 4.5, free_slots: [] })

    if (url.startsWith('/api/events')) return json(EVENTS)

    throw new Error(`想定外のリクエスト: ${url}`)
  })

  vi.stubGlobal('fetch', fetchMock)
  return { fetchMock }
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <CalendarPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

/** カレンダー内の予定（eventContent が出す .cal-ev）を title 属性で探す */
async function eventEl(title: string): Promise<HTMLElement> {
  return await waitFor(() => {
    const hit = document.querySelector(`.cal-ev[title="${title}"]`)
    if (!hit) throw new Error(`予定が描かれていない: ${title}`)
    return hit as HTMLElement
  })
}

beforeEach(() => {
  // Calendar.tsx の基準日はマウント時の実日時から計算するため、モック予定と同じ
  // 2026-07-30 に固定する（実行日によって表示週がずれてテストが不安定にならないように）。
  // Date だけを固定し、setTimeout 等は実タイマーのままにする（waitFor / userEvent が動かなくなるため）。
  vi.useFakeTimers({ toFake: ['Date'] })
  vi.setSystemTime(new Date(2026, 6, 30, 12, 0, 0))
})

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('表示ラベル', () => {
  it('凡例とヒーローの指標が「就活」になっている（「選考」と出さない）', async () => {
    mockServer()
    renderPage()

    const legend = await waitFor(() => {
      const hit = document.querySelector('.legend')
      if (!hit) throw new Error('凡例が無い')
      return hit as HTMLElement
    })
    expect(within(legend).getByText('就活')).toBeInTheDocument()
    expect(within(legend).getByText('学業')).toBeInTheDocument()
    expect(within(legend).queryByText('選考')).not.toBeInTheDocument()

    expect(await screen.findByText('表示中の就活')).toBeInTheDocument()
    expect(screen.queryByText('表示中の選考')).not.toBeInTheDocument()
  })
})

describe('予定の詳細モーダル', () => {
  it('予定をクリックすると予定名の全文・種別・日時・場所が出て、閉じるで消える', async () => {
    mockServer()
    renderPage()

    // 開く前はモーダルが無い
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()

    await userEvent.click(await eventEl('アルファテック 一次面接（Zoom・人事1名／技術1名）'))

    const dlg = await screen.findByRole('dialog')
    expect(within(dlg).getByText('アルファテック 一次面接（Zoom・人事1名／技術1名）')).toBeInTheDocument()
    expect(within(dlg).getByText('就活')).toBeInTheDocument()
    expect(within(dlg).getByText('7/30（木）15:00〜16:00')).toBeInTheDocument()
    expect(within(dlg).getByText('Zoom')).toBeInTheDocument()

    await userEvent.click(within(dlg).getByRole('button', { name: '閉じる' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })

  it('学業の予定は種別が「学業」になる', async () => {
    mockServer()
    renderPage()

    await userEvent.click(await eventEl('研究室ゼミ'))

    const dlg = await screen.findByRole('dialog')
    expect(within(dlg).getByText('学業')).toBeInTheDocument()
    expect(within(dlg).getByText('B棟 402')).toBeInTheDocument()
    expect(within(dlg).getByText('7/30（木）10:30〜12:00')).toBeInTheDocument()
  })
})
