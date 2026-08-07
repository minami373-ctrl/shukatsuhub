/** ヒーロー（docs/spec.md §4.0）。全画面に必ず置く。
 *
 *  左に「← 今日」＋ページ名＋そのページで今すぐやるべき1文、右に指標。
 *  指標には必ず「研究にあてられる時間」を含める。
 *  指標は先頭2つがスマホでも残るので、重要な順に並べること（CSS: .sum div:nth-child(n+3)）。
 */

import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'

/** bar を渡すとその指標の直下に 0〜100% の横バーを敷く（プロフィールの充実度）。 */
export type Metric = { label: string; value: string; bar?: number }

type Props = {
  pageName: string
  /** 件数の羅列ではなく、行動や状況を伝える1文にする */
  sentence: string
  metrics: Metric[]
  /** 1文の後ろに出す遷移導線（例: 想定問答 →） */
  next?: ReactNode
  /** 1文の下に出す状態表示（保存しました・エラーなど） */
  status?: ReactNode
  /** 主要アクション。1画面に1つだけ */
  action?: ReactNode
  /** 今日画面自身では戻り導線を出さない */
  showBack?: boolean
}

export function Hero({
  pageName,
  sentence,
  metrics,
  next,
  status,
  action,
  showBack = true,
}: Props) {
  return (
    <section className="hero">
      <div className="lead">
        <div className="d">
          {showBack && (
            <>
              <Link className="back" to="/">
                ← 今日
              </Link>
              <span> ／ </span>
            </>
          )}
          <span>{pageName}</span>
        </div>
        <h1>
          {sentence}
          {next}
        </h1>
        {status}
      </div>
      <div className="sum">
        {metrics.map((m) => (
          <div key={m.label}>
            <span>{m.label}</span>
            <b>{m.value}</b>
            {m.bar !== undefined && (
              <div className="hbar">
                <i style={{ width: `${m.bar}%` }} />
              </div>
            )}
          </div>
        ))}
      </div>
      {action}
    </section>
  )
}
