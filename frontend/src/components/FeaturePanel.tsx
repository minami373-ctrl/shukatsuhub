/** 右パネル（☰ 機能）。docs/spec.md §4.0 / §2「右パネルに出す 7 機能」。
 *
 *  各項目にサブテキストを出す（開かずに状況が分かるのが案03の核）。
 *  現在ページの項目に `.on` を付ける。
 *
 *  2026-08-05 に `通知` と `メール自動振り分け` をパネルから外した（当初は9件）。
 *  通知は上部のバナー（Shell）、メールの自動振り分けは上部タブの `受信箱` が入口で、
 *  同じ機能への入口を2つ置かないため。
 */

import { Link } from 'react-router-dom'

import { useKnowledge } from '../api/knowledge'
import { useProfile } from '../api/profile'
import { useCompanies, useQASheet } from '../api/qa'
import { useResearch } from '../api/research'
import type { PageKey } from './Shell'

type PanelItem = {
  icon: string
  label: string
  sub: string
  group: string
  to?: string
  page?: PageKey
}

// TODO: サブテキストは GET /api/panel（seed/panel.json の固定値）に差し替える。
//       /api/panel は受信箱・プロフィール担当の実装範囲なので、現状はモックと同じ固定値を置く。
const ITEMS: PanelItem[] = [
  {
    group: '進行管理',
    icon: '✓',
    label: 'タスク・締め切り',
    // サブテキストの実データ化は GET /api/panel の担当範囲なので固定値のまま置く（TODO 上記）
    sub: '今日 5件・期限切れ 1件',
    to: '/tasks',
    page: 'tasks',
  },
  {
    group: '進行管理',
    icon: '▤',
    label: '選考ステータス管理',
    // サブテキストの実データ化は GET /api/panel の担当範囲なので固定値のまま置く（TODO 上記）
    sub: '選考中 18社',
    to: '/pipeline',
    page: 'pipeline',
  },
  {
    group: '準備・分析',
    icon: '◉',
    label: 'プロフィール・自己分析',
    sub: '', // 実データ（充実度）を下で差し込む
    to: '/profile',
    page: 'profile',
  },
  {
    group: '準備・分析',
    icon: '？',
    label: '想定問答',
    sub: '', // 実データ（先頭企業の準備率）を下で差し込む（§2）
    to: '/qa',
    page: 'qa',
  },
  {
    group: '準備・分析',
    icon: '◎',
    // DESIGN_RULES §2 の配列では「面接対策収集」。企業研究に置き換えたので表示名を変える
    // （配列側の名称変更は人の承認待ち。パスは /interview のまま）
    label: '企業研究',
    sub: '', // 実データ（集めた情報・未確認の観点）を下で差し込む
    to: '/interview',
    page: 'research',
  },
  {
    group: '準備・分析',
    icon: '▧',
    label: 'ナレッジ蓄積',
    sub: '', // 実データ（メモ件数）を下で差し込む
    to: '/knowledge',
    page: 'knowledge',
  },
  {
    group: '準備・分析',
    icon: '◇',
    label: '企業の発見・マッチング',
    // サブテキストの実データ化は GET /api/panel の担当範囲なので固定値のまま置く（TODO 上記）
    sub: 'おすすめ 12社',
    to: '/companies',
    page: 'companies',
  },
]

type Props = {
  current: PageKey
  onClose: () => void
}

export function FeaturePanel({ current, onClose }: Props) {
  // プロフィールと想定問答は実データがあるので、固定値ではなく実際の数値を出す（§2）。
  // 想定問答は画面と同じく先頭の企業を見る（QA 画面の初期選択と一致させる）。
  const { data: profile } = useProfile()
  const { data: companies } = useCompanies()
  const firstCompany = companies?.[0] ?? null
  // 企業研究は画面と同じく先頭の企業を見る（Research 画面の初期選択と一致させる）
  const { data: research } = useResearch(firstCompany?.id ?? null)
  const { data: qaSheet } = useQASheet(firstCompany?.id ?? null)
  const { data: knowledgeNotes } = useKnowledge()
  let lastGroup = ''

  const qaSub =
    firstCompany === null
      ? '企業が未登録です'
      : qaSheet && qaSheet.items.length > 0
        ? `${firstCompany.name} ${qaSheet.prepared_rate}%`
        : `${firstCompany.name} 未生成`

  return (
    <aside className="panel">
      <div className="ph">
        すべての機能
        <button className="x" type="button" onClick={onClose} aria-label="閉じる">
          ✕
        </button>
      </div>
      <div className="cap">上部タブの3つ以外はここから</div>

      {ITEMS.map((item) => {
        const heading = item.group === lastGroup ? null : <div className="grp">{item.group}</div>
        lastGroup = item.group
        const sub =
          item.page === 'profile'
            ? `充実度 ${profile?.completeness ?? 0}%`
            : item.page === 'qa'
              ? qaSub
              : item.page === 'knowledge'
                ? `メモ ${knowledgeNotes?.length ?? 0}件`
                : item.page === 'research'
                  ? research?.report
                    ? `${research.company_name} 済・未確認 ${research.unchecked}点`
                    : '未収集'
                  : item.sub
        const body = (
          <>
            <span className="ico">{item.icon}</span>
            <div>
              {item.label}
              <span className="sub">{sub}</span>
            </div>
          </>
        )

        return (
          <div key={item.label}>
            {heading}
            {item.to ? (
              <Link
                className={`item${item.page === current ? ' on' : ''}`}
                to={item.to}
                onClick={onClose}
              >
                {body}
              </Link>
            ) : (
              // 遷移先の無い項目。現在は7件すべてに遷移先があるので通らないが、
              // 項目を足すときに href="#" で置ける形は残しておく（§2）
              <a className="item disabled" href="#" onClick={(e) => e.preventDefault()}>
                {body}
              </a>
            )}
          </div>
        )
      })}
    </aside>
  )
}
