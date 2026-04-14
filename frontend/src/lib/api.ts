/** In dev, prefer Vite proxy `/api` unless VITE_API_URL is set (avoids CORS + wrong host). */
function apiBase(): string {
  const v = import.meta.env.VITE_API_URL
  if (v != null && String(v).trim() !== '') {
    return String(v).replace(/\/$/, '')
  }
  if (import.meta.env.DEV) {
    return '/api'
  }
  // Production build co-located with API (e.g. nginx gateway on :8080) → same-origin paths
  return ''
}

const API = apiBase()

const FIXED_USER_ID = 'Neel'

function userHeader(): Record<string, string> {
  let pw = ''
  try {
    pw = (window.localStorage.getItem('risk_admin_pw') || '').trim()
  } catch {
    pw = ''
  }
  const h: Record<string, string> = { 'X-User-Id': FIXED_USER_ID }
  if (pw) h['X-Admin-Password'] = pw
  return h
}

/** Max wait for full SSE (retrieval + tokens + final frame). Override with VITE_CHAT_STREAM_TIMEOUT_MS (ms). */
const STREAM_TIMEOUT_MS = (() => {
  const v = import.meta.env.VITE_CHAT_STREAM_TIMEOUT_MS
  const n = v != null && String(v).trim() !== '' ? Number(v) : NaN
  return Number.isFinite(n) && n > 0 ? n : 420_000
})()

function detailFromBody(body: unknown, fallback: string): string {
  const d = (body as { detail?: string | { msg?: string }[] }).detail
  if (typeof d === 'string') return d
  if (Array.isArray(d)) return d.map((x) => (typeof x === 'string' ? x : JSON.stringify(x))).join('; ')
  return fallback
}

/** Chrome may throw TypeError with message containing BodyStreamBuffer when a fetch body is aborted. */
function isAbortLikeError(e: unknown): boolean {
  if (e == null || typeof e !== 'object') return false
  const err = e as { name?: string; message?: string }
  if (err.name === 'AbortError') return true
  const msg = typeof err.message === 'string' ? err.message : ''
  return /aborted|BodyStreamBuffer|cancelled|canceled/i.test(msg)
}

function parseSseDataLine(line: string): {
  token?: string
  done?: boolean
  thread_id?: string
  sources?: unknown[]
  error?: boolean
} | null {
  const t = line.trim()
  if (!t.startsWith('data: ')) return null
  const payload = t.slice(6).trim()
  if (payload === '[DONE]') return null
  try {
    return JSON.parse(payload) as {
      token?: string
      done?: boolean
      thread_id?: string
      sources?: unknown[]
      error?: boolean
    }
  } catch {
    return null
  }
}

function emitSseBlock(
  block: string,
  onToken: (t: string) => void,
  onMeta: (m: StreamMeta) => void,
): void {
  const normalized = block.replace(/\r\n/g, '\n')
  for (const line of normalized.split('\n')) {
    const j = parseSseDataLine(line)
    if (!j) continue
    if (j.token) onToken(j.token)
    onMeta({
      thread_id: j.thread_id || '',
      sources: j.sources || [],
      done: Boolean(j.done),
    })
  }
}

export type DocumentSummary = { doc_id: string; filename: string }

export type ThreadSummary = {
  thread_id: string
  doc_id: string
  title: string
  created_at: string
}

export type ServerMessage = {
  role: 'user' | 'assistant'
  content: string
  sources: unknown[]
}

export async function verifyLogin(_uid: string, adminPw: string): Promise<void> {
  const p = adminPw.trim()
  const res = await fetch(`${API}/chat/auth/check`, {
    headers: {
      'X-User-Id': FIXED_USER_ID,
      'X-Admin-Password': p,
    },
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(detailFromBody(err, res.statusText))
  }
}

export async function fetchThreads(docId: string): Promise<ThreadSummary[]> {
  try {
    const res = await fetch(`${API}/threads?doc_id=${encodeURIComponent(docId)}`, { headers: userHeader() })
    if (!res.ok) return []
    return res.json()
  } catch {
    return []
  }
}

export async function fetchThreadMessages(threadId: string): Promise<ServerMessage[]> {
  try {
    const res = await fetch(`${API}/threads/${encodeURIComponent(threadId)}/messages`, { headers: userHeader() })
    if (!res.ok) return []
    return res.json()
  } catch {
    return []
  }
}

export type DocPage = { page: number; content: string }

export async function fetchDocumentPages(docId: string): Promise<DocPage[]> {
  const res = await fetch(`${API}/documents/${encodeURIComponent(docId)}/pages`, { headers: userHeader() })
  if (!res.ok) return []
  return res.json()
}

export type SuggestedQuestionsResult = { questions: string[]; status: string }

export async function fetchSuggestedQuestions(docId: string): Promise<SuggestedQuestionsResult> {
  try {
    const res = await fetch(`${API}/documents/${encodeURIComponent(docId)}/suggested-questions`, { headers: userHeader() })
    if (!res.ok) return { questions: [], status: 'none' }
    return res.json() as Promise<SuggestedQuestionsResult>
  } catch {
    return { questions: [], status: 'none' }
  }
}

export async function fetchDocuments(): Promise<DocumentSummary[]> {
  const res = await fetch(`${API}/documents`, { headers: userHeader() })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(detailFromBody(err, res.statusText))
  }
  return res.json()
}

