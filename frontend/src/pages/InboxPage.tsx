/** 受信箱画面（docs/spec.md §4.3）。
 *
 *  目的：gmail と iCloud のメールを1つの箱で見て、返すべきものを先に見つける。
 *  分類は件名の内容（キーワード＋AIフォールバック）のみで決まる（送信元ドメインは使わない）。
 */

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { getEmails } from '../api/emails'
import { useGmailStatus, useStartGmailAuth, useSyncGmail } from '../api/gmail'
import { Hero } from '../components/Hero'
import { Shell } from '../components/Shell'

const FILTERS: { value: string | undefined; label: string }[] = [
  { value: undefined, label: 'すべて' },
  { value: '重要', label: '重要' },
  { value: '確認', label: '確認' },
  { value: '広告', label: '広告' },
]

const CATEGORY_TAG_CLASS: Record<string, string> = {
  重要: 'tag d',
  確認: 'tag w',
  広告: 'tag',
}

// services/classifier.py のキーワードと一致させる（件名の内容のみで判定。送信元は見ない）
const CLASSIFICATION_RULES: { category: string; keywords: string }[] = [
  { category: '重要', keywords: '面接・日程・選考結果・内定・お祈り・最終' },
  { category: '広告', keywords: '配信停止・メルマガ・セミナー案内・PR・スカウト・おすすめ求人' },
  { category: '確認', keywords: 'ES・エントリーシート・提出・期限・リマインド・説明会' },
]

function formatTime(iso: string): string {
  const date = new Date(iso)
  return `${date.getMonth() + 1}/${date.getDate()} ${String(date.getHours()).padStart(2, '0')}:${String(
    date.getMinutes(),
  ).padStart(2, '0')}`
}

export function InboxPage() {
  const [filter, setFilter] = useState<string | undefined>(undefined)
  const [expandedThread, setExpandedThread] = useState<string | null>(null)

  const { data: allData } = useQuery({ queryKey: ['emails', undefined], queryFn: () => getEmails() })
  const { data: filteredData } = useQuery({ queryKey: ['emails', filter], queryFn: () => getEmails(filter) })

  // Gmail 実連携。未認可でも seed のメールが表示され続ける（デモが止まらない）
  const { data: gmailStatus } = useGmailStatus()
  const sync = useSyncGmail()
  const startAuth = useStartGmailAuth()
  // 認可から戻ってきた直後だけ出すトースト（/inbox?connected=1）
  const [searchParams] = useSearchParams()
  const justConnected = searchParams.get('connected') === '1'

  const oldestNeedsReply = allData?.groups
    .flatMap((g) => g.emails)
    .filter((e) => e.needs_reply)
    .sort((a, b) => a.received_at.localeCompare(b.received_at))[0]

  const sentence =
    allData && allData.needs_reply_count > 0 && oldestNeedsReply
      ? `今すぐ返すべきメールは ${allData.needs_reply_count}通。まず ${oldestNeedsReply.category} から。`
      : '今すぐ返すべきメールはありません。'

  return (
    <Shell current="inbox">
      <Hero
        pageName="受信箱"
        sentence={sentence}
        metrics={[
          { label: '要対応', value: `${allData?.needs_reply_count ?? 0}通` },
          { label: 'AI判定', value: `${allData?.ai_decided_count ?? 0}件` },
          { label: '全メール', value: `${allData?.total_count ?? 0}件` },
        ]}
      />
      <div className="two">
        <div className="card">
          <h2>
            ✉ 受信箱
            {/* 連携状態のバッジ。未連携のときはバッジ自体がリンクになる
                （ボタンにしないのは「主要アクションは1画面に1つ」を崩さないため） */}
            {gmailStatus?.connected ? (
              <span className="tag">Gmail 連携中</span>
            ) : (
              <a
                className="tag g"
                href="#"
                onClick={(event) => {
                  event.preventDefault()
                  startAuth.mutate()
                }}
              >
                Gmail 未連携
              </a>
            )}
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

          {justConnected && <p className="toast">Gmail と連携しました</p>}
          {sync.isSuccess && (
            <p className="toast">
              {sync.data.source === 'gmail'
                ? `Gmail から 追加 ${sync.data.added}件 / 更新 ${sync.data.updated}件（AI判定 ${sync.data.ai_decided}件）`
                : 'Gmail 未連携のため seed のメールを表示しています'}
            </p>
          )}
          {sync.isError && <p className="toast err">同期に失敗しました：{sync.error.message}</p>}
          {startAuth.isError && (
            <p className="toast err">連携を開始できませんでした：{startAuth.error.message}</p>
          )}

          <div className="body scroll">
            <div className="chips">
              {FILTERS.map((f) => (
                <button
                  key={f.label}
                  className={filter === f.value ? 'on' : ''}
                  onClick={() => setFilter(f.value)}
                >
                  {f.label}
                </button>
              ))}
            </div>
            {filteredData && filteredData.groups.length === 0 && (
              <p className="empty">該当するメールはありません。</p>
            )}
            {filteredData?.groups.map((group) => (
              <div key={group.thread_key}>
                <div
                  className="task mail-group"
                  onClick={() =>
                    setExpandedThread(expandedThread === group.thread_key ? null : group.thread_key)
                  }
                >
                  <span className={CATEGORY_TAG_CLASS[group.category] ?? 'tag'}>{group.category}</span>
                  {group.has_ai_decided && <span className="tag ai">AI</span>}
                  <div className="t">
                    {group.subject}
                    <div className="co">
                      {group.company_name ?? group.domain} ・ {formatTime(group.latest_received_at)}
                    </div>
                  </div>
                  {group.accounts.map((account) => (
                    <span key={account} className="acct">
                      {account}
                    </span>
                  ))}
                  <span className="cnt">{group.count}通</span>
                </div>
                {expandedThread === group.thread_key && (
                  <div className="thread">
                    {group.emails.map((email) => (
                      <div key={email.id} className="mail">
                        {formatTime(email.received_at)}　{email.subject}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>

        <div className="card">
          <h2>
            ⚙ 分類ロジック
            <span className="more">
              AI判定 {allData?.ai_decided_count ?? 0}件 / 全 {allData?.total_count ?? 0}件
            </span>
          </h2>
          <div className="body">
            {CLASSIFICATION_RULES.map((rule) => (
              <div key={rule.category} className="rule-row">
                <span className={CATEGORY_TAG_CLASS[rule.category] ?? 'tag'}>{rule.category}</span>
                <span className="domain">{rule.keywords}</span>
              </div>
            ))}
            <p className="co">件名がどれにも一致しない場合はAIが判定します（送信元は判定に使いません）。</p>
          </div>
        </div>
      </div>
    </Shell>
  )
}
