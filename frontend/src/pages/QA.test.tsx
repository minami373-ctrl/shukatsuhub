/** 想定問答画面（spec.md §7「想定問答の生成と入れ替え」「フォールバック」「回答の編集と保存」「準備率の算出」）。
 *
 *  バックエンドは fetch をモックして代替する（API 自体の検証は pytest 側の test_qa.py）。
 *  AI が生成した文章の内容は期待値にしない（§3「AI 部分のテスト方針」）。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { QAItem, QASheet, QASource } from '../lib/qa'
import { QAPage } from './QA'

const COMPANIES = [
  { id: 1, name: 'アルファテック', tags: 'IT' },
  { id: 2, name: 'ベータ社', tags: '' },
]

const CATEGORIES = ['志望動機', 'ガクチカ', '逆質問'] as const

function makeItems(count: number, companyId: number, source: QASource): QAItem[] {
  return Array.from({ length: count }, (_, i) => ({
    id: companyId * 100 + i,
    company_id: companyId,
    question: `質問${i}`,
    answer_draft: `回答骨子${i}`,
    category: CATEGORIES[i % CATEGORIES.length],
    is_prepared: false,
    source,
    generated_at: '2026-07-30T12:20:00',
  }))
}

function rateOf(items: QAItem[]): number {
  if (items.length === 0) return 0
  return Math.round((items.filter((i) => i.is_prepared).length / items.length) * 100)
}

type ServerOptions = {
  /** 生成時に何件返すか */
  generated?: number
  /** 生成元。認証情報未設定なら template */
  source?: QASource
  /** 生成が 422 になる（プロフィールが全項目空） */
  generateError?: string
  /** 最初から生成済みの状態にする */
  initial?: Record<number, QAItem[]>
}

