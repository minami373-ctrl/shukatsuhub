export type Email = {
  id: number
  account: string
  from_address: string
  from_name: string
  subject: string
  body: string
  received_at: string
  category: string
  needs_reply: boolean
  decided_by: string
  company_id: number | null
  thread_key: string
}

export type EmailGroup = {
  thread_key: string
  company_name: string | null
  domain: string
  subject: string
  count: number
  latest_received_at: string
  category: string
  accounts: string[]
  has_ai_decided: boolean
  emails: Email[]
}

export type EmailsResponse = {
  groups: EmailGroup[]
  ai_decided_count: number
  needs_reply_count: number
  total_count: number
}

export async function getEmails(category?: string): Promise<EmailsResponse> {
  const query = category ? `?category=${encodeURIComponent(category)}` : ''
  const response = await fetch(`/api/emails${query}`)
  if (!response.ok) {
    throw new Error('メールの取得に失敗しました')
  }
  return response.json()
}
