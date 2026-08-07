/** タスクの追加・変更フォーム（`03-today-focus/FEATURE_PAGE_SPECS.md` §6）。
 *
 *  ネイティブの <dialog> を使う。理由は2つ。
 *  - `.content` が2行グリッド（ヒーロー ＋ 本体）で固定なので、ページの行を増やせない
 *  - 開閉が要素の属性1つで済み、状態管理ライブラリを足さずに書ける（DESIGN_RULES R5 と同じ考え）
 *
 *  入れる項目は内容・期限（日付＋時刻）・見積り時間・重要度・タグ。
 *  見積り時間は空き時間の算出に直接効く（docs/spec.md §5.3）ので入力できるようにする。
 *  ただし既定 30 分を入れておき、触らなくても登録できるようにする。
 *
 *  重要度（priority）とタグ（badge）は別の軸。priority は度合い（高/中/低）、
 *  badge は行動の種類（要返信・準備）。1つの選択肢にまとめると意味が通らなくなる。
 */

import { useEffect, useRef, useState } from 'react'

import { BADGES, PRIORITIES, type Badge, type Priority, type TaskInput } from '../api/tasks'

export type TaskDraft = TaskInput & { id?: number }

type Props = {
  /** null なら閉じている。id を持つ下書きなら「変更」、無ければ「追加」 */
  draft: TaskDraft | null
  saving: boolean
  error: string | null
  onSubmit: (draft: TaskDraft) => void
  onClose: () => void
}

/** ISO 文字列を datetime-local の value（YYYY-MM-DDTHH:MM）に整える。 */
export function toLocalInput(iso: string): string {
  return iso.slice(0, 16)
}

export function TaskDialog({ draft, saving, error, onSubmit, onClose }: Props) {
  const ref = useRef<HTMLDialogElement>(null)
  const [title, setTitle] = useState('')
  const [dueAt, setDueAt] = useState('')
  const [estimate, setEstimate] = useState('30')
  const [priority, setPriority] = useState<Priority>('中')
  const [badge, setBadge] = useState<Badge | ''>('')

  // 開くたびに下書きで初期化する。前回の入力が残っていると別のタスクを上書きしかねない
  useEffect(() => {
    if (draft === null) {
      ref.current?.close()
      return
    }
    setTitle(draft.title)
    setDueAt(toLocalInput(draft.due_at))
    setEstimate(String(draft.estimate_min))
    setPriority(draft.priority)
    setBadge(draft.badge ?? '')
    if (!ref.current?.open) ref.current?.showModal()
  }, [draft])

  const isEdit = draft?.id !== undefined
  const estimateMin = Number(estimate)
  const estimateOk = Number.isInteger(estimateMin) && estimateMin >= 0
  const canSave = title.trim() !== '' && dueAt !== '' && estimateOk && !saving

  return (
    <dialog className="dlg" ref={ref} onCancel={onClose} aria-label={isEdit ? 'タスクを変更' : 'タスクを追加'}>
      <form
        method="dialog"
        onSubmit={(e) => {
          e.preventDefault()
          if (!canSave) return
          onSubmit({
            id: draft?.id,
            title: title.trim(),
            due_at: dueAt,
            estimate_min: estimateMin,
            priority,
            badge: badge || null,
          })
        }}
      >
        <h2>{isEdit ? 'タスクを変更' : 'タスクを追加'}</h2>

        <label>
          内容
          <input
            autoFocus
            maxLength={200}
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="アルファテック ES を提出"
          />
        </label>

        <label>
          期限（日付と時刻）
          <input type="datetime-local" value={dueAt} onChange={(e) => setDueAt(e.target.value)} />
        </label>

        <label>
          見積り時間（分）
          {/* 空き時間 = 可処分時間 − 予定 − 未完了タスクの見積り合計（docs/spec.md §5.3）。
              チェックを付けるとこの分だけ空き時間が増えるので、実際の値を入れられるようにする */}
          <input
            type="number"
            min={0}
            step={15}
            value={estimate}
            onChange={(e) => setEstimate(e.target.value)}
          />
        </label>

        <label>
          重要度
          {/* 度合い。docs/spec.md §6 の priority。必須なので「なし」は置かない */}
          <select value={priority} onChange={(e) => setPriority(e.target.value as Priority)}>
            {PRIORITIES.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        </label>

        <label>
          タグ（任意）
          {/* 行動の種類。docs/spec.md §6 の badge。重要度とは別の軸 */}
          <select value={badge} onChange={(e) => setBadge(e.target.value as Badge | '')}>
            <option value="">なし</option>
            {BADGES.map((b) => (
              <option key={b} value={b}>
                {b}
              </option>
            ))}
          </select>
        </label>

        {error && <p className="toast err">{error}</p>}

        <div className="dlg-act">
          <button className="mini" type="button" onClick={onClose} disabled={saving}>
            キャンセル
          </button>
          <button className="primary" type="submit" disabled={!canSave}>
            {saving ? '保存中…' : '保存'}
          </button>
        </div>
      </form>
    </dialog>
  )
}
