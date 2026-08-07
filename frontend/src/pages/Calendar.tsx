/** カレンダー画面（docs/spec.md §4.2）。
 *
 *  目的：就活と学業の衝突を見つけ、空いている時間を把握する。
 *  - FullCalendar の 週（timeGrid）／月（dayGrid）をトグル。初期表示は週
 *  - 就活＝ティール／学業＝グレー（`kind` の値は `選考` のまま。表示ラベルだけ `就活`）
 *  - 予定をクリックすると読み取り専用の詳細モーダルが開く（枠に入りきらない予定名の全文を見る）
 *  - 主要アクションは `同期` の1つだけ（POST /api/calendar/sync。2回押しても増えない）
 */

import dayGridPlugin from '@fullcalendar/daygrid'
import FullCalendar from '@fullcalendar/react'
import timeGridPlugin from '@fullcalendar/timegrid'
import { useRef, useState } from 'react'

import {
  type ApiEvent,
  DAY_END_HOUR,
  DAY_START_HOUR,
  conflicts,
  countKind,
  heroSentence,
  researchHours,
  toCalendarEvents,
  toLocalIso,
} from '../api/eventMap'
import { useEvents, useSyncCalendar } from '../api/useEvents'
import { EventDialog } from '../components/EventDialog'
import { Hero } from '../components/Hero'
import { Shell } from '../components/Shell'

type ViewKey = 'timeGridWeek' | 'dayGridMonth'

export default function CalendarPage() {
  const calendarRef = useRef<FullCalendar | null>(null)
  const [view, setView] = useState<ViewKey>('timeGridWeek')
  // 2026-08-05 にチームで合意の上、基準日は固定値ではなく実際の今日の日付にした。
  // マウント時に一度だけ計算する（コンポーネント内に置くことでテストが日時を差し替えられる）。
  const [baseDate] = useState(() => toLocalIso(new Date()).slice(0, 10))
  const [range, setRange] = useState<{ from: string | null; to: string | null }>({
    from: null,
    to: null,
  })
  /** 詳細モーダルに出す予定。null なら閉じている */
  const [selected, setSelected] = useState<ApiEvent | null>(null)

  const { data: events = [], isLoading, error } = useEvents(range.from, range.to)
  const sync = useSyncCalendar()

  function switchView(next: ViewKey) {
    setView(next)
    calendarRef.current?.getApi().changeView(next)
  }

  const conflictCount = conflicts(events, baseDate).length

  return (
    <Shell current="calendar">
      <Hero
        pageName="カレンダー"
        sentence={heroSentence(events, baseDate)}
        metrics={[
          // TODO: タスク見積りを差し引いた正式な値は GET /api/today（今日画面担当）から取る
          { label: '研究にあてられる時間', value: `${researchHours(events, baseDate)}h` },
          { label: '衝突', value: `${conflictCount}件` },
          { label: '表示中の就活', value: `${countKind(events, '選考')}件` },
          { label: '表示中の学業', value: `${countKind(events, '学業')}件` },
        ]}
      />

      <div className="two">
        <section className="card cal-card">
          <h2>
            ▣ 予定
            <div className="seg">
              <button
                type="button"
                className={view === 'timeGridWeek' ? 'on' : ''}
                onClick={() => switchView('timeGridWeek')}
              >
                週
              </button>
              <button
                type="button"
                className={view === 'dayGridMonth' ? 'on' : ''}
                onClick={() => switchView('dayGridMonth')}
              >
                月
              </button>
            </div>
            <button
              className="primary"
              style={{ marginLeft: 'auto' }}
              type="button"
              onClick={() => sync.mutate()}
              disabled={sync.isPending}
            >
              {sync.isPending ? '同期中…' : '同期'}
            </button>
          </h2>

          <div className="legend">
            <span className="senko">
              <i />
              就活
            </span>
            <span className="gakugyo">
              <i />
              学業
            </span>
          </div>

          {sync.isSuccess && (
            <p className="toast">
              同期しました（追加 {sync.data.added}件 / 更新 {sync.data.updated}件）
            </p>
          )}
          {sync.isError && <p className="toast err">同期に失敗しました：{sync.error.message}</p>}
          {error && <p className="toast err">予定を取得できませんでした：{error.message}</p>}
          {isLoading && <p className="toast">読み込み中…</p>}

          <div className="cal-body">
            <FullCalendar
              ref={calendarRef}
              plugins={[timeGridPlugin, dayGridPlugin]}
              initialView="timeGridWeek"
              initialDate={baseDate}
              locale="ja"
              height="100%"
              headerToolbar={{ left: 'prev,next today', center: 'title', right: '' }}
              buttonText={{ today: '今週' }}
              firstDay={1}
              allDaySlot={false}
              slotMinTime={`${String(DAY_START_HOUR).padStart(2, '0')}:00:00`}
              slotMaxTime={`${String(DAY_END_HOUR).padStart(2, '0')}:00:00`}
              slotDuration="01:00:00"
              expandRows
              dayMaxEvents={3}
              events={toCalendarEvents(events)}
              // 表示範囲が変わるたびに、その期間のイベントを取り直す
              datesSet={(arg) => setRange({ from: toLocalIso(arg.start), to: toLocalIso(arg.end) })}
              // 枠が狭いので時刻と予定名を縦2段にし、予定名は CSS で2行まで省略する。
              // 全文は title 属性（PC のホバー）と詳細モーダルで確認できる
              eventContent={(arg) => (
                <div className="cal-ev" title={arg.event.title}>
                  <b className="cal-ev-time">{arg.timeText}</b>
                  <span className="cal-ev-title">{arg.event.title}</span>
                </div>
              )}
              // クリック（スマホはタップ）で詳細モーダル。API が返した予定をそのまま渡す
              eventClick={(arg) =>
                setSelected(events.find((e) => String(e.id) === arg.event.id) ?? null)
              }
            />
          </div>
        </section>
      </div>

      <EventDialog event={selected} onClose={() => setSelected(null)} />
    </Shell>
  )
}
