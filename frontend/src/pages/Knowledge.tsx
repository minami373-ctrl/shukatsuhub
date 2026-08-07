/** ナレッジ蓄積 /knowledge（03-today-focus/FEATURE_PAGE_SPECS.md §11）。
 *
 *  目的：面接の振り返りや企業メモを1か所に貯め、次の想定問答づくりに活かす。
 *  - フィルタ：面接振り返り / 企業メモ / テンプレート / 学び
 *  - 左：メモ一覧（カード内スクロールで全件）／右：選択中メモの本文＋「想定問答に反映する →」
 *  - 主要アクションは「＋ メモを追加」の1つだけ（ネイティブ <dialog> で完結させる）
 *  - 想定問答（QA）への自動反映は今回作らない。導線（リンク）だけ用意する
 */

import { useEffect, useRef, useState } from 'react'

import {
  useAddKnowledge,
  useKnowledge,
  type KnowledgeCategory,
  type NewKnowledgeNote,
} from '../api/knowledge'
import { useCompanies } from '../api/qa'
import { useToday } from '../api/today'
import { Hero } from '../components/Hero'

const CATEGORIES: KnowledgeCategory[] = ['面接振り返り', '企業メモ', 'テンプレート', '学び']

function formatDate(iso: string): string {
  const date = new Date(iso)
  return `${date.getMonth() + 1}/${date.getDate()}`
}

export function KnowledgePage() {
  const [filter, setFilter] = useState<KnowledgeCategory | undefined>(undefined)
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [dialogOpen, setDialogOpen] = useState(false)

  const today = useToday()
  const companies = useCompanies()
  const notes = useKnowledge(filter)
  const addNote = useAddKnowledge()

  const list = notes.data ?? []
  const selected = list.find((n) => n.id === selectedId) ?? list[0] ?? null
  const reflectionCount = list.filter((n) => n.category === '面接振り返り').length

  const sentence =
    list.length === 0
      ? 'まだメモがありません。面接の振り返りから書いてみましょう。'
      : `メモは${list.length}件。振り返りは${reflectionCount}件あります。`

  return (
    <>
      <Hero
        pageName="ナレッジ"
        sentence={sentence}
        metrics={[
          {
            label: '研究にあてられる時間',
            value: today.data ? `${today.data.research_hours}h` : '—',
          },
          { label: 'メモ', value: `${list.length}件` },
          { label: '振り返り', value: `${reflectionCount}件` },
          { label: '企業メモ', value: `${list.filter((n) => n.category === '企業メモ').length}件` },
        ]}
        action={
          <button className="primary" type="button" onClick={() => setDialogOpen(true)}>
            ＋ メモを追加
          </button>
        }
      />

      <div className="two">
        <section className="card">
          <h2>▧ メモ一覧</h2>
          <div className="body scroll">
            <div className="chips">
              <button className={filter === undefined ? 'on' : ''} onClick={() => setFilter(undefined)}>
                すべて
              </button>
              {CATEGORIES.map((c) => (
                <button key={c} className={filter === c ? 'on' : ''} onClick={() => setFilter(c)}>
                  {c}
                </button>
              ))}
            </div>
            {notes.isPending && <p className="toast">読み込み中…</p>}
            {!notes.isPending && list.length === 0 && (
              <p className="empty">該当するメモはありません。</p>
            )}
            {list.map((note) => (
              <div
                key={note.id}
                className={['task', note.id === selected?.id && 'sel'].filter(Boolean).join(' ')}
                onClick={() => setSelectedId(note.id)}
              >
                <span className="tag">{note.category}</span>
                <div className="t">
                  {note.title}
                  <div className="co">
                    {note.company_name ?? '企業紐付けなし'} ・ {formatDate(note.updated_at)}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </section>

        <section className="card">
          <h2>◎ メモの内容</h2>
          <div className="body scroll">
            {selected ? (
              <>
                <p className="co">
                  {selected.category} ／ {selected.company_name ?? '企業紐付けなし'}
                </p>
                <p style={{ whiteSpace: 'pre-wrap' }}>{selected.content}</p>
              </>
            ) : (
              <p className="empty">メモを選ぶと、ここに内容が表示されます。</p>
            )}
          </div>
        </section>
      </div>

      <KnowledgeDialog
        open={dialogOpen}
        companies={companies.data ?? []}
        saving={addNote.isPending}
        error={addNote.error?.message ?? null}
        onSubmit={(note) => {
          addNote.mutate(note, { onSuccess: () => setDialogOpen(false) })
        }}
        onClose={() => setDialogOpen(false)}
      />
    </>
  )
}

type DialogProps = {
  open: boolean
  companies: { id: number; name: string }[]
  saving: boolean
  error: string | null
  onSubmit: (note: NewKnowledgeNote) => void
  onClose: () => void
}

function KnowledgeDialog({ open, companies, saving, error, onSubmit, onClose }: DialogProps) {
  const ref = useRef<HTMLDialogElement>(null)
  const [title, setTitle] = useState('')
  const [category, setCategory] = useState<KnowledgeCategory>('面接振り返り')
  const [companyId, setCompanyId] = useState<number | ''>('')
  const [content, setContent] = useState('')

  useEffect(() => {
    if (!open) {
      ref.current?.close()
      return
    }
    // 開くたびに空の状態に戻す（前回の入力を持ち越さない）
    setTitle('')
    setCategory('面接振り返り')
    setCompanyId('')
    setContent('')
    if (!ref.current?.open) ref.current?.showModal()
  }, [open])

  // バックエンド（routers/knowledge.py）はタイトルだけを必須にしている。内容は空でも保存できる
  const canSave = title.trim() !== '' && !saving

  return (
    <dialog className="dlg" ref={ref} onCancel={onClose} aria-label="メモを追加">
      <form
        method="dialog"
        onSubmit={(e) => {
          e.preventDefault()
          if (!canSave) return
          onSubmit({
            title: title.trim(),
            category,
            company_id: companyId === '' ? null : companyId,
            content: content.trim(),
          })
        }}
      >
        <h2>メモを追加</h2>

        <label>
          タイトル
          <input
            autoFocus
            maxLength={200}
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="一次面接 振り返り"
          />
        </label>

        <label>
          カテゴリ
          <select value={category} onChange={(e) => setCategory(e.target.value as KnowledgeCategory)}>
            {CATEGORIES.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </label>

        <label>
          企業（任意）
          <select
            value={companyId}
            onChange={(e) => setCompanyId(e.target.value === '' ? '' : Number(e.target.value))}
          >
            <option value="">紐付けなし</option>
            {companies.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        </label>

        <label>
          内容
          <textarea
            className="ta"
            rows={4}
            value={content}
            onChange={(e) => setContent(e.target.value)}
            placeholder="・逆算質問が多かった&#10;・研究内容を3分で説明できるよう準備"
          />
        </label>

        {error && <p className="toast err">{error}</p>}

        <div className="dlg-act">
          <button className="mini" type="button" onClick={onClose} disabled={saving}>
            キャンセル
          </button>
          <button className="primary" type="submit" disabled={!canSave}>
            {saving ? '保存中…' : '保存'}
          </button>
        </div>
      </form>
    </dialog>
  )
}
