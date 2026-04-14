import { Loader2, MessageSquare, Plus, Send } from 'lucide-react'
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { fetchThreadMessages, fetchThreadTitle, streamChat } from '../lib/api'
import {
  loadMessages,
  saveMessages,
  threadTitleFromFirstUserMessage,
  updateThreadCatalogTitle,
  upsertThreadCatalog,
} from '../lib/threadStorage'
import type { ChatSource, Msg } from './MessageBubble'
import { MessageBubble } from './MessageBubble'
import { SuggestedPrompts } from './SuggestedPrompts'

type Props = {
  docId: string | null
  docName: string
  /** Shown under the filename — from the thread catalog (first question text). */
  threadLabel: string
  threadId: string | null
  /** Bump only when switching PDF / picking a saved thread / new chat — not when the server assigns a thread id. */
  hydrateVersion: number
  onMessagesChange?: (m: Msg[]) => void
  onOpenCitation: (s: ChatSource) => void
  /** Fire after a thread is persisted to local catalog (refreshes sidebar). */
  onThreadCatalogChanged?: () => void
  /** Called while AI title is generating (null = done). */
  onTitleGenerating?: (threadId: string | null) => void
  /** Called when the user clicks "New conversation" from the no-thread placeholder. */
  onNewChat?: () => void
}

