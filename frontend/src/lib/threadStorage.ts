import type { Msg } from '../components/MessageBubble'

const MSG_PREFIX = 'risk-auditor-msgs'
const CATALOG_KEY = 'risk-auditor-thread-catalog'

/** Used with `storage` events so other tabs can detect catalog / message updates. */
export const THREAD_CATALOG_STORAGE_KEY = CATALOG_KEY

const UI_SESSION_KEY = 'risk-auditor-ui-session'

/** Same key as `saveUISession` / `loadUISession` — listen for cross-tab workspace sync. */
export const UI_SESSION_STORAGE_KEY = UI_SESSION_KEY

export type UISessionSnapshot = {
  docId: string
  threadId: string | null
  docName?: string
}

/** Remember last open document + thread so a new tab can reopen the same workspace. */
export function saveUISession(snapshot: UISessionSnapshot | null): void {
  try {
    if (!snapshot) {
      localStorage.removeItem(UI_SESSION_KEY)
      return
    }
    localStorage.setItem(UI_SESSION_KEY, JSON.stringify(snapshot))
  } catch {
    /* quota / private mode */
  }
}

export function loadUISession(): UISessionSnapshot | null {
  try {
    const raw = localStorage.getItem(UI_SESSION_KEY)
    if (!raw) return null
    const o = JSON.parse(raw) as unknown
    if (!o || typeof o !== 'object') return null
    const docId = (o as { docId?: unknown }).docId
    if (typeof docId !== 'string' || !docId) return null
    const threadId = (o as { threadId?: unknown }).threadId
    const docName = (o as { docName?: unknown }).docName
    return {
      docId,
      threadId: typeof threadId === 'string' ? threadId : null,
      docName: typeof docName === 'string' ? docName : undefined,
    }
  } catch {
    return null
  }
}

export function isMessageStorageKey(key: string): boolean {
  return key.startsWith(`${MSG_PREFIX}:`)
}

export type ThreadCatalogEntry = {
  threadId: string
  docId: string
  title: string
  updatedAt: string
}

/** Fingerprint for catalog updates — ignores `sources` / metadata that often differ after JSON round-trip. */
export function threadMessagesFingerprint(msgs: Msg[]): string {
  return JSON.stringify(msgs.map((m) => ({ role: m.role, content: m.content })))
}

/** Common English filler — strip to keep 2–3 “main” words for thread titles. */
const SUMMARY_STOP = new Set(
  `a an the is are was were be been being
   what which who whom whose where when why how
   can could would should may might must shall will
   do does did doing done have has had having
   i you we they he she it its our your their my me him her us them
   to of in on at by for from with as into through during before after above below between
   and or nor but so yet if then there this that these those here any all some each every no not only own same such too very just about also than per
   please tell describe explain list give show find help`.split(/\s+/).filter(Boolean),
)

/**
 * Short label: up to `maxWords` content words (default 3), skipping common stop words.
 * Falls back to the first tokens of the original text if everything is filtered out.
 */
