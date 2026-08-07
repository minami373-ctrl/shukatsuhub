/** プロフィールの純ロジック（spec.md §4.4 / §5.5）。
 *  充実度とヒーローの1文はここだけで組み立てる。Vitest の検証対象。 */

export type ProfileFields = {
  gakuchika: string
  strengths: string
  self_pr: string
  academics: string
  teamwork: string
  skills: string
  motivation_template: string
  career_plan: string
  job_axis: string
}

export type ProfileResponse = ProfileFields & { completeness: number }

export type FieldName = keyof ProfileFields

/** 9項目の定義。順序は spec.md §4.4 の表示順（3列 × 3行。行ごとに意味をそろえる）。
 *  1行目＝自分 ／ 2行目＝経験と力 ／ 3行目＝志望 */
export const PROFILE_FIELDS: { name: FieldName; label: string; placeholder: string }[] = [
  { name: 'gakuchika', label: 'ガクチカ', placeholder: '学生時代に力を入れたこと' },
  { name: 'strengths', label: '強み', placeholder: '強みと、それを示す具体例' },
  { name: 'self_pr', label: '自己PR', placeholder: 'ES やマイページに使い回す自己PR' },
  { name: 'academics', label: '学業', placeholder: '研究テーマ・使っている技術' },
  { name: 'teamwork', label: 'チームで活動した経験', placeholder: '役割・工夫したこと・結果' },
  { name: 'skills', label: '資格・スキル', placeholder: '資格・スコア・使える技術' },
  { name: 'motivation_template', label: '志望動機テンプレ', placeholder: '企業名を差し替えて使う下書き' },
  { name: 'career_plan', label: 'キャリアプラン', placeholder: '入社後にやりたいこと・将来像' },
  { name: 'job_axis', label: '就活軸', placeholder: 'カンマ区切り（例: 裁量,技術力,勤務地）' },
]

export const EMPTY_PROFILE: ProfileFields = {
  gakuchika: '',
  strengths: '',
  self_pr: '',
  academics: '',
  teamwork: '',
  skills: '',
  motivation_template: '',
  career_plan: '',
  job_axis: '',
}

/** API のレスポンスから9項目だけを取り出す（completeness は導出値なので持ち回らない）。
 *  項目を足したときの取りこぼしを防ぐため PROFILE_FIELDS から組み立てる。 */
export function pickFields(profile: ProfileFields): ProfileFields {
  return Object.fromEntries(
    PROFILE_FIELDS.map(({ name }) => [name, profile[name]]),
  ) as ProfileFields
}

/** 2つのプロフィールの9項目が同一か。未保存の変更があるかの判定に使う。 */
export function isSameProfile(a: ProfileFields, b: ProfileFields): boolean {
  return PROFILE_FIELDS.every(({ name }) => a[name] === b[name])
}

/** 空でない項目（前後の空白を除いて判定。spec.md §5.5 補足）。 */
export function filledFields(profile: ProfileFields): FieldName[] {
  return PROFILE_FIELDS.filter(({ name }) => profile[name].trim() !== '').map(({ name }) => name)
}

/** 未入力項目の日本語ラベル。 */
export function unfilledLabels(profile: ProfileFields): string[] {
  const filled = new Set(filledFields(profile))
  return PROFILE_FIELDS.filter(({ name }) => !filled.has(name)).map(({ label }) => label)
}

/** 充実度%（空でない項目数 ÷ 9 の四捨五入）。バックエンドの completeness() と同じ規則。 */
export function completeness(profile: ProfileFields): number {
  return Math.round((filledFields(profile).length / PROFILE_FIELDS.length) * 100)
}

/** ヒーローの1文（spec.md §4.4）。件数の羅列ではなく次の行動を示す。 */
export function heroSentence(profile: ProfileFields): string {
  const unfilled = unfilledLabels(profile)
  if (unfilled.length === 0) {
    return 'プロフィールは埋まっています。想定問答の準備に進めます。'
  }
  return `未入力は「${unfilled.join('・')}」だけ。埋めれば想定問答が作れます。`
}
