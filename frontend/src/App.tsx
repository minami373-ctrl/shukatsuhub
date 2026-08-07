/** ルーティング（docs/spec.md §4「画面は5枚」）。
 *
 *  上部タブは 今日 / カレンダー / 受信箱 の3つ。プロフィールと想定問答は右パネルから。
 *  カレンダーと受信箱はページ側で Shell を描画する。プロフィールは Shell を持たないので
 *  ここで包む（job-dashboard 側の作法をそのまま持ち込まないため）。
 */

import { Route, Routes } from 'react-router-dom'

import { Shell } from './components/Shell'
import CalendarPage from './pages/Calendar'
import CompaniesPage from './pages/Companies'
import { InboxPage } from './pages/InboxPage'
import { KnowledgePage } from './pages/Knowledge'
import ResearchPage from './pages/Research'
import PipelinePage from './pages/Pipeline'
import { ProfilePage } from './pages/Profile'
import { QAPage } from './pages/QA'
import TasksPage from './pages/Tasks'
import TodayPage from './pages/Today'

function ProfileRoute() {
  return (
    <Shell current="profile">
      {/* 充実度は右パネルが GET /api/profile から直接取るので、ここでは受け取らない */}
      <ProfilePage onCompletenessChange={() => {}} />
    </Shell>
  )
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<TodayPage />} />
      <Route path="/calendar" element={<CalendarPage />} />
      <Route path="/inbox" element={<InboxPage />} />
      <Route path="/profile" element={<ProfileRoute />} />
      <Route path="/tasks" element={<TasksPage />} />
      {/* 企業研究の情報収集。パスは DESIGN_RULES §2 の配列に合わせて /interview のまま */}
      <Route path="/interview" element={<ResearchPage />} />
      <Route path="/pipeline" element={<PipelinePage />} />
      <Route path="/companies" element={<CompaniesPage />} />
      <Route
        path="/qa"
        element={
          <Shell current="qa">
            <QAPage />
          </Shell>
        }
      />
      <Route
        path="/knowledge"
        element={
          <Shell current="knowledge">
            <KnowledgePage />
          </Shell>
        }
      />
    </Routes>
  )
}
