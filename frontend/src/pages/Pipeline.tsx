/** 選考ステータス管理ボード（`03-today-focus/FEATURE_PAGE_SPECS.md` §7）。
 *
 *  目的：どの企業がどの段階にいて、今日動きがあるのはどれかを一目で決める。
 *  5列カンバン（気になる / エントリー / 書類選考 / 面接 / 最終・内定）。
 *
 *  文言と緊急度の組み立ては lib/pipeline.ts（純関数・Vitest でテスト済み）に置く。
 *
 *  1画面完結（DESIGN_RULES R1）のため、列は横スクロール・列の中は縦スクロールにする。
 *  ページ自体には縦スクロールを出さない。
 *
 *  段階の変更は2通り用意する。
 *  - ドラッグ&ドロップ … ブラウザ標準の HTML5 DnD。ライブラリを足さない（CLAUDE.md §C）
 *  - select          … タッチ端末では標準 DnD が効かないので必ず残す。キーボードでも操作できる
 */

import { useState } from 'react'

import {
  STAGES,
  useCreateCompany,
  useDeleteCompany,
  usePipeline,
  useUpdateCompany,
  type CompanyCard,
  type Stage,
} from '../api/pipeline'
import { useToday } from '../api/today'
import { CompanyDialog, type CompanyDraft } from '../components/CompanyDialog'
import { Hero } from '../components/Hero'
import { Shell } from '../components/Shell'
import { heroSentence, mostUrgentName, statusTag, urgencyClass } from '../lib/pipeline'

const EMPTY_DRAFT: CompanyDraft = {
  name: '',
  domain: '',
  stage: '気になる',
  job_type: '',
  location: '',
  remote_ok: false,
  tags: '',
  salary_min: null,
  holidays_per_year: null,
  deadline_at: null,
  deadline_label: null,
}

/** ドラッグ中のカードを表す DataTransfer の型。企業 id だけを渡す。 */
const DRAG_TYPE = 'application/x-shukatsuhub-company'