/** 企業ごとの想定問答を保持する、最小の fetch モック。 */
function mockServer(options: ServerOptions = {}) {
  const { generated = 6, source = 'ai', generateError, initial = {} } = options
  const store: Record<number, QAItem[]> = { ...initial }
  const generateCalls: number[] = []
  const patches: { id: number; answer_draft: string }[] = []

  const json = (body: unknown, status = 200) =>
    new Response(JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json' },
    })

  const sheetOf = (companyId: number): QASheet => {
    const items = store[companyId] ?? []
    return {
      company_id: companyId,
      source: items.length > 0 ? items[0].source : null,
      items,
      prepared_rate: rateOf(items),
    }
  }

  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === '/api/companies') return json(COMPANIES)

    // 研究にあてられる時間はヒーローの指標に出すだけ（算出の検証は pytest 側）
    if (url === '/api/today') return json({ research_hours: 4.5 })

    if (url === '/api/qa/generate') {
      const { company_id: companyId } = JSON.parse(String(init?.body)) as { company_id: number }
      generateCalls.push(companyId)
      if (generateError) return json({ detail: generateError }, 422)
      // 既存を削除して入れ替える（件数が増えないこと）
      store[companyId] = makeItems(generated, companyId, source)
      return json(sheetOf(companyId))
    }

    if (url.startsWith('/api/qa?')) {
      const companyId = Number(new URL(url, 'http://localhost').searchParams.get('company_id'))
      return json(sheetOf(companyId))
    }

    const patched = /^\/api\/qa\/(\d+)$/.exec(url)
    if (patched && init?.method === 'PATCH') {
      const id = Number(patched[1])
      const { answer_draft: answerDraft } = JSON.parse(String(init.body)) as {
        answer_draft: string
      }
      patches.push({ id, answer_draft: answerDraft })
      if (answerDraft.trim() === '') return json({ detail: '回答を入力してください' }, 422)
      for (const items of Object.values(store)) {
        const hit = items.find((item) => item.id === id)
        if (hit) {
          // 保存すると準備済みになる（§4.5）
          hit.answer_draft = answerDraft
          hit.is_prepared = true
          return json(hit)
        }
      }
      return json({ detail: '想定問答が見つかりません' }, 404)
    }

    throw new Error(`想定外のリクエスト: ${url}`)
  })

  vi.stubGlobal('fetch', fetchMock)
  return { store, generateCalls, patches, fetchMock }
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  })
  // ヒーローの「← 今日」は react-router の Link なので Router 内で描画する
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <QAPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const generateButton = () => screen.getByRole('button', { name: '想定問答を生成' })
const saveButton = () => screen.getByRole('button', { name: '回答を保存' })
const answerBox = () => screen.getByLabelText('回答骨子')

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('生成と入れ替え', () => {
  it('生成すると想定質問が全件並び、見出し右に AI生成 が出る', async () => {
    const user = userEvent.setup()
    mockServer({ generated: 6, source: 'ai' })
    renderPage()

    await user.click(await screen.findByRole('button', { name: '想定問答を生成' }))

    expect(await screen.findByText('AI生成')).toBeInTheDocument()
    // 件数で切らない（＋他N件を使わない。§4.5 の 2026-08-03 改訂）
    for (let i = 0; i < 6; i++) {
      expect(screen.getByText(`質問${i}`)).toBeInTheDocument()
    }
    expect(screen.queryByRole('button', { name: /＋ 他/ })).not.toBeInTheDocument()
  })

  it('同じ企業で2回生成しても 12問にならず 6問のまま', async () => {
    const user = userEvent.setup()
    const { store } = mockServer({ generated: 6 })
    renderPage()

    await user.click(await screen.findByRole('button', { name: '想定問答を生成' }))
    await screen.findByText('質問0')
    await user.click(generateButton())

    await waitFor(() => expect(store[1]).toHaveLength(6))
    // 「6問」はヒーローの指標（想定質問／未準備）にも出るので、1文で件数を確かめる
    expect(
      await screen.findByText('アルファテック の想定問答は 6問。未準備は 6問です。'),
    ).toBeInTheDocument()
  })

  it('生成中はボタンを「生成中…」にして二重押しを防ぐ', async () => {
    const user = userEvent.setup()
    let release: (() => void) | null = null
    const gate = new Promise<void>((resolve) => {
      release = resolve
    })
    const server = mockServer({ generated: 6 })
    const original = server.fetchMock.getMockImplementation()
    // 生成リクエストが「届いた回数」をここで数える（gate の手前で数えないと0件になる）
    const attempts: number[] = []
    server.fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (url === '/api/qa/generate') {
        attempts.push(attempts.length)
        await gate
      }
      return original!(url, init)
    })
    renderPage()

    await user.click(await screen.findByRole('button', { name: '想定問答を生成' }))

    const pending = await screen.findByRole('button', { name: '生成中…' })
    expect(pending).toBeDisabled()
    await user.click(pending)
    expect(attempts).toHaveLength(1)

    release!()
    await screen.findByText('質問0')
  })

  it('企業を切り替えるとその企業の想定問答に入れ替わる', async () => {
    const user = userEvent.setup()
    mockServer({ initial: { 1: makeItems(6, 1, 'ai') } })
    renderPage()
    await screen.findByText('質問0')
    expect(screen.getByText(/アルファテック の想定問答は 6問/)).toBeInTheDocument()

    await user.selectOptions(screen.getByLabelText('企業'), '2')

    expect(
      await screen.findByText('想定問答はまだありません。企業を選んで生成してください。'),
    ).toBeInTheDocument()
  })
})

describe('フォールバック', () => {
  it('認証情報未設定でテンプレになったときは「テンプレ（APIキー未設定）」と出す', async () => {
    const user = userEvent.setup()
    mockServer({ generated: 6, source: 'template' })
    renderPage()

    await user.click(await screen.findByRole('button', { name: '想定問答を生成' }))

    expect(await screen.findByText('テンプレ（APIキー未設定）')).toBeInTheDocument()
    expect(screen.queryByText('AI生成')).not.toBeInTheDocument()
  })

  it('プロフィールが全項目空なら 422 の理由をそのまま画面に出す', async () => {
    const user = userEvent.setup()
    mockServer({ generateError: 'プロフィールを1項目以上入力してください' })
    renderPage()

    await user.click(await screen.findByRole('button', { name: '想定問答を生成' }))

    expect(await screen.findByText(/プロフィールを1項目以上入力してください/)).toBeInTheDocument()
    expect(
      screen.getByText('想定問答はまだありません。企業を選んで生成してください。'),
    ).toBeInTheDocument()
  })
})

