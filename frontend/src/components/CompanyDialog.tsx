/** 企業の追加・変更フォーム（`03-today-focus/FEATURE_PAGE_SPECS.md` §7）。
 *
 *  TaskDialog と同じくネイティブの <dialog> を使う（.content が2行グリッドで固定なので
 *  ページの行を増やせない。開閉が属性1つで済む）。
 *
 *  ドメインは追加時だけ入力できる。変更で書き換えるとメールの企業逆引き（services/grouping.py）
 *  の結果が変わり、既存メールの紐づけが黙ってずれるため。
 *
 *  このボードは「その日に動きがある選考」ではなく**すべての選考**を管理する。
 *  自分で登録した企業に期限が付けられないと管理にならないので、追加時に締切を入れられる。
 *  締切は Task として登録される（Company に期限カラムを持たない。docs/spec.md §6 の注記）。
 *  変更ダイアログには出さない ― 登録後の締切はタスク側（/tasks）で編集する。
 */

import { useEffect, useRef, useState } from 'react'

import { STAGES, type CompanyInput, type Stage } from '../api/pipeline'

export type CompanyDraft = CompanyInput & { id?: number }

/** 数値の入力欄を保存する値に直す。空欄・数値でないものは「未登録」（null）にする。 */
function toNumberOrNull(value: string): number | null {
  const trimmed = value.trim()
  if (trimmed === '') return null
  const parsed = Number(trimmed)
  return Number.isFinite(parsed) && parsed >= 0 ? Math.round(parsed) : null
}

type Props = {
  /** null なら閉じている。id を持つ下書きなら「変更」、無ければ「追加」 */
  draft: CompanyDraft | null
  saving: boolean
  error: string | null
  onSubmit: (draft: CompanyDraft) => void
  onClose: () => void
}

export function CompanyDialog({ draft, saving, error, onSubmit, onClose }: Props) {
  const ref = useRef<HTMLDialogElement>(null)
  const [name, setName] = useState('')
  const [domain, setDomain] = useState('')
  const [stage, setStage] = useState<Stage>('気になる')
  const [jobType, setJobType] = useState('')
  const [location, setLocation] = useState('')
  const [remoteOk, setRemoteOk] = useState(false)
  const [tags, setTags] = useState('')
  const [salaryMin, setSalaryMin] = useState('')
  const [holidaysPerYear, setHolidaysPerYear] = useState('')
  const [deadlineAt, setDeadlineAt] = useState('')
  const [deadlineLabel, setDeadlineLabel] = useState('')

  // 開くたびに下書きで初期化する。前回の入力が残っていると別の企業を上書きしかねない
  useEffect(() => {
    if (draft === null) {
      ref.current?.close()
      return
    }
    setName(draft.name)
    setDomain(draft.domain)
    setStage(draft.stage)
    setJobType(draft.job_type ?? '')
    setLocation(draft.location ?? '')
    setRemoteOk(draft.remote_ok ?? false)
    setTags(draft.tags ?? '')
    // null（未登録）は空欄にする。0 と未登録を混ぜない
    setSalaryMin(draft.salary_min == null ? '' : String(draft.salary_min))
    setHolidaysPerYear(draft.holidays_per_year == null ? '' : String(draft.holidays_per_year))
    setDeadlineAt(draft.deadline_at ?? '')
    setDeadlineLabel(draft.deadline_label ?? '')
    if (!ref.current?.open) ref.current?.showModal()
  }, [draft])

  const isEdit = draft?.id !== undefined
  const canSave = name.trim() !== '' && (isEdit || domain.trim() !== '') && !saving

  return (
    <dialog
      className="dlg"
      ref={ref}
      onCancel={onClose}
      aria-label={isEdit ? '企業を変更' : '企業を追加'}
    >
      <form
        method="dialog"
        onSubmit={(e) => {
          e.preventDefault()
          if (!canSave) return
          onSubmit({
            id: draft?.id,
            name: name.trim(),
            domain: domain.trim(),
            stage,
            job_type: jobType.trim(),
            location: location.trim(),
            remote_ok: remoteOk,
            tags: tags.trim(),
            // 空欄は「未登録」。0 万円として保存するとマッチ率の判定がずれる
            salary_min: toNumberOrNull(salaryMin),
            holidays_per_year: toNumberOrNull(holidaysPerYear),
            // 空文字は「締切なし」。null を渡してバックエンドに Task を作らせない
            deadline_at: deadlineAt === '' ? null : deadlineAt,
            deadline_label: deadlineLabel.trim() === '' ? null : deadlineLabel.trim(),
          })
        }}
      >
        <h2>{isEdit ? '企業を変更' : '企業を追加'}</h2>

        <label>
          企業名
          <input
            autoFocus
            maxLength={80}
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="アルファテック"
          />
        </label>

        <label>
          ドメイン
          {/* @ を含めずホスト部のみ（docs/spec.md §6）。変更時は触らせない */}
          <input
            maxLength={120}
            value={domain}
            disabled={isEdit}
            onChange={(e) => setDomain(e.target.value)}
            placeholder="alphatech.co.jp"
          />
        </label>
        {isEdit && (
          <p className="co">
            ドメインは変更できません（メールの企業逆引きの結果が変わってしまうため）
          </p>
        )}

        <label>
          選考段階
          <select value={stage} onChange={(e) => setStage(e.target.value as Stage)}>
            {STAGES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>

        {/* マッチング用の条件（docs/spec.md §5.9）。空なら未登録＝その条件では合致しない */}
        <label>
          職種
          <input
            maxLength={60}
            value={jobType}
            onChange={(e) => setJobType(e.target.value)}
            placeholder="ソフトウェアエンジニア"
          />
        </label>

        <label>
          勤務地
          <input
            maxLength={60}
            value={location}
            onChange={(e) => setLocation(e.target.value)}
            placeholder="東京"
          />
        </label>

        <label className="chk-row">
          <input
            type="checkbox"
            checked={remoteOk}
            onChange={(e) => setRemoteOk(e.target.checked)}
          />
          リモート勤務が可能
        </label>

        {/* 年収・休日は AI に生成させない。人が入れた値だけをマッチ率に使う（docs/spec.md §5.9） */}
        <label>
          想定年収の下限（万円・任意）
          <input
            type="number"
            min={0}
            max={9999}
            value={salaryMin}
            onChange={(e) => setSalaryMin(e.target.value)}
            placeholder="450"
          />
        </label>

        <label>
          年間休日（日・任意）
          <input
            type="number"
            min={0}
            max={365}
            value={holidaysPerYear}
            onChange={(e) => setHolidaysPerYear(e.target.value)}
            placeholder="125"
          />
        </label>

        <label>
          特徴タグ（カンマ区切り）
          <input
            maxLength={200}
            value={tags}
            onChange={(e) => setTags(e.target.value)}
            placeholder="成長環境,若手裁量"
          />
        </label>

        {/* 締切は追加時だけ。登録後は /tasks で編集する（同じ Task を2箇所から触らせない） */}
        {!isEdit && (
          <>
            <label>
              次の締切（任意）
              <input
                type="datetime-local"
                value={deadlineAt}
                onChange={(e) => setDeadlineAt(e.target.value)}
              />
            </label>

            <label>
              締切の名前
              <input
                maxLength={40}
                value={deadlineLabel}
                disabled={deadlineAt === ''}
                onChange={(e) => setDeadlineLabel(e.target.value)}
                placeholder="選考の締切"
              />
            </label>
            <p className="co">
              締切はタスクとして登録されます。タスク一覧・今日画面・空き時間の算出にも反映されます
            </p>
          </>
        )}

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