export async function deleteThread(threadId: string): Promise<{ thread_id: string; deleted_rows: number }> {
  const res = await fetch(`${API}/threads/${encodeURIComponent(threadId)}`, { method: 'DELETE', headers: userHeader() })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(detailFromBody(err, res.statusText))
  }
  return res.json()
}

export async function deleteDocument(docId: string): Promise<{ doc_id: string; deleted_chunks: number }> {
  const res = await fetch(`${API}/documents/${encodeURIComponent(docId)}`, { method: 'DELETE', headers: userHeader() })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(detailFromBody(err, res.statusText))
  }
  return res.json()
}

export async function uploadPdf(file: File): Promise<{ doc_id: string; filename: string }> {
  const fd = new FormData()
  fd.append('file', file)
  const res = await fetch(`${API}/upload`, { method: 'POST', body: fd, headers: userHeader() })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(detailFromBody(err, res.statusText))
  }
  return res.json()
}

/** Generate an AI sidebar title from the user's first question.
 *  Fires concurrently with the chat stream so the title appears quickly.
 *  Returns empty string on any failure so callers can fall back gracefully. */
export async function fetchThreadTitle(userMessage: string, threadId?: string): Promise<string> {
  try {
    const res = await fetch(`${API}/chat/thread-title`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...userHeader() },
      body: JSON.stringify({
        user_message: userMessage,
        assistant_message: '',
        thread_id: threadId ?? null,
      }),
    })
    if (!res.ok) return ''
    const data = (await res.json()) as { title?: string }
    return typeof data.title === 'string' ? data.title.trim() : ''
  } catch {
    return ''
  }
}

export type StreamMeta = { thread_id: string; sources: unknown[]; done: boolean }

export async function streamChat(
  message: string,
  docId: string,
  threadId: string | null,
  onToken: (t: string) => void,
  onMeta: (m: StreamMeta) => void,
  signal?: AbortSignal,
): Promise<void> {
  const combined = new AbortController()
  let timedOut = false
  const onAbort = () => combined.abort()
  if (signal) {
    if (signal.aborted) combined.abort()
    else signal.addEventListener('abort', onAbort, { once: true })
  }
  const timeout = window.setTimeout(() => {
    timedOut = true
    combined.abort()
  }, STREAM_TIMEOUT_MS)

  let reader: ReadableStreamDefaultReader<Uint8Array> | null = null

  try {
    const res = await fetch(`${API}/chat/stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'text/event-stream',
        ...userHeader(),
      },
      body: JSON.stringify({
        message,
        doc_id: docId,
        thread_id: threadId,
      }),
      signal: combined.signal,
    })
    if (!res.ok || !res.body) {
      const err = await res.json().catch(() => ({}))
      throw new Error(detailFromBody(err, res.statusText))
    }
    reader = res.body.getReader()
    const dec = new TextDecoder()
    let buf = ''

    const pumpBuffer = (): void => {
      buf = buf.replace(/\r\n/g, '\n')
      let sep: number
      while ((sep = buf.indexOf('\n\n')) >= 0) {
        const block = buf.slice(0, sep)
        buf = buf.slice(sep + 2)
        emitSseBlock(block, onToken, onMeta)
      }
    }

    while (true) {
      const { value, done } = await reader.read()
      if (value) {
        buf += dec.decode(value, { stream: true })
        pumpBuffer()
      }
      if (done) break
    }
    buf += dec.decode()
    pumpBuffer()
    const tail = buf.trim()
    if (tail) emitSseBlock(tail, onToken, onMeta)
  } catch (e) {
    if (timedOut) {
      throw new Error(
        `This reply exceeded the app time limit (${Math.round(STREAM_TIMEOUT_MS / 60_000)} min). Try a shorter question, or set VITE_CHAT_STREAM_TIMEOUT_MS in frontend/.env to allow longer streams.`,
      )
    }
    if (combined.signal.aborted || isAbortLikeError(e)) {
      if (signal?.aborted) {
        throw new Error('Request was cancelled.')
      }
      throw new Error(
        'The connection closed before the reply finished (often a network blip or the browser stopping a background tab). Try sending your message again.',
      )
    }
    throw e
  } finally {
    window.clearTimeout(timeout)
    if (signal) signal.removeEventListener('abort', onAbort)
    if (reader && combined.signal.aborted) {
      try {
        await reader.cancel()
      } catch {
        /* ignore */
      }
    }
  }
}
