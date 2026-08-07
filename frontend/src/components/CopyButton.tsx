/** 項目本文をクリップボードへコピーするボタン（spec.md §4.4）。
 *  押すとラベルが2秒間「コピー済」に変わる。 */

import { useEffect, useRef, useState } from 'react'

const RESET_MS = 2000

type State = 'idle' | 'copied' | 'failed'

const LABEL: Record<State, string> = {
  idle: 'コピー',
  copied: 'コピー済',
  failed: 'コピー失敗',
}

type Props = {
  /** コピーする本文 */
  text: string
  /** スクリーンリーダー用にどの項目かを添える */
  fieldLabel: string
}

export function CopyButton({ text, fieldLabel }: Props) {
  const [state, setState] = useState<State>('idle')
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // アンマウント後に setState しないようタイマーを片付ける
  useEffect(() => {
    return () => {
      if (timerRef.current !== null) clearTimeout(timerRef.current)
    }
  }, [])

  async function handleClick() {
    if (timerRef.current !== null) clearTimeout(timerRef.current)
    try {
      await navigator.clipboard.writeText(text)
      setState('copied')
    } catch {
      // 非セキュアコンテキストや権限拒否のとき。黙って成功に見せない
      setState('failed')
    }
    timerRef.current = setTimeout(() => setState('idle'), RESET_MS)
  }

  return (
    <button
      type="button"
      className={state === 'copied' ? 'mini done' : 'mini'}
      onClick={handleClick}
      disabled={text === ''}
      aria-label={`${fieldLabel}をコピー`}
    >
      {LABEL[state]}
    </button>
  )
}
