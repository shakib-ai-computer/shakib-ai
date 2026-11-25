// SHAKIB AI Core API client.
//
// The browser talks ONLY to Core (http://localhost:8000 by default, or
// VITE_API_BASE). No provider/gateway keys ever appear in frontend code:
// the gateway key is server-side in Core, and user provider keys are sent
// once to POST /api/settings/keys (write-only — the API never returns them).
//
// Errors are surfaced verbatim: FastAPI's `detail` string (including the
// backend's 503 "not configured" explanations) becomes ApiError.message so
// the UI can show exactly what the server said instead of fake data.

export const API_BASE: string =
  (import.meta.env.VITE_API_BASE as string | undefined) ?? 'http://localhost:8000'

const TOKEN_KEY = 'shakib_token'

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(token: string | null): void {
  if (token) localStorage.setItem(TOKEN_KEY, token)
  else localStorage.removeItem(TOKEN_KEY)
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function parseError(res: Response): Promise<ApiError> {
  let detail = ''
  try {
    const body: unknown = await res.json()
    if (typeof body === 'object' && body !== null && 'detail' in body) {
      const d = (body as { detail: unknown }).detail
      if (typeof d === 'string') detail = d
      else if (Array.isArray(d)) {
        // FastAPI validation errors: [{loc, msg, ...}, ...]
        detail = d
          .map((item) => {
            if (typeof item === 'object' && item !== null && 'msg' in item) {
              return String((item as { msg: unknown }).msg)
            }
            return JSON.stringify(item)
          })
          .join('; ')
      } else detail = JSON.stringify(d)
    }
  } catch {
    detail = ''
  }
  if (!detail) detail = `request failed (HTTP ${res.status})`
  return new ApiError(res.status, detail)
}

interface RequestOptions {
  method?: string
  body?: unknown
  form?: FormData
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = {}
  const token = getToken()
  if (token) headers['Authorization'] = `Bearer ${token}`
  let body: BodyInit | undefined
  if (options.form) {
    body = options.form
  } else if (options.body !== undefined) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(options.body)
  }
  let res: Response
  try {
    res = await fetch(`${API_BASE}${path}`, {
      method: options.method ?? 'GET',
      headers,
      body,
    })
  } catch {
    throw new ApiError(0, `cannot reach SHAKIB AI Core at ${API_BASE} — is the backend running?`)
  }
  if (!res.ok) throw await parseError(res)
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

// ---------------------------------------------------------------- health
export interface Health {
  status: string
  service: string
  version: string
  gateway_configured: boolean
  research_configured: boolean
  auth_required: boolean
}

export const getHealth = () => request<Health>('/health')

// ------------------------------------------------------------------ auth
export interface TokenResponse {
  access_token: string
  token_type: string
  user_id: number
  email: string
}

export interface MeResponse {
  user_id: number
  email: string
  created_at: string | null
}

export const register = (email: string, password: string) =>
  request<TokenResponse>('/api/auth/register', { method: 'POST', body: { email, password } })

export const login = (email: string, password: string) =>
  request<TokenResponse>('/api/auth/login', { method: 'POST', body: { email, password } })

export const getMe = () => request<MeResponse>('/api/auth/me')

// ------------------------------------------------------------------ chat
export interface ChatMessage {
  role: string
  content: string
}

export interface ChatChoice {
  message: { role: string; content: string }
}

export interface ChatResponse {
  id?: string
  model?: string
  choices: ChatChoice[]
}

export type ModelRole = 'fast' | 'smart' | 'strategic'

export const sendChat = (messages: ChatMessage[], role: ModelRole) =>
  request<ChatResponse>('/api/chat/', { method: 'POST', body: { messages, role } })

export interface ChatModels {
  gateway_configured: boolean
  roles: Record<string, string[]>
  gateway_models: unknown
  gateway_error?: string
}

export const getChatModels = () => request<ChatModels>('/api/chat/models')

// --------------------------------------------------------- conversations
export interface Conversation {
  id: number
  title: string
  created_at: string | null
  updated_at: string | null
}

export interface StoredMessage {
  id: number
  conversation_id: number
  role: string
  content: string
  created_at: string | null
}

export interface ConversationDetail extends Conversation {
  messages: StoredMessage[]
}

export const listConversations = () =>
  request<{ conversations: Conversation[] }>('/api/conversations/')

export const createConversation = (title: string) =>
  request<Conversation>('/api/conversations/', { method: 'POST', body: { title } })

export const getConversation = (id: number) =>
  request<ConversationDetail>(`/api/conversations/${id}`)

export const addConversationMessage = (id: number, role: string, content: string) =>
  request<StoredMessage>(`/api/conversations/${id}/messages`, {
    method: 'POST',
    body: { role, content },
  })

export const deleteConversation = (id: number) =>
  request<void>(`/api/conversations/${id}`, { method: 'DELETE' })

// -------------------------------------------------------------- research
export interface ResearchSource {
  url: string
  title?: string
  credibility_score?: number
  credibility_reasons?: string[]
  [key: string]: unknown
}

export interface ContradictionPair {
  claim_a: string
  claim_b: string
  explanation: string
}

export interface ContradictionResult {
  status: 'ok' | 'skipped' | 'error' | string
  reason?: string
  claims_checked?: number
  contradictions?: ContradictionPair[]
}

export interface ResearchResult {
  run_id: string
  report_markdown: string
  sources: ResearchSource[]
  contradiction: ContradictionResult
  costs: unknown
  meta: Record<string, unknown>
}

export type ResearchLanguage = 'en' | 'bn'

export const runResearch = (query: string, language: ResearchLanguage, reportType: string) =>
  request<ResearchResult>('/api/research/', {
    method: 'POST',
    body: { query, language, report_type: reportType },
  })

export type ExportFormat = 'md' | 'docx' | 'pdf'

/** Download a research export via an authenticated fetch -> blob -> <a>. */
export async function downloadExport(runId: string, format: ExportFormat): Promise<void> {
  const headers: Record<string, string> = {}
  const token = getToken()
  if (token) headers['Authorization'] = `Bearer ${token}`
  let res: Response
  try {
    res = await fetch(`${API_BASE}/api/research/${runId}/export?format=${format}`, { headers })
  } catch {
    throw new ApiError(0, `cannot reach SHAKIB AI Core at ${API_BASE} — is the backend running?`)
  }
  if (!res.ok) throw await parseError(res)
  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `shakib-ai-research-${runId}.${format}`
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

// --------------------------------------------------------------- council
export interface CouncilPoint {
  point?: string
  target_claim?: string
  strength?: string
  issue?: string
  severity?: string
  evidence_gap?: string
  scenario?: string
  plausibility?: string
  impact?: string
  gap?: string
  why_it_matters?: string
  [key: string]: unknown
}

export interface CouncilMemberResult {
  member: string
  status: 'ok' | 'error' | string
  summary?: string
  reason?: string
  points?: CouncilPoint[]
  findings?: CouncilPoint[]
  scenarios?: CouncilPoint[]
  gaps?: CouncilPoint[]
}

export interface CouncilResult {
  run_id?: string
  language: string
  members: Record<string, CouncilMemberResult>
  generated_by_role: string | null
}

export interface CouncilRequestBody {
  run_id?: string
  report_markdown?: string
  sources?: ResearchSource[]
  language: ResearchLanguage
}

export const runCouncil = (body: CouncilRequestBody) =>
  request<CouncilResult>('/api/council/', { method: 'POST', body })

// ----------------------------------------------------------------- files
export interface DocumentMeta {
  id: number
  filename: string
  mime: string
  size: number
  created_at: string | null
}

export interface UploadResult extends DocumentMeta {
  text_chars: number
}

export interface DocumentDetail extends DocumentMeta {
  text: string
  truncated: boolean
}

export const uploadFile = (file: File) => {
  const form = new FormData()
  form.append('file', file)
  return request<UploadResult>('/api/files/upload', { method: 'POST', form })
}

export const listDocuments = () => request<{ documents: DocumentMeta[] }>('/api/files/')

export const getDocument = (id: number) => request<DocumentDetail>(`/api/files/${id}`)

export const deleteDocument = (id: number) =>
  request<void>(`/api/files/${id}`, { method: 'DELETE' })

// ---------------------------------------------------------------- images
export interface GeneratedImage {
  url?: string
  b64_json?: string
  revised_prompt?: string
}

export interface ImageResponse {
  created?: number
  data: GeneratedImage[]
}

export const generateImage = (prompt: string, model?: string, size?: string) =>
  request<ImageResponse>('/api/images/generate', {
    method: 'POST',
    body: { prompt, model: model || undefined, size: size || undefined },
  })

// ---------------------------------------------------------------- skills
export interface Skill {
  name: string
  description: string
  status: 'ready' | 'needs_configuration' | 'client_side' | string
  missing: string[]
}

export const listSkills = () => request<{ skills: Skill[] }>('/api/skills/')

// ---------------------------------------------------------------- memory
export interface MemoryItem {
  id: number
  kind: string
  content: string
  created_at: string | null
}

export const listMemory = () => request<{ items: MemoryItem[] }>('/api/memory/')

export const addMemory = (kind: string, content: string) =>
  request<MemoryItem>('/api/memory/', { method: 'POST', body: { kind, content } })

export const deleteMemory = (id: number) =>
  request<void>(`/api/memory/${id}`, { method: 'DELETE' })

// -------------------------------------------------------------- settings
export interface ModelSettings {
  gateway_configured: boolean
  gateway_base_url: string
  roles: Record<string, string[]>
}

export const getModelSettings = () => request<ModelSettings>('/api/settings/models')

export interface StoredKey {
  id: number
  provider: string
  last4: string
  created_at: string | null
}

export const listKeys = () => request<{ keys: StoredKey[] }>('/api/settings/keys')

export const storeKey = (provider: string, apiKey: string) =>
  request<StoredKey>('/api/settings/keys', {
    method: 'POST',
    body: { provider, api_key: apiKey },
  })

export const deleteKey = (provider: string) =>
  request<void>(`/api/settings/keys/${encodeURIComponent(provider)}`, { method: 'DELETE' })
