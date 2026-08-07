/** マークダウン描画（components/Markdown.tsx）。
 *
 *  AI と外部ページ由来の文字列を描くので、**危険なリンクを通さないこと**を必ず確かめる
 *  （HTML は組み立てず React 要素だけを返す実装。CLAUDE.md §D）。
 */

import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { Markdown } from './Markdown'

describe('Markdown', () => {
  it('見出しと箇条書きを要素にする', () => {
    render(
      <Markdown
        markdown={'## 事業・製品\n- 物流向けの画像認識\n- 顧客は法人のみ\n\n### 補足\n本文の段落。\n'}
      />,
    )

    expect(screen.getByRole('heading', { level: 3, name: '事業・製品' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 4, name: '補足' })).toBeInTheDocument()
    expect(screen.getAllByRole('listitem')).toHaveLength(2)
    expect(screen.getByText('本文の段落。')).toBeInTheDocument()
  })

  it('**強調** を strong にする', () => {
    render(<Markdown markdown={'- 制御ソフトを**内製**している\n'} />)
    expect(screen.getByText('内製').tagName).toBe('STRONG')
  })

  it('http(s) のリンクだけを別タブで開くリンクにする', () => {
    render(<Markdown markdown={'- 事業内容 [出典](https://sios.com/company/)\n'} />)

    const link = screen.getByRole('link', { name: '出典' })
    expect(link).toHaveAttribute('href', 'https://sios.com/company/')
    expect(link).toHaveAttribute('target', '_blank')
    expect(link).toHaveAttribute('rel', 'noreferrer noopener')
  })

  it('javascript: などのリンクはリンクにせず文字として出す', () => {
    render(<Markdown markdown={'- 危ないリンク [クリック](javascript:alert(1))\n'} />)

    expect(screen.queryByRole('link')).not.toBeInTheDocument()
    expect(screen.getByText(/クリック/)).toBeInTheDocument()
  })

  it('生の HTML を書かれても要素にしない（文字として出す）', () => {
    render(<Markdown markdown={'<img src=x onerror="alert(1)">\n'} />)

    expect(document.querySelector('img')).toBeNull()
    expect(screen.getByText('<img src=x onerror="alert(1)">')).toBeInTheDocument()
  })

  it('空文字でも落ちない', () => {
    const { container } = render(<Markdown markdown="" />)
    expect(container.querySelector('.md')).toBeInTheDocument()
  })
})