export function ChatPanel({
  docId,
  docName,
  threadLabel,
  threadId,
  hydrateVersion,
  onMessagesChange,
  onOpenCitation,
  onThreadCatalogChanged,
  onTitleGenerating,
  onNewChat,
}: Props) {
  const [input, setInput] = useState('')
  const [msgs, setMsgs] = useState<Msg[]>([])
  const [loading, setLoading] = useState(false)
  const [awaitingTokens, setAwaitingTokens] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  const acRef = useRef<AbortController | null>(null)
  const threadIdRef = useRef(threadId)
  const msgsRef = useRef<Msg[]>([])
  const sendingRef = useRef(false)
  const inputRef = useRef(input)
  inputRef.current = input
  threadIdRef.current = threadId
  msgsRef.current = msgs
  const prevThreadIdForScrollRef = useRef<string | null>(null)

  useEffect(() => {
    if (prevThreadIdForScrollRef.current !== threadId) {
      prevThreadIdForScrollRef.current = threadId
      return
    }
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [msgs, loading, threadId])

  useEffect(() => {
    onMessagesChange?.(msgs)
  }, [msgs, onMessagesChange])

  /**
   * Runs before `saveMessages` effect so the new threadId never inherits the old msgs.
   * Also aborts any in-flight stream so stale token callbacks cannot corrupt the new thread.
   */
  useLayoutEffect(() => {
    // Cancel the previous stream immediately — its callbacks must not mutate new thread state.
    acRef.current?.abort()
    sendingRef.current = false
    setLoading(false)
    setAwaitingTokens(false)
    setError(null)

    if (!docId || !threadId) {
      setMsgs([])
      return
    }
    // Load from localStorage first (instant); if empty, fall back to backend
    const local = loadMessages(docId, threadId)
    if (local.length > 0) {
      setMsgs(local)
    } else {
      setMsgs([])
      const tid = threadId
      const did = docId
      void fetchThreadMessages(tid).then((serverMsgs) => {
        if (serverMsgs.length === 0) return
        // Only apply if we haven't switched thread/doc in the meantime
        if (threadIdRef.current !== tid) return
        const mapped = serverMsgs.map((m) => ({
          role: m.role as 'user' | 'assistant',
          content: m.content,
          sources: (m.sources || []) as ChatSource[],
        }))
        setMsgs(mapped)
        saveMessages(did, tid, mapped)
      })
    }
  }, [docId, threadId, hydrateVersion])

  useEffect(() => {
    if (!docId || !threadId || msgs.length === 0) return
    saveMessages(docId, threadId, msgs)
  }, [msgs, docId, threadId])

  // No catalog updatedAt bump here — we only update the title (via AI call in sendMessage).
  // Bumping updatedAt on every message change caused the selected thread to jump to the top of the list.

  const sendMessage = useCallback(
    async (textOverride?: string) => {
      if (!docId) return
      const raw = textOverride !== undefined ? textOverride : inputRef.current
      const text = raw.trim()
      if (!text) return
      if (sendingRef.current) return
      if (textOverride === undefined) setInput('')
      setError(null)
      const tid = threadIdRef.current
      if (!tid) return
      const isFirstTurn = msgsRef.current.length === 0
      const nextWithUser = [...msgsRef.current, { role: 'user' as const, content: text }]
      setMsgs(nextWithUser)
      upsertThreadCatalog(docId, tid, nextWithUser, { title: '…' })
      onThreadCatalogChanged?.()

      // Fire AI title generation concurrently on the first message only — don't await the stream
      if (isFirstTurn) {
        onTitleGenerating?.(tid)
        void (async () => {
          const aiTitle = await fetchThreadTitle(text, tid)
          const title = aiTitle || threadTitleFromFirstUserMessage([{ role: 'user', content: text }])
          if (title && docId && tid) {
            updateThreadCatalogTitle(docId, tid, title)
            onThreadCatalogChanged?.()  // re-fetch sidebar with the real title
          }
          onTitleGenerating?.(null)
        })()
      }
      acRef.current?.abort()
      const requestCtrl = new AbortController()
      acRef.current = requestCtrl
      sendingRef.current = true
      setAwaitingTokens(true)
      setLoading(true)
      let assistant = ''
      let lastSources: ChatSource[] = []
      try {
        await streamChat(
          text,
          docId,
          tid,
          (tok) => {
            // Drop stale callbacks from an aborted or superseded stream.
            if (requestCtrl.signal.aborted || acRef.current !== requestCtrl) return
            if (tok) setAwaitingTokens(false)
            assistant += tok
            setMsgs((m) => {
              const copy = [...m]
              const last = copy[copy.length - 1]
              if (last?.role === 'assistant') copy.pop()
              copy.push({ role: 'assistant', content: assistant, sources: lastSources })
              return copy
            })
          },
          (meta) => {
            if (requestCtrl.signal.aborted || acRef.current !== requestCtrl) return
            lastSources = (meta.sources || []) as ChatSource[]
            if (meta.done) {
              setAwaitingTokens(false)
              setMsgs((m) => {
                const copy = [...m]
                const last = copy[copy.length - 1]
                if (last?.role === 'assistant') copy.pop()
                copy.push({ role: 'assistant', content: assistant, sources: lastSources })
                return copy
              })
            }
          },
          requestCtrl.signal,
        )
      } catch (e) {
        // Superseded by a newer send or a thread-switch — discard silently.
        if (requestCtrl.signal.aborted || acRef.current !== requestCtrl) {
          /* superseded */
        } else {
          const msg = e instanceof Error ? e.message : 'Request failed'
          setError(msg)
          setMsgs((m) => [...m, { role: 'assistant', content: '\u26a0\ufe0f Could not complete the request.' }])
        }
      } finally {
        // Only update global loading state for the controller that is still active.
        if (acRef.current === requestCtrl) {
          sendingRef.current = false
          setAwaitingTokens(false)
          setLoading(false)
          // Re-fetch sidebar threads now that the backend has committed the turn.
          // Small delay lets the async _persist() task complete before we query.
          setTimeout(() => onThreadCatalogChanged?.(), 600)
        }
      }
    },
    [docId, onThreadCatalogChanged, onTitleGenerating],
  )

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      void sendMessage()
    }
  }

  if (!docId) {
    return (
      <div className="flex min-h-0 flex-1 flex-col items-center justify-center rounded-2xl border border-border bg-card/70 px-6 py-12 text-center shadow-card">
        <div className="flex h-14 w-14 items-center justify-center rounded-xl bg-muted/80 text-foreground/50">
          <MessageSquare className="h-7 w-7 stroke-[1.65]" aria-hidden />
        </div>
        <p className="mt-4 text-sm font-semibold text-foreground">Choose a PDF in the library</p>
        <p className="mx-auto mt-2 max-w-md text-sm leading-relaxed text-muted-foreground">
          Use <span className="font-medium text-foreground">Upload PDF</span> in the header to add a file, then open it from{' '}
          <span className="font-medium text-foreground">PDFs</span>. Remove an upload with the trash icon on its row.
        </p>
      </div>
    )
  }

  if (!threadId) {
    return (
      <div className="flex min-h-0 flex-1 flex-col items-center justify-center rounded-2xl border border-border bg-card/70 px-6 py-12 text-center shadow-card">
        <div className="flex h-14 w-14 items-center justify-center rounded-xl bg-blue-500/10 text-blue-400">
          <Plus className="h-7 w-7 stroke-[1.65]" aria-hidden />
        </div>
        <p className="mt-4 text-sm font-semibold text-foreground">Start a conversation</p>
        <p className="mx-auto mt-2 max-w-xs text-sm leading-relaxed text-muted-foreground">
          You have <span className="font-medium text-foreground">{docName || 'a document'}</span> open.
          Click the button below to begin a new chat grounded in this PDF.
        </p>
        <button
          type="button"
          onClick={onNewChat}
          disabled={!onNewChat}
          className="mt-6 inline-flex items-center gap-2 rounded-xl bg-blue-600 px-5 py-2.5 text-sm font-semibold text-white shadow-md transition-all hover:bg-blue-500 active:scale-95 active:brightness-90 disabled:opacity-40"
        >
          <Plus className="h-4 w-4 stroke-[2]" aria-hidden />
          New conversation
        </button>
      </div>
    )
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-2xl border border-border bg-card shadow-lift">
      <div
        className="min-w-0 shrink-0 overflow-hidden border-b border-border bg-muted/20 px-4 py-2.5 text-left text-sm leading-snug break-words whitespace-normal"
        title={threadLabel ? `${threadLabel} — ${docName || 'Document'}` : (docName || 'Document')}
      >
        {threadLabel
          ? (
            <>
              <span className="break-words font-semibold text-foreground">{threadLabel}</span>
              <span className="text-muted-foreground"> — </span>
              <span className="break-all text-muted-foreground">{docName || 'Document'}</span>
            </>
            )
          : <span className="font-medium break-all text-muted-foreground">{docName || 'Document'}</span>
        }
      </div>

      <div className="scrollbar-minimal min-h-0 flex-1 space-y-1 overflow-y-auto overscroll-contain p-4">
        {msgs.length === 0 && (
          <div className="mx-auto max-w-md rounded-2xl border border-border bg-muted/25 px-5 py-8 text-center ring-1 ring-foreground/[0.04]">
            <p className="text-sm font-semibold text-foreground">Grounded document Q&A</p>
            <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
              Use a suggested prompt below or compose your own question. Citations from the PDF open in the side panel.
            </p>
          </div>
        )}
        {msgs.map((m, i) => (
          <MessageBubble key={i} msg={m} onOpenSource={m.role === 'assistant' ? onOpenCitation : undefined} />
        ))}
        {loading && awaitingTokens && (
          <div className="flex items-center gap-2 rounded-xl border border-border bg-muted/40 px-3 py-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 shrink-0 animate-spin text-foreground/45" aria-hidden />
            Retrieving and drafting…
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Only show suggested prompts before the conversation starts — once messages exist
          they clutter the view and the user already knows what to ask. */}
      {msgs.length === 0 && (
        <SuggestedPrompts docId={docId} onPick={(q) => void sendMessage(q)} disabled={loading} />
      )}

      {error && (
        <p className="shrink-0 border-t border-destructive/20 bg-destructive/10 px-4 py-2.5 text-xs font-medium text-destructive">
          {error}
        </p>
      )}

      <div className="flex shrink-0 gap-2 border-t border-border bg-card p-3">
        <textarea
          aria-label="Message input"
          className="scrollbar-minimal min-h-[48px] flex-1 resize-none rounded-xl border border-input bg-background px-3.5 py-2.5 text-sm text-foreground outline-none transition placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring"
          placeholder="Ask anything about this document…"
          rows={2}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={onKeyDown}
          disabled={loading}
        />
        <button
          type="button"
          aria-label="Send message"
          className="inline-flex h-12 w-12 shrink-0 items-center justify-center self-end rounded-xl bg-blue-600 text-white shadow-md transition-all duration-150 hover:bg-blue-500 active:scale-95 active:brightness-90 disabled:cursor-not-allowed disabled:opacity-40"
          onClick={() => void sendMessage()}
          disabled={loading || !input.trim()}
        >
          <Send className="h-5 w-5" aria-hidden />
        </button>
      </div>
    </div>
  )
}
