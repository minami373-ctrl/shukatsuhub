/** コピーボタン（spec.md §4.4「ラベルを2秒間 コピー済 に変える」）。
 *  時間の経過を偽タイマーで検証するため、通信を含まない単体で確かめる。
 *  偽タイマー下では userEvent がクリックを解決できないので fireEvent を使う。 */

import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { CopyButton } from './CopyButton'

/** navigator.clipboard は jsdom に無いので差し替える。 */
function stubClipboard(writeText: ReturnType<typeof vi.fn>) {
  vi.stubGlobal('navigator', { clipboard: { writeText } })
}

/** クリック内の await（clipboard.writeText）を消化する。 */
async function flush() {
  await act(async () => {})
}

const button = () => screen.getByRole('button', { name: 'ガクチカをコピー' })

describe('CopyButton', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('押すと本文をクリップボードに書き込む', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    stubClipboard(writeText)
    render(<CopyButton text="ガクチカの本文" fieldLabel="ガクチカ" />)

    fireEvent.click(button())
    await flush()

    expect(writeText).toHaveBeenCalledWith('ガクチカの本文')
  })

  it('ラベルが「コピー済」に変わり、2秒後に「コピー」へ戻る', async () => {
    stubClipboard(vi.fn().mockResolvedValue(undefined))
    render(<CopyButton text="ガクチカの本文" fieldLabel="ガクチカ" />)
    expect(button()).toHaveTextContent('コピー')

    fireEvent.click(button())
    await flush()
    expect(button()).toHaveTextContent('コピー済')

    // 2秒に満たないうちは戻らない
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1900)
    })
    expect(button()).toHaveTextContent('コピー済')

    await act(async () => {
      await vi.advanceTimersByTimeAsync(100)
    })
    expect(button()).toHaveTextContent('コピー')
  })

  it('連続で押しても2秒の計測がやり直される', async () => {
    stubClipboard(vi.fn().mockResolvedValue(undefined))
    render(<CopyButton text="ガクチカの本文" fieldLabel="ガクチカ" />)

    fireEvent.click(button())
    await flush()
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1500)
    })
    fireEvent.click(button())
    await flush()

    // 1回目から2秒経ってもまだ「コピー済」のまま（2回目の押下で測り直している）
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000)
    })
    expect(button()).toHaveTextContent('コピー済')
  })

  it('コピーに失敗したら成功に見せず「コピー失敗」を出す', async () => {
    stubClipboard(vi.fn().mockRejectedValue(new Error('denied')))
    render(<CopyButton text="ガクチカの本文" fieldLabel="ガクチカ" />)

    fireEvent.click(button())
    await flush()

    expect(button()).toHaveTextContent('コピー失敗')
  })

  it('本文が空なら押せない', () => {
    stubClipboard(vi.fn())
    render(<CopyButton text="" fieldLabel="ガクチカ" />)

    expect(button()).toBeDisabled()
  })
})
