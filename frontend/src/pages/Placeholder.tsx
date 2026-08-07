/** 他メンバーが担当する画面の仮置き。
 *
 *  タブとパネルの遷移を今から確認できるようにするための最小実装。
 *  各担当者はこのファイルを使わず、docs/spec.md §4 に従って自分のページを作る
 *  （Shell と Hero はそのまま流用する）。
 */

import { Hero } from '../components/Hero'
import { Shell, type PageKey } from '../components/Shell'

type Props = {
  page: PageKey
  pageName: string
  owner: string
  specSection: string
}

export function Placeholder({ page, pageName, owner, specSection }: Props) {
  return (
    <Shell current={page}>
      <Hero
        pageName={pageName}
        sentence={`${pageName}はまだ実装されていません。`}
        metrics={[
          { label: '研究にあてられる時間', value: '—' },
          { label: '担当', value: owner },
        ]}
        showBack={page !== 'today'}
      />
      <div className="two">
        <section className="card">
          <h2>この画面について</h2>
          <div className="body">
            <p className="co">
              仕様は docs/spec.md {specSection} に定義済み。担当者が実装します。
            </p>
          </div>
        </section>
      </div>
    </Shell>
  )
}
