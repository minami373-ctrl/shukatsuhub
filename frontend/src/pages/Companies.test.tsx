/** 企業の発見・マッチング（`/companies`。`03-today-focus/FEATURE_PAGE_SPECS.md` §12）。
 *
 *  バックエンドは fetch をモックして代替する（マッチ率の算出の検証は pytest 側の test_matching.py）。
 *  ここで見るのは「押したときに何を送るか」と「送った結果どう表示が変わるか」。
 *  純関数の判定（色分け・文言）は src/lib/matching.test.ts 側で見る。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { MatchedCompany } from '../api/matching'
import CompaniesPage from './Companies'

function matched(over: Partial<MatchedCompany> = {}): MatchedCompany {
  return {
    id: 9,
    name: 'ゼータネットワークス',
    domain: 'zeta-networks.jp',
    stage: '気になる',
    is_watched: false,
    job_type: 'インフラエンジニア',
    location: '東京',
    remote_ok: true,
    salary_min: 400,
    holidays_per_year: 122,
    rate: 100,
    reasons: ['勤務地が一致：東京'],
    ...over,
  }
}

function mockServer() {
  // 1社だけ返す。マッチング結果は「いま DB に入っている値」を毎回作り直して返す
  let company = matched()
  const patches: { url: string; body: unknown }[] = []

  const json = (body: unknown, status = 200) =>
    new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    // Shell（受信箱バッジ・通知バナー）と右パネルが出すリクエスト
    if (url.startsWith('/api/emails')) return json({ needs_reply_count: 0, total_count: 0 })
    if (url === '/api/profile') return json({ completeness: 0, job_axis: '成長環境' })
    if (url === '/api/companies') return json([{ id: 9, name: 'ゼータネットワークス', tags: '' }])
    if (url.startsWith('/api/qa?')) return json({ company_id: 9, source: null, items: [], prepared_rate: 0 })
    if (url === '/api/today') return json({ research_hours: 4.5, free_slots: [] })

    if (url === '/api/companies/suggestions') return json({ items: [] })

    if (url === '/api/matching' && init?.method === 'POST') {
      const body = JSON.parse(String(init.body)) as { scope: string }
      const items = body.scope === 'watched' && !company.is_watched ? [] : [company]
      return json({
        source: 'seed',
        axes: ['成長環境'],
        recommended_count: items.length,
        total_count: 1,
        items,
      })
    }

    const patch = /^\/api\/companies\/(\d+)$/.exec(url)
    if (patch && init?.method === 'PATCH') {
      const body = JSON.parse(String(init.body)) as Partial<MatchedCompany>
      patches.push({ url, body })
      company = { ...company, ...body }
      return json(company)
    }

    throw new Error(`想定外のリクエスト: ${url}`)
  })

  vi.stubGlobal('fetch', fetchMock)
  return { patches, current: () => company }
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <CompaniesPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const searchButton = () => screen.getByRole('button', { name: '条件で探す' })

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('気になるに追加', () => {
  it('stage だけでなく is_watched も立てる（登録企業フラグは stage とは別物）', async () => {
    const user = userEvent.setup()
    const server = mockServer()
    renderPage()

    await user.click(searchButton())
    await user.click(await screen.findByRole('button', { name: '＋ 気になるに追加' }))

    await waitFor(() => expect(server.patches).toHaveLength(1))
    expect(server.patches[0].body).toEqual({ stage: '気になる', is_watched: true })
  })

  it('追加すると「登録済み」に変わり、ボタンが消える', async () => {
    const user = userEvent.setup()
    mockServer()
    renderPage()

    await user.click(searchButton())
    await user.click(await screen.findByRole('button', { name: '＋ 気になるに追加' }))

    expect(await screen.findByText('登録済み')).toBeInTheDocument()
    await waitFor(() =>
      expect(screen.queryByRole('button', { name: '＋ 気になるに追加' })).not.toBeInTheDocument(),
    )
  })

  it('追加した企業が「気になる」セグメントに出る', async () => {
    const user = userEvent.setup()
    mockServer()
    renderPage()

    await user.click(searchButton())
    // 追加前は is_watched が false なので「気になる」に出ない
    await user.click(screen.getByRole('button', { name: '気になる' }))
    expect(await screen.findByText('該当する企業はありません。条件をゆるめてみてください。')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'おすすめ' }))
    await user.click(await screen.findByRole('button', { name: '＋ 気になるに追加' }))
    await user.click(screen.getByRole('button', { name: '気になる' }))

    const card = (await screen.findByText('ゼータネットワークス')).closest('.co-card') as HTMLElement
    expect(within(card).getByText('登録済み')).toBeInTheDocument()
  })
})

describe('マッチング条件', () => {
  it('年収・年間休日を条件として送る（空欄は条件に数えない）', async () => {
    const user = userEvent.setup()
    mockServer()
    renderPage()

    await user.type(screen.getByLabelText('希望年収（万円以上）'), '400')
    await user.click(searchButton())

    // 検索が終わってから、実際に送った本文を見る
    expect(await screen.findByText('ゼータネットワークス')).toBeInTheDocument()
    const fetchMock = globalThis.fetch as unknown as ReturnType<typeof vi.fn>
    const matchCall = fetchMock.mock.calls.find(
      ([url, init]) => url === '/api/matching' && init?.method === 'POST',
    )
    // 空欄の年間休日は null＝条件に数えない（0 日以上として送らない）
    expect(JSON.parse(String(matchCall?.[1]?.body))).toMatchObject({
      salary_min: 400,
      holidays_min: null,
    })
  })
})
