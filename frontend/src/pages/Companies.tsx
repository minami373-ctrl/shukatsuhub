/** 企業の発見・マッチング（`03-today-focus/FEATURE_PAGE_SPECS.md` §12）。
 *
 *  目的：いくつかの質問に答えるだけで、条件に合いそうな企業が並ぶ。
 *  - 左：企業カード（マッチ率・職種/勤務地・マッチ理由・「気になるに追加」）
 *  - 右：マッチング条件（テンプレ質問）と検索ボタン
 *
 *  **マッチ率は AI ではなくプログラム計算**（docs/spec.md §5.9）。同じ条件なら常に同じ結果。
 *  企業一覧の取得元は services/company_source.py に集約してあり、実データへの移行は
 *  そこだけを差し替える（§5.10）。取得元は画面下部に出す。
 *
 *  「気になるに追加」は選考ステータスの「気になる」列へ入る＝ページ間が繋がっていることを示す（§12）。
 */

import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import {
  MATCH_SCOPES,
  useCompanySuggestions,
  useCreateCompaniesFromEmails,
  useMatching,
  type CompanySuggestion,
  type MatchScope,
  type MatchedCompany,
} from '../api/matching'
import { useUpdateCompany } from '../api/pipeline'
import { useProfile } from '../api/profile'
import { useToday } from '../api/today'
import { Hero } from '../components/Hero'
import { Shell } from '../components/Shell'
import {
  canWatch,
  companyMeta,
  heroSentence,
  rateClass,
  rateTone,
  suggestionHeading,
  suggestionMeta,
  watchedLabel,
} from '../lib/matching'

export default function CompaniesPage() {
  const [jobType, setJobType] = useState('')
  const [location, setLocation] = useState('')
  const [remoteOnly, setRemoteOnly] = useState(false)
  const [salaryMin, setSalaryMin] = useState('')
  const [holidaysMin, setHolidaysMin] = useState('')
  const [scope, setScope] = useState<MatchScope>('recommended')

  const search = useMatching()
  const watch = useUpdateCompany()
  const suggestions = useCompanySuggestions()
  const register = useCreateCompaniesFromEmails()
  const { data: profile } = useProfile()
  const { data: today } = useToday()

  const result = search.data
  const items = result?.items ?? []
  const searched = search.isSuccess

  // セグメントを切り替えたら、同じ条件で取り直す（条件は右カラムに残したまま）
  useEffect(() => {
    if (!search.isSuccess && !search.isError) return
    runSearch()
    // scope の変更だけをきっかけにする。条件を打つたびに検索が走らないようにする
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scope])

  function runSearch() {
    search.mutate({
      job_type: jobType,
      location,
      remote_only: remoteOnly,
      salary_min: salaryMin,
      holidays_min: holidaysMin,
      axes: null,
      scope,
    })
  }

  return (
    <Shell current="companies">
      <Hero
        pageName="企業の発見・マッチング"
        sentence={heroSentence(searched, result?.recommended_count ?? 0, items[0]?.name ?? null)}
        metrics={[
          // 先頭2つはスマホでも残る（§4.0）
          { label: '研究にあてられる時間', value: `${today?.research_hours ?? 0}h` },
          { label: 'おすすめ', value: `${result?.recommended_count ?? 0}社` },
          { label: '該当', value: `${items.length}社` },
          { label: '登録企業', value: `${result?.total_count ?? 0}社` },
        ]}
        status={
          watch.isError ? <p className="hs">追加できませんでした：{watch.error.message}</p> : null
        }
        action={
          // このページの主要アクションは1つだけ（DESIGN_RULES / PROMPT.md）
          <button className="act" type="button" disabled={search.isPending} onClick={runSearch}>
            {search.isPending ? '検索中…' : '条件で探す'}
          </button>
        }
      />

      <div className="two">
        <section className="card">
          <h2>
            ◇ 企業
            <div className="seg">
              {MATCH_SCOPES.map((s) => (
                <button
                  key={s.value}
                  type="button"
                  className={scope === s.value ? 'on' : ''}
                  aria-pressed={scope === s.value}
                  onClick={() => setScope(s.value)}
                >
                  {s.label}
                </button>
              ))}
            </div>
          </h2>
          <div className="body scroll">
            {search.isError && (
              <p className="toast err">検索できませんでした：{search.error.message}</p>
            )}
            {search.isPending && <p className="toast">検索中…</p>}
            {!searched && !search.isPending && !search.isError && (
              <p className="empty">右の条件を入力して「条件で探す」を押してください。</p>
            )}
            {searched && items.length === 0 && (
              <p className="empty">該当する企業はありません。条件をゆるめてみてください。</p>
            )}

            <div className="co-grid">
              {items.map((company) => (
                <MatchCard
                  key={company.id}
                  company={company}
                  busy={watch.isPending}
                  onWatch={() =>
                    // stage（カンバンの列）と is_watched（登録企業フラグ）は別物（docs/spec.md §6）。
                    // 「気になるに追加」は登録企業にすることなので is_watched を必ず立てる。
                    // stage だけ送ると、既に「気になる」の企業では何も変わらない
                    watch.mutate(
                      { id: company.id, stage: '気になる', is_watched: true },
                      { onSuccess: () => runSearch() },
                    )
                  }
                />
              ))}
            </div>
          </div>
        </section>

        <section className="card">
          <h2>
            ⚙ マッチング条件
            <Link className="more" to="/profile">
              プロフィール →
            </Link>
          </h2>
          <div className="body scroll">
            <label className="fld">
              希望する職種
              <input
                maxLength={60}
                value={jobType}
                onChange={(e) => setJobType(e.target.value)}
                placeholder="ソフトウェアエンジニア"
              />
            </label>

            <label className="fld">
              希望する勤務地
              <input
                maxLength={60}
                value={location}
                onChange={(e) => setLocation(e.target.value)}
                placeholder="東京"
              />
            </label>

            <label className="fld row">
              <input
                type="checkbox"
                checked={remoteOnly}
                onChange={(e) => setRemoteOnly(e.target.checked)}
              />
              リモート勤務が必須
            </label>

            {/* 年収・休日は企業に保存した値とだけ照合する。AI に生成させない（docs/spec.md §5.9） */}
            <label className="fld">
              希望年収（万円以上）
              <input
                type="number"
                min={0}
                max={9999}
                value={salaryMin}
                onChange={(e) => setSalaryMin(e.target.value)}
                placeholder="400"
              />
            </label>

            <label className="fld">
              年間休日（日以上）
              <input
                type="number"
                min={0}
                max={365}
                value={holidaysMin}
                onChange={(e) => setHolidaysMin(e.target.value)}
                placeholder="120"
              />
            </label>

            <div className="fld">
              就活軸（プロフィールから）
              <div className="axes">
                {(result?.axes ?? []).length === 0 && (
                  <span className="co">
                    {profile && profile.job_axis.trim() !== ''
                      ? '検索すると反映されます'
                      : 'プロフィールの就活軸が未入力です'}
                  </span>
                )}
                {(result?.axes ?? []).map((axis) => (
                  <span className="tag" key={axis}>
                    {axis}
                  </span>
                ))}
              </div>
            </div>

            <p className="co">
              マッチ率は AI ではなく計算で出しています
              （職種3・勤務地2・年収2・休日1・リモート1・就活軸1つにつき1の重み）。
              同じ条件なら常に同じ結果になります。企業側が未登録の項目は合致しない扱いです。
            </p>
            {result && (
              <p className="co">
                企業データの取得元：<b>{result.source === 'seed' ? 'サンプルデータ' : result.source}</b>
              </p>
            )}

            {/* 受信箱からの企業登録の提案（docs/spec.md §5.11）。
                企業を探す手間・登録する手間を減らすのが目的なので、条件の下に並べる。
                AI もスクレイピングも使わず、既に受信しているメールだけを根拠にする */}
            {(suggestions.data ?? []).length > 0 && (
              <div className="sug">
                <h3>{suggestionHeading((suggestions.data ?? []).length)}</h3>
                <p className="co">
                  登録すると選考ボードの「気になる」に入ります。
                  職種・年収などはメールから分からないので、登録後に企業ダイアログで入力してください。
                </p>
                {(suggestions.data ?? []).map((suggestion) => (
                  <SuggestionRow
                    key={suggestion.domain}
                    suggestion={suggestion}
                    busy={register.isPending}
                    onRegister={() =>
                      register.mutate([suggestion.domain], {
                        onSuccess: () => {
                          if (searched) runSearch()
                        },
                      })
                    }
                  />
                ))}
                {register.isError && (
                  <p className="toast err">登録できませんでした：{register.error.message}</p>
                )}
                {register.isSuccess && register.data.created.length > 0 && (
                  <p className="co">
                    {register.data.created.map((c) => c.name).join('・')} を登録しました
                    （メール{register.data.linked_emails}件を紐づけました）
                  </p>
                )}
              </div>
            )}
          </div>
        </section>
      </div>
    </Shell>
  )
}

