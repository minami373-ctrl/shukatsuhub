/** プロフィール・自己分析 /profile（spec.md §4.4）。
 *  ES やマイページに何度も書く内容を1か所に置き、コピーで使い回す。 */

import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import { useProfile, useSaveProfile } from '../api/profile'
import { CopyButton } from '../components/CopyButton'
import { Hero } from '../components/Hero'
import {
  EMPTY_PROFILE,
  PROFILE_FIELDS,
  completeness,
  filledFields,
  heroSentence,
  isSameProfile,
  pickFields,
  unfilledLabels,
  type FieldName,
  type ProfileFields,
} from '../lib/profile'

export function ProfilePage({ onCompletenessChange }: { onCompletenessChange: (v: number) => void }) {
  const { data, isPending, isError, error } = useProfile()
  const save = useSaveProfile()

  // draft は「ユーザーが編集した内容」だけを持つ。未編集なら null のまま
  const [draft, setDraft] = useState<ProfileFields | null>(null)
  // スマホでどの項目を編集中か（PC では9項目すべて並ぶので使わない）
  const [selected, setSelected] = useState<FieldName>(PROFILE_FIELDS[0].name)

  // 取得前は編集させない。取得済みの内容を空文字で上書きしてしまうのを防ぐ
  const loaded = data ? pickFields(data) : null
  const current = draft ?? loaded ?? EMPTY_PROFILE
  const isDirty = loaded !== null && draft !== null && !isSameProfile(draft, loaded)
  const pct = completeness(current)
  const filled = new Set(filledFields(current))
  const unfilled = unfilledLabels(current)

  // 親（パネルのサブテキスト）へ充実度を伝える
  useEffect(() => {
    onCompletenessChange(pct)
  }, [pct, onCompletenessChange])

  function update(name: FieldName, value: string) {
    if (loaded === null) return // 取得完了までは編集を受け付けない
    setDraft({ ...current, [name]: value })
  }

  return (
    <>
      <Hero
        pageName="プロフィール・自己分析"
        sentence={heroSentence(current)}
        next={
          unfilled.length === 0 ? (
            <Link className="next" to="/qa">
              想定問答 →
            </Link>
          ) : undefined
        }
        status={
          <div className="hs">
            {isPending && <span>読み込み中…</span>}
            {isError && <span>⚠ {error.message}</span>}
            {save.isError && <span>⚠ {save.error.message}</span>}
            {/* 未保存の変更が出たら消す。保存済みと誤認させないため */}
            {save.isSuccess && !save.isPending && !isDirty && <span>保存しました</span>}
          </div>
        }
        metrics={[
          { label: '充実度', value: `${pct}%`, bar: pct },
          // 研究にあてられる時間は /api/today（別スコープ）の算出値。未実装なので伏せる
          { label: '研究にあてられる時間', value: '—' },
          { label: '入力済み', value: `${filled.size}項目` },
          { label: '未入力', value: `${unfilled.length}項目` },
        ]}
        action={
          <button
            className="act"
            onClick={() => save.mutate(current)}
            disabled={loaded === null || save.isPending}
          >
            {save.isPending ? '保存中…' : '保存'}
          </button>
        }
      />

      {/* 9項目を 3列 × 3行（spec.md §4.4）。スマホはチップで1項目ずつ切り替える */}
      <div className="fields">
        <div className="chips field-chips">
          {PROFILE_FIELDS.map(({ name, label }) => (
            <button
              key={name}
              className={name === selected ? 'on' : undefined}
              onClick={() => setSelected(name)}
            >
              {label}
            </button>
          ))}
        </div>

        {PROFILE_FIELDS.map(({ name, label, placeholder }) => (
          <div className={name === selected ? 'card sel' : 'card'} key={name}>
            {/* 文字数とコピーは見出しに畳む。カード下段を作らず入力欄の高さを稼ぐ */}
            <h2>
              <span className="lb">{label}</span>
              {!filled.has(name) && <span className="tag w">未入力</span>}
              <CopyButton text={current[name]} fieldLabel={label} />
              <span className="co">{current[name].length} 字</span>
            </h2>
            <div className="body">
              <textarea
                className="ta"
                value={current[name]}
                placeholder={placeholder}
                aria-label={label}
                disabled={loaded === null}
                onChange={(e) => update(name, e.target.value)}
              />
            </div>
          </div>
        ))}
      </div>
    </>
  )
}
