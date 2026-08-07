/** タスク・締め切り画面（`03-today-focus/FEATURE_PAGE_SPECS.md` §6）。
 *
 *  目的：締切が近いものから順に片付ける。どれが期限切れかを一目で分かるようにする。
 *  - 左：タスク一覧（今日 / 今週 / すべて / 完了 で絞り込み）
 *  - 右上：締切カウントダウン上位3件
 *  - 右下：空き時間に差し込む提案（今日画面と同じ GET /api/today の空きスロットを使う）
 *
 *  文言の組み立ては lib/tasks.ts（純関数・Vitest でテスト済み）に置く。
 *
 *  絞り込みは `.content` が2行グリッド（ヒーロー ＋ 本体）で固定されているため、
 *  行を増やさずカードの見出しに入れる（1画面完結を崩さないため）。
 */

import { useState } from 'react'
import { Link } from 'react-router-dom'

import {
  SCOPES,
  useCreateTask,
  useDeleteTask,
  useTasks,
  useUpdateTask,
  type Badge,
  type Priority,
  type TaskScope,
} from '../api/tasks'
import { useToday, useToggleTask } from '../api/today'
import { Hero } from '../components/Hero'
import { Shell } from '../components/Shell'
import { TaskDialog, type TaskDraft } from '../components/TaskDialog'
import {
  countdownLabel,
  dueTag,
  dueTagClass,
  formatMd,
  heroSentence,
  isVisibleInScope,
  taskMeta,
} from '../lib/tasks'
import { formatHm } from '../lib/today'

/** 追加のときの初期値。期限は空にして、必ず自分で決めさせる（今日の23:59を勝手に入れない）。 */
const EMPTY_DRAFT: TaskDraft = {
  title: '',
  due_at: '',
  estimate_min: 30,
  priority: '中',
  badge: null,
}

/** 重要度は「高」だけをタグで出す。
 *
 *  1行に並ぶタグが3つになると読みづらいので、既定の「中」に加えて「低」も出さない
 *  （急ぎでないものを目立たせる必要はない）。docs/spec.md §6 のとおり priority で
 *  並べ替えはしないので、色は締切タグ（.tag.d）と重ならないティール系にする。 */
const HIGH_PRIORITY = '高'

/** タスクのバッジ色。今日画面と同じ対応にする。 */
const BADGE_TAG_CLASS: Record<string, string> = {
  最優先: 'tag d',
  要返信: 'tag w',
  準備: 'tag',
}

