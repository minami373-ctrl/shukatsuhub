/** 企業研究の情報収集画面（パスは /interview）。
 *
 *  目的：企業ごとに公開ページを AI に読ませ、研究メモ1枚として読める形にする。
 *  手で1件ずつ書き写す作業をなくすのがこの画面の役目。
 *
 *  レイアウト（人の指定・2026-08-05）:
 *  - 左（.col split）：上＝企業一覧（クリックで切り替え・収集済みが分かる）／下＝確認観点
 *  - 右：研究メモ本文（マークダウン）＋ 出典リンク
 *
 *  分類のタブは置かない（マークダウンの見出しで分かれるため）。収集元 URL の登録も持たない
 *  （読むのは企業ドメイン配下の定番ページだけ。services/research.py）。
 *  文言の組み立ては lib/research.ts（純関数・Vitest でテスト済み）に置く。
 */

import { useState } from 'react'

import {
  useCollect,
  useResearch,
  useResearchCompanies,
  useToggleCheck,
} from '../api/research'
import { useToday } from '../api/today'
import { Hero } from '../components/Hero'
import { Markdown } from '../components/Markdown'
import { Shell } from '../components/Shell'
import {
  collectToast,
  collectedAtLabel,
  companyMeta,
  heroSentence,
  sourceLabel,
  sourceLinkLabel,
  sourceTagClass,
} from '../lib/research'

export default function ResearchPage() {
  const [selectedId, setSelectedId] = useState<number | null>(null)

  const { data: companies, error: companiesError } = useResearchCompanies()
  // 初期選択は先頭の企業（想定問答画面と同じ作法）
  const companyId = selectedId ?? companies?.[0]?.id ?? null

  const { data, isLoading, error } = useResearch(companyId)
  // 研究にあてられる時間は今日画面と同じ GET /api/today を使い回す（算出を二重に持たない）
  const { data: today } = useToday()
  const collect = useCollect()
  const toggleCheck = useToggleCheck()

  const report = data?.report ?? null
  const checks = data?.checks ?? []
  const doneChecks = checks.filter((c) => c.is_done).length
  const collectedCount = (companies ?? []).filter((c) => c.collected_at !== null).length

  return (
    <Shell current="research">
      <Hero
        pageName="企業研究"
        sentence={heroSentence(data?.company_name ?? null, report !== null, data?.unchecked ?? 0)}
        metrics={[
          // 先頭2つはスマホでも残る（§4.0）。学業の研究時間と、未確認の観点を先に置く
          { label: '研究にあてられる時間', value: `${today?.research_hours ?? 0}h` },
          { label: '未確認の観点', value: `${checks.length - doneChecks}点` },
          { label: '調べた企業', value: `${collectedCount}/${companies?.length ?? 0}社` },
          { label: '出典', value: `${report?.source_urls.length ?? 0}件` },
        ]}
        status={
          collect.isError ? (
            <p className="hs">収集できませんでした：{collect.error.message}</p>
          ) : collect.isSuccess ? (
            <p className="hs">{collectToast(collect.data.source, collect.data.fetched)}</p>
          ) : toggleCheck.isError ? (
            <p className="hs">確認観点を更新できませんでした：{toggleCheck.error.message}</p>
          ) : null
        }
        action={
          // このページの主要アクションは1つだけ（DESIGN_RULES / PROMPT.md）
          <button
            className="act"
            type="button"
            disabled={companyId === null || collect.isPending}
            onClick={() => companyId !== null && collect.mutate(companyId)}
          >
            {collect.isPending ? '収集中…' : 'AI で情報を集める'}
          </button>
        }
      />

      <div className="two">
        <div className="col split">
          <section className="card">
            <h2>
              ◇ 企業
              <span className="more co">
                調べた {collectedCount}/{companies?.length ?? 0}
              </span>
            </h2>
            <div className="body scroll">
              {companiesError && (
                <p className="toast err">企業を取得できませんでした：{companiesError.message}</p>
              )}
              {companies?.length === 0 && <p className="empty">企業が登録されていません。</p>}

              {(companies ?? []).map((company) => (
                // 選択中の行は .task.sel（想定問答の質問リストと同じ語彙）
                <div
                  className={company.id === companyId ? 'task sel' : 'task'}
                  key={company.id}
                >
                  <button
                    className="row-pick"
                    type="button"
                    aria-pressed={company.id === companyId}
                    onClick={() => setSelectedId(company.id)}
                  >
                    <span className="t">
                      {company.name}
                      <span className="co">{companyMeta(company)}</span>
                    </span>
                  </button>
                  {company.source !== null && (
                    <span className={sourceTagClass(company.source)}>
                      {sourceLabel(company.source)}
                    </span>
                  )}
                  {company.unchecked > 0 && <span className="tag w">未確認 {company.unchecked}</span>}
                </div>
              ))}
            </div>
          </section>

          <section className="card">
            <h2>
              ✓ 確認観点
              <span className="more co">
                {doneChecks}/{checks.length} 点
              </span>
            </h2>
            <div className="body scroll">
              {checks.length === 0 && (
                <p className="empty">収集すると、確認すべき観点がここに並びます。</p>
              )}
              {checks.map((check) => (
                // 完了＝打ち消し線（行は動かさない）。今日画面のタスクと同じ見せ方
                <div className={check.is_done ? 'task done' : 'task'} key={check.id}>
                  <button
                    className="chk"
                    type="button"
                    aria-label={`${check.label} を${check.is_done ? '未確認に戻す' : '確認済みにする'}`}
                    aria-pressed={check.is_done}
                    disabled={toggleCheck.isPending}
                    onClick={() => toggleCheck.mutate({ id: check.id, isDone: !check.is_done })}
                  />
                  <div className="t">{check.label}</div>
                </div>
              ))}
            </div>
          </section>
        </div>

        <section className="card">
          <h2>
            ▣ {data?.company_name ?? '企業研究メモ'}
            {report && <span className="more co">{collectedAtLabel(report.collected_at)}</span>}
          </h2>
          <div className="body scroll">
            {error && <p className="toast err">メモを取得できませんでした：{error.message}</p>}
            {isLoading && <p className="toast">読み込み中…</p>}
            {!isLoading && !error && report === null && (
              <p className="empty">
                まだ調べていません。「AI で情報を集める」を押すと、この企業の公開ページを読んで
                メモを作ります。
              </p>
            )}

            {report && (
              <>
                {/* AI が書いた文章。事実の確認は人が行う（docs/spec.md §5.6 と同じ運用） */}
                <Markdown markdown={report.markdown} />

                {report.source_urls.length > 0 && (
                  <div className="src-list">
                    <h4>出典</h4>
                    <ul>
                      {report.source_urls.map((url) => (
                        <li key={url}>
                          <a href={url} target="_blank" rel="noreferrer noopener">
                            {sourceLinkLabel(url)}
                          </a>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                {report.source !== 'web' && (
                  <p className="toast">
                    {sourceLabel(report.source)}：公開ページの本文は使っていません。事実は自分で確かめてください。
                  </p>
                )}
              </>
            )}
          </div>
        </section>
      </div>
    </Shell>
  )
}
