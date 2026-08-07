/** 企業研究メモのマークダウン描画（依存を足さない最小実装）。
 *
 *  ライブラリを入れない理由は2つ。
 *  - CLAUDE.md §C「UI ライブラリ・CDN を入れない」／依存の追加は人の判断
 *  - `dangerouslySetInnerHTML` を使わずに済む（§D「ユーザー入力を innerHTML に入れない」）。
 *    ここは AI と外部ページ由来の文字列を描くので、HTML を組み立てず React 要素だけを返す
 *
 *  対応する記法は services/ai.py が指示している範囲だけ:
 *  `## 見出し` `### 小見出し` `- 箇条書き` `**強調**` `[表示](URL)`。
 *  それ以外（表・画像・コードブロック）は素の文字として出す。
 */

import type { ReactNode } from 'react'

/** 安全に開けるリンクだけを通す（javascript: などを弾く）。 */
function safeHref(url: string): string | null {
  const trimmed = url.trim()
  return /^https?:\/\//i.test(trimmed) ? trimmed : null
}

/** 1行の中の `**強調**` と `[表示](URL)` を React 要素にする。 */
function renderInline(text: string, keyPrefix: string): ReactNode[] {
  const nodes: ReactNode[] = []
  // 強調とリンクを1つの正規表現で拾う（入れ子は扱わない。AI にもその範囲で書かせている）
  const pattern = /\*\*([^*]+)\*\*|\[([^\]]+)\]\(([^)\s]+)\)/g
  let last = 0
  let match: RegExpExecArray | null
  let index = 0

  while ((match = pattern.exec(text)) !== null) {
    if (match.index > last) nodes.push(text.slice(last, match.index))

    if (match[1] !== undefined) {
      nodes.push(<strong key={`${keyPrefix}-b${index}`}>{match[1]}</strong>)
    } else {
      const href = safeHref(match[3] ?? '')
      if (href === null) {
        // 開けない URL はリンクにせず文字として出す（出典を偽装できないようにする）
        nodes.push(match[2])
      } else {
        nodes.push(
          <a key={`${keyPrefix}-a${index}`} href={href} target="_blank" rel="noreferrer noopener">
            {match[2]}
          </a>,
        )
      }
    }
    last = match.index + match[0].length
    index += 1
  }

  if (last < text.length) nodes.push(text.slice(last))
  return nodes
}

type Props = {
  markdown: string
}

export function Markdown({ markdown }: Props) {
  const blocks: ReactNode[] = []
  let listItems: string[] = []

  const flushList = (key: string) => {
    if (listItems.length === 0) return
    blocks.push(
      <ul key={key}>
        {listItems.map((item, i) => (
          <li key={`${key}-${i}`}>{renderInline(item, `${key}-${i}`)}</li>
        ))}
      </ul>,
    )
    listItems = []
  }

  markdown.split('\n').forEach((raw, i) => {
    const line = raw.trimEnd()
    const key = `md-${i}`

    if (line.trim() === '') {
      flushList(`${key}-ul`)
      return
    }
    if (line.startsWith('### ')) {
      flushList(`${key}-ul`)
      blocks.push(<h4 key={key}>{renderInline(line.slice(4), key)}</h4>)
      return
    }
    if (line.startsWith('## ')) {
      flushList(`${key}-ul`)
      blocks.push(<h3 key={key}>{renderInline(line.slice(3), key)}</h3>)
      return
    }
    if (line.startsWith('# ')) {
      flushList(`${key}-ul`)
      blocks.push(<h3 key={key}>{renderInline(line.slice(2), key)}</h3>)
      return
    }
    if (/^[-*] /.test(line.trimStart())) {
      listItems.push(line.trimStart().slice(2))
      return
    }

    flushList(`${key}-ul`)
    blocks.push(<p key={key}>{renderInline(line, key)}</p>)
  })

  flushList('md-tail-ul')

  return <div className="md">{blocks}</div>
}
