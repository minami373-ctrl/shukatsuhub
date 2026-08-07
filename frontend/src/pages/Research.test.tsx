/** 企業研究の情報収集画面（パスは /interview）。
 *
 *  バックエンドは fetch をモックして代替する（API 自体の検証は pytest 側の test_research.py）。
 *  AI が書いた文章の内容は期待値にしない（docs/spec.md §3「AI 部分のテスト方針」）。
 *  ここで見るのは「企業の切り替え」「マークダウンと出典の表示」「収集ボタン」「確認観点」。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { ResearchCheck, ResearchCompany, ResearchReport } from '../api/research'
import ResearchPage from './Research'

const MARKDOWN =
  '## 事業・製品\n- 物流向けの**画像認識** [出典](https://alphatech.co.jp/company/)\n\n## 求める人材\n- 課題設定できる人\n'

type ServerOptions = {
  /** collect が返す由来 */
  collectSource?: 'web' | 'ai' | 'template'
}

function mockServer(options: ServerOptions = {}) {
  const { collectSource = 'web' } = options

  const companies: ResearchCompany[] = [
    {
      id: 1,
      name: 'アルファテック',
      domain: 'alphatech.co.jp',
      collected_at: '2026-08-05T10:42:00',
      source: 'seed',
      unchecked: 1,
    },
    {
      id: 5,
      name: 'サイオステクノロジー株式会社',
      domain: 'sios.com',
      collected_at: null,
      source: null,
      unchecked: 0,
    },
  ]
  const reports: Record<number, ResearchReport> = {
    1: {
      company_id: 1,
      markdown: MARKDOWN,
      source_urls: ['https://alphatech.co.jp/company/'],
      source: 'seed',
      collected_at: '2026-08-05T10:42:00',
    },
  }
  const checks: Record<number, ResearchCheck[]> = {
    1: [
      { id: 11, company_id: 1, label: '事業の柱を3つ言えるようにする', is_done: true, source: 'seed' },
      { id: 12, company_id: 1, label: '強みの重なりを1文にする', is_done: false, source: 'seed' },
    ],
    5: [],
  }
  const collectCalls: number[] = []

  const json = (body: unknown, status = 200) =>
    new Response(JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json' },
    })

  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    // Shell（受信箱バッジ・通知バナー）と右パネルが出すリクエスト
    if (url.startsWith('/api/emails')) return json({ needs_reply_count: 0, total_count: 0 })
    if (url === '/api/profile') return json({ completeness: 0 })
    if (url === '/api/companies') return json(companies.map((c) => ({ id: c.id, name: c.name, tags: '' })))
    if (url.startsWith('/api/qa?')) return json({ company_id: 1, source: null, items: [], prepared_rate: 0 })
    // 研究にあてられる時間はヒーローの指標に出すだけ（算出の検証は pytest 側）
    if (url === '/api/today') return json({ research_hours: 4.5, free_slots: [] })

    if (url === '/api/research/companies') return json(companies)

    if (url.startsWith('/api/research?')) {
      const companyId = Number(new URL(url, 'http://localhost').searchParams.get('company_id'))
      const companyChecks = checks[companyId] ?? []
      return json({
        company_id: companyId,
        company_name: companies.find((c) => c.id === companyId)?.name ?? '',
        report: reports[companyId] ?? null,
        checks: companyChecks,
        unchecked: companyChecks.filter((c) => !c.is_done).length,
      })
    }

    if (url === '/api/research/collect' && init?.method === 'POST') {
      const { company_id: companyId } = JSON.parse(String(init.body)) as { company_id: number }
      collectCalls.push(companyId)
      const collectedAt = '2026-08-05T11:30:00'
      const fetched =
        collectSource === 'web'
          ? [
              { url: 'https://sios.com/', status: 'ok' as const, message: null },
              { url: 'https://sios.com/company/', status: 'ok' as const, message: null },
            ]
          : collectSource === 'ai'
            ? [
                {
                  url: 'https://sios.com/',
                  status: 'robots_denied' as const,
                  message: 'robots.txt がこのページの取得を許可していません',
                },
              ]
            : []
      reports[companyId] = {
        company_id: companyId,
        markdown: '## 事業・製品\n- 収集でできたメモ\n',
        source_urls: fetched.filter((f) => f.status === 'ok').map((f) => f.url),
        source: collectSource,
        collected_at: collectedAt,
      }
      checks[companyId] = [
        { id: 90, company_id: companyId, label: '事業の柱を3つ言えるようにする', is_done: false, source: collectSource },
      ]
      const row = companies.find((c) => c.id === companyId)
      if (row) {
        row.collected_at = collectedAt
        row.source = collectSource
        row.unchecked = 1
      }
      return json({
        company_id: companyId,
        source: collectSource,
        report: reports[companyId],
        checks: checks[companyId],
        fetched,
      })
    }

    const check = /^\/api\/research\/checks\/(\d+)$/.exec(url)
    if (check && init?.method === 'PATCH') {
      const hit = Object.values(checks)
        .flat()
        .find((c) => c.id === Number(check[1]))
      if (!hit) return json({ detail: '確認観点が見つかりません' }, 404)
      hit.is_done = (JSON.parse(String(init.body)) as { is_done: boolean }).is_done
      return json(hit)
    }

    throw new Error(`想定外のリクエスト: ${url}`)
  })

  vi.stubGlobal('fetch', fetchMock)
  return { companies, reports, checks, collectCalls, fetchMock }
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <ResearchPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const collectButton = () => screen.getByRole('button', { name: 'AI で情報を集める' })
/** メモ本文のカード（見出しに企業名が入る） */
const reportCard = () => screen.getByText('物流向けの', { exact: false }).closest('.card') as HTMLElement

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('企業一覧と本文', () => {
  it('先頭の企業のメモをマークダウンで描き、出典リンクを出す', async () => {
    mockServer()
    renderPage()

    // 見出しと強調がマークダウンとして描かれる（タブは無い）
    expect(await screen.findByRole('heading', { level: 3, name: '事業・製品' })).toBeInTheDocument()
    expect(screen.getByText('画像認識').tagName).toBe('STRONG')
    expect(screen.queryByRole('button', { name: '働き方・制度' })).not.toBeInTheDocument()

    // 出典は本文中と出典リストの2か所（どちらも企業ドメイン）
    const card = reportCard()
    expect(within(card).getByRole('link', { name: '出典' })).toHaveAttribute(
      'href',
      'https://alphatech.co.jp/company/',
    )
    expect(within(card).getByRole('link', { name: 'alphatech.co.jp/company/' })).toBeInTheDocument()
  })

  it('企業一覧に収集済み・未収集が出る', async () => {
    mockServer()
    renderPage()

    const alpha = (await screen.findByText('アルファテック')).closest('.task') as HTMLElement
    expect(within(alpha).getByText('8/5 10:42 収集')).toBeInTheDocument()
    expect(within(alpha).getByText('未確認 1')).toBeInTheDocument()

    const sios = screen.getByText('サイオステクノロジー株式会社').closest('.task') as HTMLElement
    expect(within(sios).getByText('sios.com・未収集')).toBeInTheDocument()
  })

  it('企業をクリックすると本文が入れ替わる', async () => {
    const user = userEvent.setup()
    mockServer()
    renderPage()

    await screen.findByText('アルファテック')
    await user.click(screen.getByText('サイオステクノロジー株式会社'))

    expect(
      await screen.findByText(
        'サイオステクノロジー株式会社 はまだ調べていません。「AI で情報を集める」を押してください。',
      ),
    ).toBeInTheDocument()
    expect(screen.getByText(/まだ調べていません。「AI で情報を集める」を押すと/)).toBeInTheDocument()
  })
})