export function threadSummaryShort(text: string, maxWords = 3): string {
  const s = text.replace(/\s+/g, ' ').trim()
  if (!s) return ''
  const tokens = s
    .split(/\s+/)
    .map((w) => w.replace(/^[^\p{L}\p{N}]+|[^\p{L}\p{N}]+$/gu, ''))
    .filter((w) => w.length > 0)
  if (tokens.length === 0) return ''

  const main: string[] = []
  for (const tok of tokens) {
    const low = tok.toLowerCase().replace(/'/g, '')
    if (SUMMARY_STOP.has(low)) continue
    main.push(tok)
    if (main.length >= maxWords) break
  }

  if (main.length >= 2) {
    return main.slice(0, maxWords).join(' ')
  }
  const lead = tokens.slice(0, Math.min(maxWords, Math.max(2, tokens.length)))
  return lead.join(' ') || tokens[0] || ''
}

/** Title-style caps for short thread labels (each word capitalized). */
export function formatThreadSummaryDisplay(text: string): string {
  const s = text.replace(/\s+/g, ' ').trim()
  if (!s) return ''
  return s
    .split(/\s+/)
    .map((w) => {
      if (w.length === 0) return w
      if (w.length <= 2 && /^[A-Z]{1,3}$/.test(w)) return w
      return w.charAt(0).toUpperCase() + w.slice(1).toLowerCase()
    })
    .join(' ')
}

/** Sidebar label from the first user message — 2–3 main words only. */
export function threadTitleFromFirstUserMessage(msgs: Msg[]): string {
  const u = msgs.find((m) => m.role === 'user')?.content?.trim() ?? ''
  if (!u) return 'New chat'
  const short = threadSummaryShort(u, 3) || 'New chat'
  return formatThreadSummaryDisplay(short)
}

export function msgStorageKey(docId: string, threadId: string) {
  return `${MSG_PREFIX}:${docId}:${threadId}`
}

export function loadMessages(docId: string, threadId: string): Msg[] {
  try {
    const raw = localStorage.getItem(msgStorageKey(docId, threadId))
    if (!raw) return []
    const parsed = JSON.parse(raw) as unknown
    return Array.isArray(parsed) ? (parsed as Msg[]) : []
  } catch {
    return []
  }
}

export function saveMessages(docId: string, threadId: string, msgs: Msg[]) {
  try {
    localStorage.setItem(msgStorageKey(docId, threadId), JSON.stringify(msgs))
  } catch {
    /* quota */
  }
}

export function loadCatalog(): ThreadCatalogEntry[] {
  try {
    const raw = localStorage.getItem(CATALOG_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw) as unknown
    return Array.isArray(parsed) ? (parsed as ThreadCatalogEntry[]) : []
  } catch {
    return []
  }
}

export function saveCatalog(entries: ThreadCatalogEntry[]) {
  try {
    localStorage.setItem(CATALOG_KEY, JSON.stringify(entries.slice(0, 80)))
  } catch {
    /* quota */
  }
}

function isPlaceholderThreadTitle(t: string): boolean {
  const s = t.trim()
  return s === '' || s === '…' || s === '...'
}

/** True once a real chat name has been saved (not draft ellipsis). */
function hasFinalThreadTitle(docId: string, threadId: string): boolean {
  const e = loadCatalog().find((x) => x.docId === docId && x.threadId === threadId)
  return !!e && !isPlaceholderThreadTitle(e.title)
}

export function upsertThreadCatalog(docId: string, threadId: string, msgs: Msg[], options?: { title?: string }) {
  const firstUser = msgs.find((m) => m.role === 'user')
  const raw = firstUser?.content?.trim() ?? ''
  const existing = loadCatalog().find((e) => e.threadId === threadId && e.docId === docId)
  const existingTitle = existing?.title?.trim() ?? ''
  const keepTitle = existingTitle.length > 0 && !isPlaceholderThreadTitle(existingTitle)

  let title: string
  if (keepTitle) {
    title = existingTitle
  } else if (options?.title !== undefined) {
    title = options.title
  } else {
    title = raw ? formatThreadSummaryDisplay(threadSummaryShort(raw, 3) || 'Chat') : 'Conversation'
  }

  const updatedAt = new Date().toISOString()
  const cur = loadCatalog().filter((e) => !(e.threadId === threadId && e.docId === docId))
  cur.unshift({ threadId, docId, title, updatedAt })
  saveCatalog(cur)
}

export function updateThreadCatalogTitle(docId: string, threadId: string, title: string): void {
  if (hasFinalThreadTitle(docId, threadId)) return
  // Keep the full AI title (backend sanitizes to ≤52 chars); only fix capitalization.
  const safe = formatThreadSummaryDisplay(title.replace(/\s+/g, ' ').trim() || 'Chat')
  const updatedAt = new Date().toISOString()
  const cur = loadCatalog()
  const idx = cur.findIndex((e) => e.docId === docId && e.threadId === threadId)
  if (idx >= 0) {
    const next = [...cur]
    next[idx] = { ...next[idx], title: safe, updatedAt }
    saveCatalog(next)
    return
  }
  const msgs = loadMessages(docId, threadId)
  upsertThreadCatalog(docId, threadId, msgs, { title: safe })
}

export function touchThreadCatalogUpdated(docId: string, threadId: string): void {
  const cur = loadCatalog()
  const idx = cur.findIndex((e) => e.docId === docId && e.threadId === threadId)
  if (idx < 0) return
  const next = [...cur]
  next[idx] = { ...next[idx], updatedAt: new Date().toISOString() }
  saveCatalog(next)
}

export function catalogForDoc(docId: string): ThreadCatalogEntry[] {
  // Preserve the natural catalog order (newest-first via unshift on creation).
  // We intentionally do NOT re-sort by updatedAt here — doing so caused selected
  // threads to jump to the top of the list on every interaction.
  return loadCatalog().filter((e) => e.docId === docId)
}

/** Remove one thread from the catalog and its cached messages (browser only). */
export function removeThreadClient(docId: string, threadId: string): void {
  saveCatalog(loadCatalog().filter((e) => !(e.docId === docId && e.threadId === threadId)))
  try {
    localStorage.removeItem(msgStorageKey(docId, threadId))
  } catch {
    /* ignore */
  }
}

/** Remove sidebar threads and cached messages for a document (e.g. after DELETE /documents). */
export function clearClientDataForDoc(docId: string): void {
  saveCatalog(loadCatalog().filter((e) => e.docId !== docId))
  const prefix = `${MSG_PREFIX}:${docId}:`
  for (let i = localStorage.length - 1; i >= 0; i--) {
    const k = localStorage.key(i)
    if (k?.startsWith(prefix)) localStorage.removeItem(k)
  }
}