describe('回答の編集と保存', () => {
  it('チェックボックスは置かない（完了は保存で決まる）', async () => {
    mockServer({ initial: { 1: makeItems(6, 1, 'ai') } })
    renderPage()
    await screen.findByText('質問0')

    expect(screen.queryByRole('button', { name: /準備済みにする/ })).not.toBeInTheDocument()
    expect(document.querySelectorAll('.chk')).toHaveLength(0)
  })

  it('編集して保存すると、その内容が PATCH され準備済みバッジが付く', async () => {
    const user = userEvent.setup()
    const { patches } = mockServer({ initial: { 1: makeItems(6, 1, 'ai') } })
    renderPage()
    await screen.findByDisplayValue('回答骨子0')

    await user.clear(answerBox())
    await user.type(answerBox(), '研究室で実験系を立ち上げた話をする')
    await user.click(saveButton())

    await waitFor(() => expect(patches).toHaveLength(1))
    expect(patches[0]).toEqual({ id: 100, answer_draft: '研究室で実験系を立ち上げた話をする' })
    expect(await screen.findByText('準備済み')).toBeInTheDocument()
  })

  it('保存後にリロードしても編集内容が残っている', async () => {
    const user = userEvent.setup()
    mockServer({ initial: { 1: makeItems(6, 1, 'ai') } })
    const first = renderPage()
    await screen.findByDisplayValue('回答骨子0')

    await user.clear(answerBox())
    await user.type(answerBox(), '自分の言葉に直した回答')
    await user.click(saveButton())
    await screen.findByText('保存しました')

    // リロード相当：アンマウントして、キャッシュを持たない新しいクライアントで描き直す
    first.unmount()
    renderPage()

    expect(await screen.findByDisplayValue('自分の言葉に直した回答')).toBeInTheDocument()
  })

  it('空欄では保存できない（ボタンが disabled）', async () => {
    const user = userEvent.setup()
    const { patches } = mockServer({ initial: { 1: makeItems(6, 1, 'ai') } })
    renderPage()
    await screen.findByDisplayValue('回答骨子0')

    await user.clear(answerBox())
    expect(saveButton()).toBeDisabled()

    await user.type(answerBox(), '   ')
    expect(saveButton()).toBeDisabled()
    expect(patches).toHaveLength(0)
  })

  it('質問を押すと骨子が差し替わる（画面遷移はしない）', async () => {
    const user = userEvent.setup()
    mockServer({ initial: { 1: makeItems(6, 1, 'ai') } })
    renderPage()
    await screen.findByDisplayValue('回答骨子0')

    await user.click(screen.getByRole('button', { name: '質問2' }))

    expect(await screen.findByDisplayValue('回答骨子2')).toBeInTheDocument()
  })

  it('未保存の編集があるまま生成を押すと確認し、キャンセルなら生成しない', async () => {
    const user = userEvent.setup()
    const { generateCalls } = mockServer({ initial: { 1: makeItems(6, 1, 'ai') } })
    renderPage()
    await screen.findByDisplayValue('回答骨子0')

    await user.type(answerBox(), '書きかけ')
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false)
    await user.click(generateButton())

    expect(confirmSpy).toHaveBeenCalledTimes(1)
    expect(generateCalls).toHaveLength(0)
    expect(screen.getByDisplayValue('回答骨子0書きかけ')).toBeInTheDocument()
  })

  it('生成を許可したら、編集中の下書きを次の一覧に持ち込まない', async () => {
    // 持ち込むと別の質問に古い回答が紐づいて見え、保存で上書きしてしまう
    const user = userEvent.setup()
    mockServer({ initial: { 1: makeItems(6, 1, 'ai') }, generated: 6 })
    renderPage()
    await screen.findByDisplayValue('回答骨子0')

    await user.type(answerBox(), '捨てられるべき下書き')
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    await user.click(generateButton())

    // 生成後は新しい先頭 QA の本文が出る（古い下書きは残らない）
    await waitFor(() => expect(answerBox()).toHaveValue('回答骨子0'))
    expect(screen.queryByDisplayValue(/捨てられるべき下書き/)).not.toBeInTheDocument()
  })

  it('未保存の編集があるまま別の質問を押すと確認する（キャンセルなら切り替えない）', async () => {
    const user = userEvent.setup()
    mockServer({ initial: { 1: makeItems(6, 1, 'ai') } })
    renderPage()
    await screen.findByDisplayValue('回答骨子0')

    await user.type(answerBox(), '書きかけ')
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false)
    await user.click(screen.getByRole('button', { name: '質問2' }))

    expect(confirmSpy).toHaveBeenCalledTimes(1)
    expect(screen.getByDisplayValue('回答骨子0書きかけ')).toBeInTheDocument()
  })
})