describe('AI で情報を集める', () => {
  it('選んだ企業で収集され、読めたページ数が出る', async () => {
    const user = userEvent.setup()
    const { collectCalls } = mockServer({ collectSource: 'web' })
    renderPage()

    await screen.findByText('サイオステクノロジー株式会社')
    await user.click(screen.getByText('サイオステクノロジー株式会社'))
    await user.click(collectButton())

    await waitFor(() => expect(collectCalls).toEqual([5]))
    expect(await screen.findByText('公開ページ 2件を読んでまとめました。')).toBeInTheDocument()
    expect(await screen.findByText('収集でできたメモ')).toBeInTheDocument()
  })

  it('robots で読めなかったときは理由を出し、本文は使っていないと断る', async () => {
    const user = userEvent.setup()
    mockServer({ collectSource: 'ai' })
    renderPage()

    await screen.findByText('サイオステクノロジー株式会社')
    await user.click(screen.getByText('サイオステクノロジー株式会社'))
    await user.click(collectButton())

    expect(await screen.findByText(/robots.txt が許可していない/)).toBeInTheDocument()
    expect(
      await screen.findByText(/公開ページの本文は使っていません。事実は自分で確かめてください。/),
    ).toBeInTheDocument()
  })

  it('AI が使えないときはテンプレだと明示する', async () => {
    const user = userEvent.setup()
    mockServer({ collectSource: 'template' })
    renderPage()

    await screen.findByText('サイオステクノロジー株式会社')
    await user.click(screen.getByText('サイオステクノロジー株式会社'))
    await user.click(collectButton())

    expect(await screen.findByText(/AZURE_OPENAI_API_KEY 未設定/)).toBeInTheDocument()
  })

  it('収集中はボタンを「収集中…」にして二重押しを防ぐ', async () => {
    const user = userEvent.setup()
    // オブジェクトに入れて渡す（let だと TypeScript が null のまま推論して呼び出せない）
    const gate: { release?: () => void } = {}
    const { fetchMock } = mockServer()
    const original = fetchMock.getMockImplementation() as (
      url: string,
      init?: RequestInit,
    ) => Promise<Response>
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (url === '/api/research/collect') {
        await new Promise<void>((resolve) => {
          gate.release = resolve
        })
      }
      return original(url, init)
    })

    renderPage()
    await screen.findByText('アルファテック')
    await user.click(collectButton())

    expect(await screen.findByRole('button', { name: '収集中…' })).toBeDisabled()
    gate.release?.()
  })
})

describe('確認観点', () => {
  it('チェックを付けると PATCH され、残り点数が減る', async () => {
    const user = userEvent.setup()
    const { checks } = mockServer()
    renderPage()

    await user.click(
      await screen.findByRole('button', { name: '強みの重なりを1文にする を確認済みにする' }),
    )

    await waitFor(() => expect(checks[1].find((c) => c.id === 12)?.is_done).toBe(true))
    expect(await screen.findByText('2/2 点')).toBeInTheDocument()
  })

  it('未収集の企業では観点が空だと案内する', async () => {
    const user = userEvent.setup()
    mockServer()
    renderPage()

    await screen.findByText('サイオステクノロジー株式会社')
    await user.click(screen.getByText('サイオステクノロジー株式会社'))

    expect(
      await screen.findByText('収集すると、確認すべき観点がここに並びます。'),
    ).toBeInTheDocument()
  })
})
