/** 今日（ホーム）画面（docs/spec.md §4.1）。
 *
 *  目的：開いたら今日の動きだけが分かる。何をすればいいかが一目で決まる。
 *  - 左カラム：今日やること（4件まで）／今日返すべきメール（2件まで）
 *  - 右カラム：今日のタイムライン（予定＋空きスロット＋翌日の先頭予定1件）
 *  - チェックを付けると is_done が反転し、ヒーローの指標が再計算される
 *
 *  文言の組み立ては lib/today.ts（純関数・Vitest でテスト済み）に置く。
 */

import { Link } from 'react-router-dom'

import { useToday, useToggleTask } from '../api/today'
import { formatJaDate } from '../api/eventMap'
import { Hero } from '../components/Hero'
import { Shell } from '../components/Shell'
import { buildTimeline, formatHm, heroSentence, taskNote } from '../lib/today'

/** カテゴリごとのタグ色（§4.3 と同じ対応にする）。 */
const CATEGORY_TAG_CLASS: Record<string, string> = {
  重要: 'tag d',
  確認: 'tag w',
  広告: 'tag',
}

/** タスクのバッジ色。最優先＝赤系／要返信＝黄系／それ以外＝ティール系。 */
const BADGE_TAG_CLASS: Record<string, string> = {
  最優先: 'tag d',
  要返信: 'tag w',
  準備: 'tag',
}

/** タイムラインの色分け。就活＝ティール／学業＝グレー／研究＝枠線つき／就活の空き＝斜線。 */
const EV_CLASS: Record<string, string> = {
  brand: 'ev',
  class: 'ev cls',
  research: 'ev study',
  free: 'ev free',
}

export default function TodayPage() {
  const { data, isLoading, error } = useToday()
  const toggle = useToggleTask()

  // 一覧は件数で切らず、カード内（.body.scroll）のスクロールで全件たどれるようにする
  const tasks = data?.tasks ?? []
  const emails = data?.emails ?? []

  const timeline = data
    ? buildTimeline(data.events, data.free_slots, data.tomorrow_event, data.research_slots)
    : []

  return (
    <Shell current="today">
      <Hero
        pageName={data ? formatJaDate(data.date) : '今日'}
        showBack={false}
        sentence={heroSentence(data?.open_task_count ?? 0, data?.nearest_task_label ?? null)}
        metrics={[
          // 先頭2つはスマホでも残る。時間の2指標を先に置く（§4.0）
          // 研究＝10:00〜17:00 の空き／空き時間＝その外側の空き。合計しても1日にはならない
          { label: '研究にあてられる時間', value: `${data?.research_hours ?? 0}h` },
          { label: '空き時間', value: `${data?.free_hours ?? 0}h` },
          { label: '就活タスク', value: `${data?.open_task_count ?? 0}件` },
          { label: '要対応メール', value: `${data?.needs_reply_count ?? 0}通` },
        ]}
        status={
          toggle.isError ? <p className="hs">更新できませんでした：{toggle.error.message}</p> : null
        }
      />

      <div className="two today">
        <div className="col split">
          <section className="card">
            <h2>
              ✓ 今日やること
              {/* タスク一覧ページは今回のスコープ外（§4.6）。遷移させずに件数だけ見せる */}
              <span className="more co">全 {tasks.length}件</span>
            </h2>
            <div className="body scroll">
              {error && <p className="toast err">今日の情報を取得できませんでした：{error.message}</p>}
              {isLoading && <p className="toast">読み込み中…</p>}
              {!isLoading && !error && tasks.length === 0 && (
                <p className="empty">今日の就活タスクはありません。研究に集中できます。</p>
              )}

              {tasks.map((task) => (
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
                    <div className="co">{taskNote(task.due_at, task.is_done, data?.date ?? '')}</div>
                  </div>
                  {task.badge && (
                    <span className={BADGE_TAG_CLASS[task.badge] ?? 'tag'}>{task.badge}</span>
                  )}
                </div>
              ))}
            </div>
          </section>

          <section className="card">
            <h2>
              ✉ 今日返すべきメール
              <Link className="more" to="/inbox">
                受信箱 →
              </Link>
            </h2>
            <div className="body scroll">
              {!isLoading && !error && emails.length === 0 && (
                <p className="empty">返すべきメールはありません。</p>
              )}

              {emails.map((mail) => (
                <div className="task" key={mail.id}>
                  <span className={CATEGORY_TAG_CLASS[mail.category] ?? 'tag'}>{mail.category}</span>
                  <div className="t">
                    {mail.subject}
                    <div className="co">
                      {mail.company_name ?? mail.from_name ?? '送信元不明'}・
                      {formatHm(mail.received_at)}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </section>
        </div>

        <section className="card">
          <h2>
            ▣ 今日のタイムライン
            <Link className="more" to="/calendar">
              カレンダー →
            </Link>
          </h2>
          <div className="body scroll">
            {!isLoading && !error && timeline.length === 0 && (
              <p className="empty">今日の予定はありません。</p>
            )}
            <div className="tl">
              {timeline.map((row) => (
                <div className="slot" key={row.key}>
                  <span className="hh">{row.time}</span>
                  <div className={EV_CLASS[row.variant]}>
                    {row.label}
                    {row.note && <div className="co">{row.note}</div>}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </section>
      </div>
    </Shell>
  )
}