type SuggestionProps = {
  suggestion: CompanySuggestion
  busy: boolean
  onRegister: () => void
}

/** 登録候補1件（docs/spec.md §5.11）。企業名はあくまで**候補**なので、
 *  登録後に企業ダイアログ（/pipeline）で直せることを添える。 */
function SuggestionRow({ suggestion, busy, onRegister }: SuggestionProps) {
  return (
    <div className="sug-row">
      <div>
        <div className="sug-name">{suggestion.suggested_name}</div>
        <div className="co">{suggestionMeta(suggestion)}</div>
      </div>
      <button className="mini" type="button" disabled={busy} onClick={onRegister}>
        ＋ 登録
      </button>
    </div>
  )
}

type CardProps = {
  company: MatchedCompany
  busy: boolean
  onWatch: () => void
}

/** 企業カード1枚（§12）。マッチ率・職種/勤務地・マッチ理由・「気になるに追加」。 */
function MatchCard({ company, busy, onWatch }: CardProps) {
  const label = watchedLabel(company)

  return (
    <div className="co-card">
      <div className="co-name">
        {company.name}
        <span className={rateClass(rateTone(company.rate))}>{company.rate}%</span>
      </div>
      <div className="co">{companyMeta(company)}</div>

      {/* 合致した条件だけを出す。合致しなかった条件は理由に出さない（推測で理由を作らない） */}
      <ul className="why">
        {company.reasons.slice(0, 2).map((reason) => (
          <li key={reason}>{reason}</li>
        ))}
        {company.reasons.length === 0 && <li className="co">合致した条件はありません</li>}
      </ul>

      {canWatch(company) ? (
        <button className="mini" type="button" disabled={busy} onClick={onWatch}>
          ＋ 気になるに追加
        </button>
      ) : (
        <span className="co">{label}</span>
      )}
    </div>
  )
}