describe('準備率の算出', () => {
  it('6問のうち2問の回答を保存すると準備率 33%・未準備 4問になる', async () => {
    const user = userEvent.setup()
    mockServer({ initial: { 1: makeItems(6, 1, 'ai') } })
    renderPage()
    await screen.findByDisplayValue('回答骨子0')
    expect(screen.getByText('0%')).toBeInTheDocument()

    await user.type(answerBox(), '追記1')
    await user.click(saveButton())
    await waitFor(() => expect(screen.getByText('17%')).toBeInTheDocument())

    await user.click(screen.getByRole('button', { name: '質問1' }))
    await screen.findByDisplayValue('回答骨子1')
    await user.type(answerBox(), '追記2')
    await user.click(saveButton())

    await waitFor(() => expect(screen.getByText('33%')).toBeInTheDocument())
    expect(screen.getByText('4問')).toBeInTheDocument()
    expect(screen.getByText(/準備率 33%（2 \/ 6問）/)).toBeInTheDocument()
  })
})

describe('長い質問文', () => {
  /** 幅に収まらない長さの質問を混ぜた一覧。AI 生成だとこの長さになる */
  const LONG = 'チームで成果を出した経験と、そのときの自分の役割、周囲をどう巻き込んだかを教えてください。'
  const SHORT = 'なぜ当社を志望したのですか。'

  function longItems(): QAItem[] {
    const items = makeItems(2, 1, 'ai')
    items[0].question = SHORT
    items[1].question = LONG
    return items
  }

  it('全行の title に全文が入る（1行に切れていても PC のホバーで読める）', async () => {
    mockServer({ initial: { 1: longItems() } })
    renderPage()
    await screen.findByRole('button', { name: SHORT })

    expect(screen.getByRole('button', { name: LONG })).toHaveAttribute('title', LONG)
    expect(screen.getByRole('button', { name: SHORT })).toHaveAttribute('title', SHORT)
  })

  it('DOM 側では文字を削らない（省略は CSS の責務）', async () => {
    mockServer({ initial: { 1: longItems() } })
    renderPage()

    const row = await screen.findByRole('button', { name: LONG })
    expect(row.textContent).toBe(LONG)
    expect(row.textContent).not.toContain('…')
  })

  it('クリックした行にだけ sel が付く（その行だけ折り返して全文が出る）', async () => {
    const user = userEvent.setup()
    mockServer({ initial: { 1: longItems() } })
    renderPage()
    await screen.findByRole('button', { name: SHORT })

    /** 質問文のボタンを含む .task 行を返す */
    const rowOf = (question: string) =>
      screen.getByRole('button', { name: question }).closest('.task')

    // 未選択のうちは先頭の QA が選ばれている（§4.5）
    expect(rowOf(SHORT)).toHaveClass('sel')
    expect(rowOf(LONG)).not.toHaveClass('sel')

    await user.click(screen.getByRole('button', { name: LONG }))

    // 選択が移り、前の行からは外れる（2行が同時に開かない）
    await waitFor(() => expect(rowOf(LONG)).toHaveClass('sel'))
    expect(rowOf(SHORT)).not.toHaveClass('sel')
  })
})

describe('ヒーローの指標', () => {
  it('研究にあてられる時間を含む4指標を、スマホで残る順に並べる', async () => {
    mockServer({ initial: { 1: makeItems(6, 1, 'ai') } })
    renderPage()
    await screen.findByText('質問0')

    const labels = Array.from(document.querySelectorAll('.hero .sum div span')).map(
      (el) => el.textContent,
    )
    expect(labels).toEqual(['研究にあてられる時間', '準備率', '想定質問', '未準備'])
    expect(screen.getByText('4.5h')).toBeInTheDocument()
  })
})
