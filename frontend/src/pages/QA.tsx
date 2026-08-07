/** 想定問答 /qa（spec.md §4.5）。
 *
 *  目的：面接前に「何を聞かれるか」と「どう答えるか」を1画面で確認し、準備の進み具合を把握する。
 *  - ヒーロー直下に企業セレクト ＋ 「想定問答を生成」（このページの主要アクション。1つだけ）
 *  - 左：想定質問（件数で切らず、カード内スクロールで全件）／右：回答骨子を自分で編集して保存
 *  - 完了はチェックボックスではなく「回答を保存」で決まる（空欄では保存できない）
 *  - 生成元（AI / テンプレ）を見出し右に必ず出す。ユーザーが取り違えないようにする
 *
 *  文言と導出値の組み立ては lib/qa.ts（純関数・Vitest でテスト済み）に置く。
 */

import { useState } from 'react'

import { useCompanies, useGenerateQA, useQASheet, useSaveQAAnswer } from '../api/qa'
import { useToday } from '../api/today'
import { Hero } from '../components/Hero'
import {
  CATEGORY_TAG_CLASS,
  canSaveAnswer,
  heroSentence,
  preparedRate,
  sourceLabel,
  unpreparedCount,
} from '../lib/qa'

export function QAPage() {
  const companies = useCompanies()
  // 研究にあてられる時間は /api/today の算出値（§5.3）。全画面で同じ数字を出す
  const today = useToday()

  const [pickedCompanyId, setPickedCompanyId] = useState<number | null>(null)
  const [pickedQAId, setPickedQAId] = useState<number | null>(null)
  // 編集中の回答。未編集なら null（保存済みの本文をそのまま見せる）
  const [draft, setDraft] = useState<string | null>(null)

  // 未選択のうちは先頭の企業を見る（useEffect で state を後追いさせない）
  const companyId = pickedCompanyId ?? companies.data?.[0]?.id ?? null

  const sheet = useQASheet(companyId)
  const generate = useGenerateQA()
  const save = useSaveQAAnswer(companyId)

  const items = sheet.data?.items ?? []
  const rate = preparedRate(items)
  const unprepared = unpreparedCount(items)
  const companyName = companies.data?.find((c) => c.id === companyId)?.name ?? null
  const badge = sourceLabel(sheet.data?.source ?? null)

  // 未選択なら先頭の QA の回答骨子を出す（§4.5）
  const selected = items.find((item) => item.id === pickedQAId) ?? items[0] ?? null
  const answer = draft ?? selected?.answer_draft ?? ''
  const isDirty = selected !== null && draft !== null && draft !== selected.answer_draft

  function changeCompany(id: number) {
    if (!confirmDiscard()) return
    setPickedCompanyId(id)
    // 企業が変われば一覧も入れ替わるので、選択と編集を初期状態に戻す
    setPickedQAId(null)
    setDraft(null)
  }

  /** 未保存の編集があるときは、捨てる前に確認する（§4.5）。 */
  function confirmDiscard(): boolean {
    if (!isDirty) return true
    return window.confirm('保存していない回答があります。破棄して切り替えますか？')
  }

  function selectQA(id: number) {
    if (id === selected?.id) return
    if (!confirmDiscard()) return
    setPickedQAId(id)
    setDraft(null)
  }

  function generateQA() {
    if (companyId === null) return
    if (!confirmDiscard()) return
    // 生成は一覧を丸ごと入れ替えるので、編集中の下書きと選択を先に捨てる。
    // 残すと別の質問に古い下書きが紐づいて見え、保存で上書きしてしまう
    setPickedQAId(null)
    setDraft(null)
    generate.mutate(companyId)
  }

  function saveAnswer() {
    if (selected === null || !canSaveAnswer(answer)) return
    save.mutate(
      { id: selected.id, answerDraft: answer },
      // 保存できたら一覧が正になるので、編集中の下書きは畳む
      { onSuccess: () => setDraft(null) },
    )
  }

  const errorMessage =
    save.error?.message ??
    generate.error?.message ??
    sheet.error?.message ??
    companies.error?.message ??
    null

  return (
    <>
      <Hero
        pageName="想定問答"
        sentence={heroSentence(companyName, items)}
        status={
          <div className="hs">
            {errorMessage && <span>⚠ {errorMessage}</span>}
            {/* 未保存の編集が出たら消す。保存済みと誤認させないため */}
            {save.isSuccess && !save.isPending && !isDirty && <span>保存しました</span>}
          </div>
        }
        metrics={[
          // 先頭2つはスマホでも残る（§4.5）。研究にあてられる時間と準備率を先に置く
          {
            label: '研究にあてられる時間',
            value: today.data ? `${today.data.research_hours}h` : '—',
          },
          { label: '準備率', value: `${rate}%`, bar: rate },
          { label: '想定質問', value: `${items.length}問` },
          { label: '未準備', value: `${unprepared}問` },
        ]}
      />

      {/* .content の grid は2行なので、セレクト行と本体はこの1枚にまとめて入れる
          （行を増やすと 100dvh に収まらなくなる） */}
      <div className="qa-main">
        <div className="qa-bar">
          <label className="co" htmlFor="qa-company">
            企業
          </label>
          <select
            id="qa-company"
            value={companyId ?? ''}
            disabled={companies.isPending || companies.isError}
            onChange={(e) => changeCompany(Number(e.target.value))}
          >
            {companies.data?.map((company) => (
              <option value={company.id} key={company.id}>
                {company.name}
              </option>
            ))}
          </select>
          <button
            className="primary"
            type="button"
            disabled={companyId === null || generate.isPending}
            onClick={generateQA}
          >
            {generate.isPending ? '生成中…' : '想定問答を生成'}
          </button>
        </div>

        <div className="two">
          <section className="card">
            <h2>
              ？ 想定質問
              {badge && <span className="src tag ai">{badge}</span>}
            </h2>
            {/* 件数で切らず、カード内スクロールで全件たどれるようにする（§4.5） */}
            <div className="body scroll">
              {sheet.isPending && companyId !== null && <p className="toast">読み込み中…</p>}
              {!sheet.isPending && items.length === 0 && (
                <p className="empty">まだありません。企業を選んで「想定問答を生成」を押してください。</p>
              )}

              {items.map((item) => (
                <div
                  className={['task', item.id === selected?.id && 'sel'].filter(Boolean).join(' ')}
                  key={item.id}
                >
                  <span className={CATEGORY_TAG_CLASS[item.category]}>{item.category}</span>
                  {/* 押すと右の回答骨子が差し替わる（画面遷移はしない）。
                      選択中の行は CSS で折り返して全文が出る。それ以外の行は1行＋… なので、
                      title で PC のホバーからも全文を読めるようにする（Calendar.tsx と同じ） */}
                  <button
                    className="t qa-q"
                    type="button"
                    title={item.question}
                    onClick={() => selectQA(item.id)}
                  >
                    {item.question}
                  </button>
                  {item.is_prepared && <span className="tag g">準備済み</span>}
                </div>
              ))}
            </div>
          </section>

          <section className="card">
            <h2>
              ◎ 回答骨子
              {selected && <span className="more co">{selected.category}</span>}
            </h2>
            <div className="body scroll">
              {selected ? (
                <textarea
                  className="ta qa-answer-input"
                  value={answer}
                  aria-label="回答骨子"
                  placeholder="AI／テンプレの骨子を、自分の言葉に直して書く"
                  disabled={save.isPending}
                  onChange={(e) => setDraft(e.target.value)}
                />
              ) : (
                <p className="empty">生成すると、ここに回答の骨子が出ます。</p>
              )}
            </div>
            {/* 保存で準備済みになる。準備率のバーはプロフィールと同じ自前 CSS */}
            <div className="qa-foot">
              <div className="qa-foot-row">
                <span className="co">
                  準備率 {rate}%（{items.length - unprepared} / {items.length}問）
                </span>
                <button
                  className="qa-save"
                  type="button"
                  disabled={selected === null || !canSaveAnswer(answer) || save.isPending}
                  onClick={saveAnswer}
                >
                  {save.isPending ? '保存中…' : '回答を保存'}
                </button>
              </div>
              <div className="hbar">
                <i style={{ width: `${rate}%` }} />
              </div>
            </div>
          </section>
        </div>
      </div>
    </>
  )
}
