/** 予定の詳細モーダル（docs/spec.md §4.2）。
 *
 *  カレンダーの枠は狭く予定名が2行で省略されるため、全文と場所をここで確認する。
 *  **読み取り専用**。編集はしない（仕様で対象外）。
 *  ネイティブの <dialog> を使う形は TaskDialog / CompanyDialog と同じ。
 */

import { useEffect, useRef } from 'react'

import { type ApiEvent, KIND_LABEL, formatEventRange } from '../api/eventMap'

type Props = {
  /** null なら閉じる。開くときは表示する予定を渡す */
  event: ApiEvent | null
  onClose: () => void
}

export function EventDialog({ event, onClose }: Props) {
  const ref = useRef<HTMLDialogElement>(null)

  useEffect(() => {
    if (event === null) {
      ref.current?.close()
      return
    }
    if (!ref.current?.open) ref.current?.showModal()
  }, [event])

  return (
    <dialog className="dlg" ref={ref} onCancel={onClose} aria-label="予定の詳細">
      {/* method="dialog" にすると Enter でも閉じる。閉じる以外の操作は持たせない */}
      <form
        method="dialog"
        onSubmit={(e) => {
          e.preventDefault()
          onClose()
        }}
      >
        <h2>▣ 予定の詳細</h2>

        {event && (
          <dl className="dlg-def">
            <dt>予定名</dt>
            <dd>{event.title}</dd>

            <dt>種別</dt>
            <dd>
              <span className={event.kind === '学業' ? 'tag cls' : 'tag'}>
                {KIND_LABEL[event.kind]}
              </span>
            </dd>

            <dt>日時</dt>
            <dd>{formatEventRange(event.start_at, event.end_at)}</dd>

            <dt>場所</dt>
            <dd>{event.location ?? '—'}</dd>
          </dl>
        )}

        <div className="dlg-act">
          <button className="primary" type="submit">
            閉じる
          </button>
        </div>
      </form>
    </dialog>
  )
}