export default function TasksPage() {
  const [scope, setScope] = useState<TaskScope>('today')
  //  null なら閉じている。id 付きなら変更、id 無しなら追加
  const [draft, setDraft] = useState<TaskDraft | null>(null)
  // 保存したタスクが絞り込みの範囲外だったときの案内
  const [notice, setNotice] = useState<string | null>(null)

  const { data, isLoading, error } = useTasks(scope)
  // 右カラムは絞り込みに関係なく「未完了の締切が近い順」を見せたいので全件から取る。
  // scope === 'all' のときは同じクエリキーになるので追加のリクエストは発生しない
  const { data: allData } = useTasks('all')
  // 空きスロットは今日画面と同じ GET /api/today を使い回す（算出ロジックを二重に持たない）
  const { data: today } = useToday()
  const toggle = useToggleTask()
  const create = useCreateTask()
  const update = useUpdateTask()
  const remove = useDeleteTask()

  const saving = create.isPending || update.isPending
  const saveError = create.error?.message ?? update.error?.message ?? null

  function handleSubmit(next: TaskDraft) {
    const body = {
      title: next.title,
      due_at: next.due_at,
      estimate_min: next.estimate_min,
      priority: next.priority,
      badge: next.badge,
    }

    /** 保存できたら閉じる。保存したタスクが今の絞り込みに出ないなら「すべて」へ逃がす。
     *
     *  「今日」の範囲（今週など）から外れた締切で保存すると一覧から外れる。
     *  黙って消えると保存できなかったように見えるため、切り替えたことを明示する。 */
    const done = (saved: { due_at: string; is_done: boolean }) => {
      setDraft(null)
      create.reset()
      update.reset()

      if (isVisibleInScope(scope, saved.due_at, saved.is_done, reference)) {
        setNotice(null)
        return
      }
      setScope('all')
      setNotice(
        `「${next.title}」を保存しました。締切 ${formatMd(saved.due_at)} は「${
          SCOPES.find((s) => s.value === scope)?.label ?? scope
        }」の範囲外なので「すべて」に切り替えました（このアプリの今日は ${reference} です）。`,
      )
    }

    if (next.id === undefined) {
      create.mutate(body, { onSuccess: done })
    } else {
      update.mutate({ id: next.id, ...body }, { onSuccess: done })
    }
  }

  const tasks = data?.tasks ?? []
  const now = data?.now ?? ''
  const counts = data?.counts
  // 絞り込みの基準日（API が返す実際の今日の日付。docs/spec.md §5.3）
  const reference = data?.date ?? ''

  const openTasks = (allData?.tasks ?? []).filter((task) => !task.is_done)
  const countdown = openTasks.slice(0, 3)
  const suggestions = (today?.free_slots ?? []).filter((slot) => slot.suggested_task_label !== null)

  // 期限切れがあればそれを、無ければ締切が最も近い未完了を「まず ○○ から。」に使う
  const nearest = counts && counts.overdue > 0 ? openTasks.find((t) => t.is_overdue) : openTasks[0]
  const nearestLabel = nearest ? (nearest.short_label ?? nearest.title) : null

  return (
    <Shell current="tasks">
      <Hero
        pageName="タスク・締め切り"
        sentence={heroSentence(counts?.today ?? 0, counts?.overdue ?? 0, nearestLabel)}
        metrics={[
          // 先頭2つはスマホでも残る。研究時間と期限切れを先に置く（§4.0）
          { label: '研究にあてられる時間', value: `${today?.research_hours ?? 0}h` },
          { label: '期限切れ', value: `${counts?.overdue ?? 0}件` },
          { label: '今日', value: `${counts?.today ?? 0}件` },
          { label: '今週', value: `${counts?.week ?? 0}件` },
        ]}
        status={
          toggle.isError ? (
            <p className="hs">更新できませんでした：{toggle.error.message}</p>
          ) : remove.isError ? (
            <p className="hs">削除できませんでした：{remove.error.message}</p>
          ) : null
        }
        action={
          // このページの主要アクションは1つだけ（DESIGN_RULES / PROMPT.md）。
          // ヒーロー内のボタンは白地の .act（プロフィールの「保存」と同じ語彙）
          <button className="act" type="button" onClick={() => setDraft(EMPTY_DRAFT)}>
            ＋ タスクを追加
          </button>
        }
      />

      <div className="two">
        <section className="card">
          <h2>
            ✓ タスク・締め切り
            <div className="seg">
              {SCOPES.map((s) => (
                <button
                  key={s.value}
                  type="button"
                  className={scope === s.value ? 'on' : ''}
                  aria-pressed={scope === s.value}
                  onClick={() => {
                    setScope(s.value)
                    setNotice(null)
                  }}
                >
                  {s.label}
                </button>
              ))}
            </div>
          </h2>
          <div className="body scroll">
            {error && <p className="toast err">タスクを取得できませんでした：{error.message}</p>}
            {isLoading && <p className="toast">読み込み中…</p>}
            {notice && <p className="toast">{notice}</p>}
            {!isLoading && !error && tasks.length === 0 && (
              <p className="empty">
                {scope === 'done'
                  ? 'まだ完了したタスクはありません。'
                  : '該当するタスクはありません。研究に集中できます。'}
              </p>
            )}

            {tasks.map((task) => {
              const tag = dueTag(task.due_at, task.is_done, now)
              return (
                // 完了＝打ち消し線（行は動かさない）／締切超過の未完了＝黄色文字
                <div
                  className={['task', task.is_done && 'done', task.is_overdue && 'over']
                    .filter(Boolean)
                    .join(' ')}
                  key={task.id}
                >
                  <button
                    className="chk"
                    type="button"
                    aria-label={`${task.title} を${task.is_done ? '未完了に戻す' : '完了にする'}`}
                    aria-pressed={task.is_done}
                    disabled={toggle.isPending}
                    onClick={() => toggle.mutate({ id: task.id, isDone: !task.is_done })}
                  />
                  <div className="t">
                    {task.title}
                    <div className="co">
                      {taskMeta(task.company_name, task.due_at, task.estimate_min)}
                    </div>
                  </div>
                  {/* 重要度は「高」だけ。中・低は出さない */}
                  {task.priority === HIGH_PRIORITY && <span className="tag">高</span>}
                  {/* タグ（行動の種類）。重要度とは別の軸 */}
                  {task.badge && (
                    <span className={BADGE_TAG_CLASS[task.badge] ?? 'tag'}>{task.badge}</span>
                  )}
                  {tag && <span className={dueTagClass(tag.tone)}>{tag.label}</span>}

                  {/* 行の操作。主要アクションではないので .mini（プロフィールのコピーボタンと同じ語彙） */}
                  <div className="row-act">
                    <button
                      className="mini"
                      type="button"
                      aria-label={`${task.title} を変更`}
                      onClick={() =>
                        setDraft({
                          id: task.id,
                          title: task.title,
                          due_at: task.due_at,
                          estimate_min: task.estimate_min,
                          priority: task.priority as Priority,
                          badge: (task.badge as Badge | null) ?? null,
                        })
                      }
                    >
                      変更
                    </button>
                    <button
                      className="mini"
                      type="button"
                      aria-label={`${task.title} を削除`}
                      disabled={remove.isPending}
                      onClick={() => {
                        // 取り消せない操作なので必ず確認する
                        if (window.confirm(`「${task.title}」を削除します。よろしいですか？`)) {
                          remove.mutate(task.id)
                        }
                      }}
                    >
                      削除
                    </button>
                  </div>
                </div>
              )
            })}
          </div>
        </section>

        <div className="col split">
          <section className="card">
            <h2>
              ⏳ 締切カウントダウン
              <span className="more co">未完了 {openTasks.length}件</span>
            </h2>
            <div className="body scroll">
              {!isLoading && countdown.length === 0 && (
                <p className="empty">締切を待つタスクはありません。</p>
              )}
              {countdown.map((task) => (
                <div className={['task', task.is_overdue && 'over'].filter(Boolean).join(' ')} key={task.id}>
                  <div className="t">
                    {task.short_label ?? task.title}
                    <div className="co">{taskMeta(task.company_name, task.due_at)}</div>
                  </div>
                  <span className={task.is_overdue ? 'tag d' : 'tag'}>
                    {countdownLabel(task.due_at, now)}
                  </span>
                </div>
              ))}
            </div>
          </section>

          <section className="card">
            <h2>
              ▣ 空き時間に差し込む提案
              <Link className="more" to="/">
                今日 →
              </Link>
            </h2>
            <div className="body scroll">
              {suggestions.length === 0 && (
                <p className="empty">差し込める空き時間はありません。</p>
              )}
              {suggestions.map((slot) => (
                <div className="task" key={slot.start}>
                  <div className="t">
                    {slot.suggested_task_label} を割り当て
                    <div className="co">
                      {formatHm(slot.start)}-{formatHm(slot.end)} の空き
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </section>
        </div>
      </div>

      <TaskDialog
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
