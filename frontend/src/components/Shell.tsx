/** 全画面共通のシェル（docs/spec.md §4.0。案03。変更禁止）。
 *
 *  上部タブは「今日 / カレンダー / 受信箱」の3つに固定。増やさない。
 *  残り9機能は右パネル（☰ 機能）に入れる。開閉は body.nav-open の付け外しのみ。
 */

import { useEffect, useState, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, useNavigate } from 'react-router-dom'

import { getEmails } from '../api/emails'
import { FeaturePanel } from './FeaturePanel'

export type PageKey =
  | 'today'
  | 'calendar'
  | 'inbox'
  | 'profile'
  | 'qa'
  | 'tasks'
  | 'knowledge'
  | 'pipeline'
  | 'companies'
  | 'research'

type Props = {
  current: PageKey
  children: ReactNode
}

// タブを見ていない間も件数の増加に気づけるようにするための間隔（ミリ秒）。
const NOTIFICATION_POLL_MS = 30_000
// 正午を過ぎたかどうかを定期的に見に行く間隔（ミリ秒）。タブを開かないまま正午をまたいでも気づけるように。
const NOON_CHECK_MS = 60_000
// 件数が変わらない場合の再通知は「正午（この時）を過ぎたら1日1回」に限定する。
const NOON_HOUR = 12

function hasPassedNoon(): boolean {
  return new Date().getHours() >= NOON_HOUR
}

function todayKey(): string {
  return new Date().toDateString()
}

// モジュールスコープに置く（コンポーネントの外）。Shell は今日／カレンダー／受信箱などの
// ページ遷移のたびに App.tsx 側で unmount → mount されるため、コンポーネント内の useRef では
// 「今日はもう通知した」という記憶がページ移動のたびに消えてしまう（ページを移動しただけで
// 何度も再通知される不具合の原因だった）。ページ遷移をまたいで保持したいのでここに置く。
const notificationMemory = {
  hasNotifiedOnce: false,
  previousImportantCount: 0,
  lastNoonNotifiedDate: null as string | null,
}

export function Shell({ current, children }: Props) {
  const navigate = useNavigate()
  const [navOpen, setNavOpen] = useState(false)
  // 受信箱の要対応件数バッジ。GET /api/emails は受信箱担当の実装範囲なのでここで取得する。
  const { data } = useQuery({ queryKey: ['emails', undefined], queryFn: () => getEmails() })
  // 通知①：重要メール検知バナー（docs/spec.md §5.7①）。新しい判定は作らず既存の category を数えるだけ。
  // タブが非フォーカスでも検知できるよう、一定間隔でバックグラウンドでも再取得する。
  const { data: importantData } = useQuery({
    queryKey: ['emails', '重要'],
    queryFn: () => getEmails('重要'),
    refetchInterval: NOTIFICATION_POLL_MS,
    refetchIntervalInBackground: true,
  })
  const importantCount = importantData?.total_count ?? 0

  // ブラウザのデスクトップ通知許可を一度だけ求める（タブを見ていなくても気づけるようにするため）。
  useEffect(() => {
    if (typeof Notification !== 'undefined' && Notification.permission === 'default') {
      Notification.requestPermission()
    }
  }, [])

  // 通知の条件は「タブを見ているか」には依存させない（タブ切り替え自体をきっかけにしない）。
  // ①アプリを開いて最初の1回は必ず通知 ②件数が増えたら即時に通知 ③件数が変わらなければ正午に1日1回通知。
  // 記憶は notificationMemory（モジュールスコープ）に持ち、ページ遷移で Shell が再マウントされても消えない。
  useEffect(() => {
    const canNotify = () =>
      typeof Notification !== 'undefined' && Notification.permission === 'granted'

    function notify(count: number) {
      const notification = new Notification('ShukatsuHub', {
        body: `重要なメールが${count}件あります`,
      })
      // クリックでウィンドウを前面に出し、受信箱へ遷移する。
      notification.onclick = () => {
        window.focus()
        navigate('/inbox')
        notification.close()
      }
    }

    // ①②③は優先順位付きの一本の判定にする（同時に2つ発火しないようにするため）。
    // タブ切り替え・定期チェックなど複数の経路から呼ばれても、呼ばれた瞬間に
    // previousImportantCount を更新するので、同じ増加を2回通知することはない。
    function checkAndNotify() {
      if (importantCount === 0 || !canNotify()) return

      const increased = importantCount > notificationMemory.previousImportantCount
      notificationMemory.previousImportantCount = importantCount

      if (!notificationMemory.hasNotifiedOnce) {
        // ①アプリを開いて最初の1回は、件数の増減に関係なく必ず通知する。
        notify(importantCount)
        notificationMemory.hasNotifiedOnce = true
        // 今日はもう通知したので、正午通知（③）の分もここで消費しておく（二重発火を防ぐ）。
        if (hasPassedNoon()) notificationMemory.lastNoonNotifiedDate = todayKey()
        return
      }

      if (increased) {
        // ②件数が増えたときは、その場で必ず通知する。
        notify(importantCount)
        return
      }

      // ③件数が変わらない場合：正午を過ぎていて、今日はまだ送っていないときだけ。
      if (hasPassedNoon() && notificationMemory.lastNoonNotifiedDate !== todayKey()) {
        notify(importantCount)
        notificationMemory.lastNoonNotifiedDate = todayKey()
      }
    }

    checkAndNotify()
    // 正午をまたぐタイミングを取りに行くため、タブの表示状態に関係なく定期的に確認する。
    const noonCheckId = window.setInterval(checkAndNotify, NOON_CHECK_MS)
    // タブ切り替え（表示に戻ってきたときなど）でも即座に再確認できるようにする。
    document.addEventListener('visibilitychange', checkAndNotify)

    return () => {
      window.clearInterval(noonCheckId)
      document.removeEventListener('visibilitychange', checkAndNotify)
    }
  }, [importantCount])

  useEffect(() => {
    document.body.classList.toggle('nav-open', navOpen)
    return () => document.body.classList.remove('nav-open')
  }, [navOpen])

  return (
    <div className="page">
      <header>
        <div className="hd">
          <div className="logo">
            Shukatsu<b>Hub</b>
          </div>
          <nav className="tabs">
            <Link className={current === 'today' ? 'on' : ''} to="/">
              今日
            </Link>
            <Link className={current === 'calendar' ? 'on' : ''} to="/calendar">
              カレンダー
            </Link>
            <Link className={current === 'inbox' ? 'on' : ''} to="/inbox">
              受信箱
              {data && data.needs_reply_count > 0 && <span className="bd">{data.needs_reply_count}</span>}
            </Link>
          </nav>
          <button className="burger" type="button" onClick={() => setNavOpen(true)}>
            ☰<span className="lb">機能</span>
          </button>
          <div className="avatar">佐</div>
        </div>
        {importantCount > 0 && (
          <Link className="mail-alert" to="/inbox">
            ⚠ 重要なメールが{importantCount}件あります
          </Link>
        )}
      </header>

      <main className="content">{children}</main>

      {/* eslint-disable-next-line jsx-a11y/click-events-have-key-events */}
      <div className="scrim" onClick={() => setNavOpen(false)} />
      <FeaturePanel current={current} onClose={() => setNavOpen(false)} />
    </div>
  )
}