export default function PipelinePage() {
  const [draft, setDraft] = useState<CompanyDraft | null>(null)
  // ドラッグ中のカードの id と、いま上に乗っている列。どちらも見た目のためだけに持つ
  const [dragging, setDragging] = useState<number | null>(null)
  const [overStage, setOverStage] = useState<string | null>(null)

  const { data, isLoading, error } = usePipeline()
  // ヒーローの「研究にあてられる時間」は今日画面と同じ GET /api/today から取る
  const { data: today } = useToday()
  const create = useCreateCompany()
  const update = useUpdateCompany()
  const remove = useDeleteCompany()

  const now = data?.now ?? ''
  const counts = data?.counts
  const columns = data?.columns ?? []
  const allCards = columns.flatMap((c) => c.companies)
  const urgentName = mostUrgentName(allCards, now)

  const saving = create.isPending || update.isPending
  const saveError = create.error?.message ?? update.error?.message ?? null
  const actionError = remove.error?.message ?? update.error?.message ?? null

  /** ドロップ先の列で呼ぶ。同じ列に落としたときは何もしない（無駄な PATCH を投げない）。 */
  function handleDrop(stage: Stage, companyId: number) {
    setDragging(null)
    setOverStage(null)
    const card = allCards.find((c) => c.id === companyId)
    if (card === undefined || card.stage === stage) return
    update.mutate({ id: companyId, stage })
  }

  function handleSubmit(next: CompanyDraft) {
    const done = () => {
      setDraft(null)
      create.reset()
      update.reset()
    }
    if (next.id === undefined) {
      create.mutate(
        {
          name: next.name,
          domain: next.domain,
          stage: next.stage,
          job_type: next.job_type,
          location: next.location,
          remote_ok: next.remote_ok,
          tags: next.tags,
          salary_min: next.salary_min,
          holidays_per_year: next.holidays_per_year,
          deadline_at: next.deadline_at,
          deadline_label: next.deadline_label,
        },
        { onSuccess: done },
      )
    } else {
      update.mutate(
        {
          id: next.id,
          name: next.name,
          stage: next.stage,
          job_type: next.job_type,
          location: next.location,
          remote_ok: next.remote_ok,
          tags: next.tags,
          salary_min: next.salary_min,
          holidays_per_year: next.holidays_per_year,
        },
        { onSuccess: done },
      )
    }
  }

  return (
    <Shell current="pipeline">
      <Hero
        pageName="選考ステータス"
        sentence={heroSentence(counts?.in_progress ?? 0, urgentName)}
        metrics={[
          // 先頭2つはスマホでも残る（§4.0）
          { label: '研究にあてられる時間', value: `${today?.research_hours ?? 0}h` },
          { label: '選考中', value: `${counts?.in_progress ?? 0}社` },
          { label: '登録企業', value: `${counts?.total ?? 0}社` },
          { label: '内定', value: `${counts?.offer ?? 0}社` },
        ]}
        status={actionError ? <p className="hs">操作できませんでした：{actionError}</p> : null}
        action={
          // このページの主要アクションは1つだけ（DESIGN_RULES / PROMPT.md）
          <button className="act" type="button" onClick={() => setDraft(EMPTY_DRAFT)}>
            ＋ 企業を追加
          </button>
        }
      />

      <section className="card">
        <h2>
          ▤ 選考ステータス
          <span className="more co">
            {counts?.total ?? 0}社・選考中 {counts?.in_progress ?? 0}社・内定 {counts?.offer ?? 0}社
          </span>
        </h2>
        <div className="body kanban-body">
          {error && <p className="toast err">選考状況を取得できませんでした：{error.message}</p>}
          {isLoading && <p className="toast">読み込み中…</p>}

          <div className="kanban">
            {columns.map((column) => (
              <div
                className={`kb-col${overStage === column.stage ? ' over' : ''}`}
                key={column.stage}
                // dragOver で preventDefault しないとドロップが許可されない（HTML5 DnD の仕様）
                onDragOver={(e) => {
                  if (!e.dataTransfer.types.includes(DRAG_TYPE)) return
                  e.preventDefault()
                  e.dataTransfer.dropEffect = 'move'
                  setOverStage(column.stage)
                }}
                onDragLeave={(e) => {
                  // 子要素へ移っただけの dragleave は無視する
                  if (e.currentTarget.contains(e.relatedTarget as Node | null)) return
                  setOverStage((s) => (s === column.stage ? null : s))
                }}
                onDrop={(e) => {
                  e.preventDefault()
                  const id = Number(e.dataTransfer.getData(DRAG_TYPE))
                  if (Number.isInteger(id) && id > 0) {
                    handleDrop(column.stage as Stage, id)
                  }
                }}
              >
                <div className="kb-head">
                  {column.stage}
                  <span className="co">{column.count}</span>
                </div>
                <div className="kb-list">
                  {column.count === 0 && <p className="empty kb-empty">なし</p>}

                  {column.companies.map((card) => (
                    <CompanyKanbanCard
                      key={card.id}
                      card={card}
                      now={now}
                      busy={update.isPending || remove.isPending}
                      isDragging={dragging === card.id}
                      onDragStart={(e) => {
                        e.dataTransfer.setData(DRAG_TYPE, String(card.id))
                        e.dataTransfer.effectAllowed = 'move'
                        setDragging(card.id)
                      }}
                      onDragEnd={() => {
                        setDragging(null)
                        setOverStage(null)
                      }}
                      onMove={(stage) => update.mutate({ id: card.id, stage })}
                      onEdit={() =>
                        setDraft({
                          id: card.id,
                          name: card.name,
                          domain: card.domain,
                          stage: card.stage as Stage,
                          job_type: card.job_type ?? '',
                          location: card.location ?? '',
                          remote_ok: card.remote_ok,
                          tags: card.tags ?? '',
                          salary_min: card.salary_min,
                          holidays_per_year: card.holidays_per_year,
                        })
                      }
                      onDelete={() => {
                        // 取り消せない操作なので必ず確認する
                        if (window.confirm(`「${card.name}」を削除します。よろしいですか？`)) {
                          remove.mutate(card.id)
                        }
                      }}
                    />
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      <CompanyDialog
        draft={draft}
        saving={saving}
        error={saveError}
        onSubmit={handleSubmit}
        onClose={() => {
          setDraft(null)
          create.reset()
          update.reset()
        }}
      />
    </Shell>
  )
}

type CardProps = {
  card: CompanyCard
  now: string
  busy: boolean
  isDragging: boolean
  onDragStart: (e: React.DragEvent<HTMLDivElement>) => void
  onDragEnd: () => void
  onMove: (stage: Stage) => void
  onEdit: () => void
  onDelete: () => void
}

/** カンバンのカード1枚。左端の色帯で緊急度を示す（§7）。 */
function CompanyKanbanCard({
  card,
  now,
  busy,
  isDragging,
  onDragStart,
  onDragEnd,
  onMove,
  onEdit,
  onDelete,
}: CardProps) {
  const tag = statusTag(card, now)

  return (
    <div
      className={`${urgencyClass(tag?.urgency ?? 'none')}${isDragging ? ' dragging' : ''}`}
      draggable={!busy}
      onDragStart={onDragStart}
      onDragEnd={onDragEnd}
    >
      <div className="co-name">{card.name}</div>
      {tag && <span className={tag.urgency === 'danger' ? 'tag d' : tag.urgency === 'warn' ? 'tag w' : 'tag'}>{tag.label}</span>}

      <div className="co-act">
        {/* ドラッグは入れない。select にすると1タップで移せてスマホでも同じ操作になる */}
        <select
          aria-label={`${card.name} の選考段階`}
          value={card.stage}
          disabled={busy}
          onChange={(e) => onMove(e.target.value as Stage)}
        >
          {STAGES.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
        <button className="mini" type="button" aria-label={`${card.name} を変更`} onClick={onEdit}>
          変更
        </button>
        <button
          className="mini"
          type="button"
          aria-label={`${card.name} を削除`}
          disabled={busy}
          onClick={onDelete}
        >
          削除
        </button>
      </div>
    </div>
  )
}
