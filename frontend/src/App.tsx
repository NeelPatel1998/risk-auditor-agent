import { CitationSheet } from '@/components/CitationSheet'
import { ChatPanel } from '@/components/ChatPanel'
import { ConfirmDialog } from '@/components/ConfirmDialog'
import type { ChatSource, Msg } from '@/components/MessageBubble'
import { LibrarySidebar } from '@/components/LibrarySidebar'
import { Button } from '@/components/ui/button'
import { deleteDocument, deleteThread, fetchDocuments, fetchThreads, verifyLogin, type DocumentSummary, type ThreadSummary, uploadPdf } from '@/lib/api'
import {
  clearClientDataForDoc,
  isMessageStorageKey,
  loadUISession,
  msgStorageKey,
  removeThreadClient,
  saveUISession,
  THREAD_CATALOG_STORAGE_KEY,
  formatThreadSummaryDisplay,
  UI_SESSION_STORAGE_KEY,
} from '@/lib/threadStorage'
import { Download, Loader2, LogOut, Upload } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

const FIXED_USER_ID = 'Neel'
const ADMIN_PW_STORAGE_KEY = 'risk_admin_pw'

function loadAdminPw(): string {
  try {
    return (window.localStorage.getItem(ADMIN_PW_STORAGE_KEY) || '').trim()
  } catch {
    return ''
  }
}

function exportText(docName: string, msgs: Msg[]) {
  const sep = '='.repeat(60)
  const lines = [
    `Risk Auditor Assistant — Export`,
    `Document: ${docName}`,
    `Exported: ${new Date().toLocaleString()}`,
    sep,
    '',
  ]
  for (const m of msgs) {
    lines.push(m.role === 'user' ? 'YOU' : 'ASSISTANT')
    lines.push('-'.repeat(40))
    lines.push(m.content.trim())
    lines.push('')
  }
  const blob = new Blob([lines.join('\n')], { type: 'text/plain' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `risk-auditor-chat-${new Date().toISOString().slice(0,10)}.txt`
  a.click()
  URL.revokeObjectURL(url)
}

export default function App() {
  const [adminPw, setAdminPw] = useState<string>(() => loadAdminPw())
  const [adminPwDraft, setAdminPwDraft] = useState<string>('')
  const [loginErr, setLoginErr] = useState<string | null>(null)
  const [loginPending, setLoginPending] = useState(false)

  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const [documents, setDocuments] = useState<DocumentSummary[]>([])
  const [documentsLoading, setDocumentsLoading] = useState(false)
  const [docId, setDocId] = useState<string | null>(null)
  const [docName, setDocName] = useState('')
  const [threadId, setThreadId] = useState<string | null>(null)
  const [hydrateVersion, setHydrateVersion] = useState(0)
  const [threadCatalogRev, setThreadCatalogRev] = useState(0)
  const [serverThreads, setServerThreads] = useState<ThreadSummary[]>([])
  const [pendingTitleThreadId, setPendingTitleThreadId] = useState<string | null>(null)
  const [exportMsgs, setExportMsgs] = useState<Msg[]>([])
  const [uploadPending, setUploadPending] = useState(false)
  const [uploadErr, setUploadErr] = useState<string | null>(null)
  const [citationOpen, setCitationOpen] = useState(false)
  const [citationSource, setCitationSource] = useState<ChatSource | null>(null)

  type DialogState = {
    title: string
    description: string
    confirmLabel: string
    cancelLabel?: string
    variant: 'danger' | 'info'
    showCancel: boolean
    resolve: (result: boolean) => void
  }
  const [dialogState, setDialogState] = useState<DialogState | null>(null)

  const showConfirm = useCallback(
    (title: string, description: string, confirmLabel = 'Delete', variant: 'danger' | 'info' = 'danger'): Promise<boolean> =>
      new Promise((resolve) => setDialogState({ title, description, confirmLabel, cancelLabel: 'Cancel', variant, showCancel: true, resolve })),
    [],
  )
  const showAlert = useCallback(
    (title: string, description: string): Promise<void> =>
      new Promise((resolve) => setDialogState({ title, description, confirmLabel: 'OK', variant: 'info', showCancel: false, resolve: () => resolve() })),
    [],
  )
  const closeDialog = useCallback((result: boolean) => {
    setDialogState((prev) => { prev?.resolve(result); return null })
  }, [])

  const hiddenFileRef = useRef<HTMLInputElement>(null)
  const sessionRestoredRef = useRef(false)
  const documentsRef = useRef(documents)
  documentsRef.current = documents
  const docIdRef = useRef(docId)
  docIdRef.current = docId
  const threadIdRef = useRef(threadId)
  threadIdRef.current = threadId
  const documentsLoadingRef = useRef(documentsLoading)
  documentsLoadingRef.current = documentsLoading

  const persistLogin = useCallback(async (pw: string) => {
    const cleanP = pw.trim()
    if (!cleanP) return
    setLoginErr(null)
    setLoginPending(true)
    try {
      await verifyLogin(FIXED_USER_ID, cleanP)
    } catch (e) {
      setLoginErr(e instanceof Error ? e.message : String(e))
      return
    } finally {
      setLoginPending(false)
    }
    window.localStorage.setItem(ADMIN_PW_STORAGE_KEY, cleanP)
    window.localStorage.removeItem(UI_SESSION_STORAGE_KEY)
    window.localStorage.removeItem(THREAD_CATALOG_STORAGE_KEY)
    sessionRestoredRef.current = false
    setDocId(null)
    setDocName('')
    setThreadId(null)
    setExportMsgs([])
    setHydrateVersion((h) => h + 1)
    setThreadCatalogRev((n) => n + 1)
    setAdminPw(cleanP)
    window.setTimeout(() => window.location.reload(), 0)
  }, [])

  const logout = useCallback(() => {
    try {
      window.localStorage.removeItem(ADMIN_PW_STORAGE_KEY)
      window.localStorage.removeItem(UI_SESSION_STORAGE_KEY)
      window.localStorage.removeItem(THREAD_CATALOG_STORAGE_KEY)
    } catch {
      /* ignore */
    }
    sessionRestoredRef.current = false
    setDocId(null)
    setDocName('')
    setThreadId(null)
    setExportMsgs([])
    setHydrateVersion((h) => h + 1)
    setThreadCatalogRev((n) => n + 1)
    setAdminPw('')
    setAdminPwDraft('')
    window.setTimeout(() => window.location.reload(), 0)
  }, [])

  const loadDocuments = useCallback(async () => {
    setDocumentsLoading(true)
    try {
      const rows = await fetchDocuments()
      setDocuments(rows)
    } catch {
      setDocuments([])
    } finally {
      setDocumentsLoading(false)
    }
  }, [])

  const loadServerThreads = useCallback(async (id: string) => {
    const rows = await fetchThreads(id)
    setServerThreads(rows)
  }, [])

  const handleTitleGenerating = useCallback((generatingThreadId: string | null) => {
    setPendingTitleThreadId(generatingThreadId)
  }, [])

  /** Reconcile doc/thread with `localStorage` (other tabs, refresh, or message/session writes). */
  const applyWorkspaceFromStorage = useCallback(() => {
    if (documentsLoadingRef.current) return

    const snap = loadUISession()
    const docs = documentsRef.current

    if (!snap) {
      if (docIdRef.current !== null || threadIdRef.current !== null) {
        setDocId(null)
        setDocName('')
        setThreadId(null)
        setHydrateVersion((h) => h + 1)
        setExportMsgs([])
      }
      return
    }

    if (docs.length === 0) return

    const d = docs.find((x) => x.doc_id === snap.docId)
    if (!d) {
      if (docIdRef.current !== null || threadIdRef.current !== null) {
        setDocId(null)
        setDocName('')
        setThreadId(null)
        setHydrateVersion((h) => h + 1)
        setExportMsgs([])
      }
      return
    }

    const sameDoc = docIdRef.current === snap.docId
    const sameThread = threadIdRef.current === snap.threadId
    if (sameDoc && sameThread) {
      return
    }

    setDocId(snap.docId)
    setDocName(snap.docName || d.filename)
    setThreadId(snap.threadId)
    setHydrateVersion((h) => h + 1)
    setExportMsgs([])
  }, [])

  useEffect(() => {
    void loadDocuments()
  }, [loadDocuments])

  // Reload documents whenever the password changes (e.g. after a fresh login).
  useEffect(() => {
    void loadDocuments()
  }, [adminPw, loadDocuments])

  // Keep sidebar threads in sync with backend whenever the doc or catalog changes
  useEffect(() => {
    if (!docId) { setServerThreads([]); return }
    void loadServerThreads(docId)
  }, [docId, threadCatalogRev, loadServerThreads])

  useEffect(() => {
    if (docId) {
      saveUISession({ docId, threadId, docName: docName || undefined })
    } else {
      saveUISession(null)
    }
  }, [docId, threadId, docName])

  useEffect(() => {
    if (sessionRestoredRef.current || documentsLoading) return
    if (documents.length === 0) return
    if (docId !== null) {
      sessionRestoredRef.current = true
      return
    }
    const snap = loadUISession()
    if (!snap) {
      sessionRestoredRef.current = true
      return
    }
    const d = documents.find((x) => x.doc_id === snap.docId)
    if (!d) {
      sessionRestoredRef.current = true
      return
    }
    setDocId(d.doc_id)
    setDocName(snap.docName || d.filename)
    setThreadId(snap.threadId)
    setHydrateVersion((h) => h + 1)
    setExportMsgs([])
    sessionRestoredRef.current = true
  }, [documentsLoading, documents, docId])

  useEffect(() => {
    if (documentsLoading) return
    applyWorkspaceFromStorage()
  }, [documentsLoading, applyWorkspaceFromStorage])

  useEffect(() => {
    const onStorage = (e: StorageEvent) => {
      if (e.storageArea !== localStorage || !e.key) return
      if (e.key === UI_SESSION_STORAGE_KEY) {
        void (async () => {
          try {
            const raw = e.newValue
            if (raw) {
              const o = JSON.parse(raw) as { docId?: unknown }
              const docFromSnap = typeof o.docId === 'string' ? o.docId : null
              if (docFromSnap && !documentsRef.current.some((x) => x.doc_id === docFromSnap)) {
                await loadDocuments()
              }
            }
          } catch {
            /* ignore malformed snapshot */
          }
          applyWorkspaceFromStorage()
          setThreadCatalogRev((n) => n + 1)
        })()
        return
      }
      if (e.key === THREAD_CATALOG_STORAGE_KEY || isMessageStorageKey(e.key)) {
        setThreadCatalogRev((n) => n + 1)
        if (docIdRef.current && threadIdRef.current && e.key === msgStorageKey(docIdRef.current, threadIdRef.current)) {
          setHydrateVersion((h) => h + 1)
        }
      }
    }
    window.addEventListener('storage', onStorage)
    return () => window.removeEventListener('storage', onStorage)
  }, [applyWorkspaceFromStorage, loadDocuments])

  useEffect(() => {
    const onVis = () => {
      if (document.visibilityState !== 'visible') return
      void (async () => {
        const snap = loadUISession()
        const docFromSnap = snap?.docId
        if (docFromSnap && !documentsRef.current.some((x) => x.doc_id === docFromSnap)) {
          await loadDocuments()
        }
        applyWorkspaceFromStorage()
        setThreadCatalogRev((n) => n + 1)
      })()
    }
    document.addEventListener('visibilitychange', onVis)
    return () => document.removeEventListener('visibilitychange', onVis)
  }, [applyWorkspaceFromStorage, loadDocuments])

  // Map backend threads → shape LibrarySidebar expects.
  // If a title is being generated for a thread not yet in the server response,
  // inject an optimistic placeholder at the top so it appears immediately.
  const threads = useMemo(() => {
    const mapped = serverThreads.map((t) => ({
      threadId: t.thread_id,
      docId: t.doc_id,
      title: t.title,
      updatedAt: t.created_at,
    }))
    if (pendingTitleThreadId && docId && !mapped.some((t) => t.threadId === pendingTitleThreadId)) {
      return [
        { threadId: pendingTitleThreadId, docId, title: 'New chat', updatedAt: new Date().toISOString() },
        ...mapped,
      ]
    }
    return mapped
  }, [serverThreads, pendingTitleThreadId, docId])

  const activeThreadLabel = useMemo(() => {
    if (!threadId) return ''
    const row = threads.find((t) => t.threadId === threadId)
    if (!row || row.title === '…' || row.title === '...' || row.title === 'New chat') return ''
    // Show the full AI-generated title; backend already limits it to ≤52 chars.
    return formatThreadSummaryDisplay(row.title.trim() || 'Chat')
  }, [threadId, threads])

  const handleUploadFile = useCallback(
    async (f: File) => {
      setUploadErr(null)
      setUploadPending(true)
      try {
        const data = await uploadPdf(f)
        setDocId(data.doc_id)
        setDocName(data.filename)
        setThreadId(null)
        setHydrateVersion((h) => h + 1)
        setExportMsgs([])
        await loadDocuments()
      } catch (e) {
        setUploadErr(e instanceof Error ? e.message : 'Upload failed')
      } finally {
        setUploadPending(false)
      }
    },
    [loadDocuments],
  )

  const onSelectDocument = useCallback((d: DocumentSummary) => {
    setDocId(d.doc_id)
    setDocName(d.filename)
    setThreadId(null)
    setHydrateVersion((h) => h + 1)
    setExportMsgs([])
  }, [])

  const onDeleteDocument = useCallback(
    async (d: DocumentSummary) => {
      const confirmed = await showConfirm(
        'Remove Document',
        `"${d.filename}" will be permanently deleted. This cannot be undone.`,
        'Remove',
      )
      if (!confirmed) return
      try {
        await deleteDocument(d.doc_id)
        clearClientDataForDoc(d.doc_id)
        if (docId === d.doc_id) {
          setDocId(null)
          setDocName('')
          setThreadId(null)
          setHydrateVersion((h) => h + 1)
          setExportMsgs([])
        }
        setThreadCatalogRev((n) => n + 1)
        await loadDocuments()
      } catch (e) {
        await showAlert('Delete Failed', e instanceof Error ? e.message : 'Delete failed')
      }
    },
    [docId, loadDocuments, showConfirm, showAlert],
  )
  const onSelectThread = useCallback((tid: string) => {
    setThreadId(tid)
    setHydrateVersion((h) => h + 1)
  }, [])

  const onNewChat = useCallback(() => {
    if (!docId) return
    const newTid = crypto.randomUUID()
    setThreadId(newTid)
    setHydrateVersion((h) => h + 1)
    setExportMsgs([])
    setThreadCatalogRev((n) => n + 1)
  }, [docId])

  const onDeleteThread = useCallback(
    async (tid: string) => {
      if (!docId) return
      const entry = serverThreads.find((t) => t.thread_id === tid)
      const title = (entry?.title || 'Conversation').trim()
      const shown = title.length > 44 ? `${title.slice(0, 44)}…` : title
      const confirmed = await showConfirm(
        'Delete Conversation',
        `"${shown}" will be permanently deleted.`,
        'Delete',
      )
      if (!confirmed) return
      removeThreadClient(docId, tid)
      if (threadId === tid) {
        const rest = serverThreads.filter((t) => t.thread_id !== tid)
        setThreadId(rest.length > 0 ? rest[0].thread_id : null)
        setHydrateVersion((h) => h + 1)
        setExportMsgs([])
      }
      try {
        await deleteThread(tid)
      } catch (e) {
        await showAlert(
          'Cleanup Incomplete',
          'The conversation was removed from this device, but a server-side cleanup error occurred: ' +
            (e instanceof Error ? e.message : String(e)),
        )
      }
      setThreadCatalogRev((n) => n + 1)
    },
    [docId, threadId, serverThreads, showConfirm, showAlert],
  )
  const openCitation = useCallback((s: ChatSource) => {
    setCitationSource(s)
    setCitationOpen(true)
  }, [])

  const bumpThreadCatalog = useCallback(() => {
    setThreadCatalogRev((n) => n + 1)
  }, [])

  // All hooks are declared above this point — the login gate is safe here.
  if (!adminPw) {
    return (
      <div className="relative min-h-screen overflow-hidden bg-background text-foreground">
        <div className="pointer-events-none absolute inset-0 bg-gradient-to-b from-background to-background/80" />

        <div className="relative mx-auto flex min-h-screen w-full max-w-xl items-center px-6">
          <div className="w-full rounded-3xl border border-border/70 bg-card/70 p-7 shadow-[0_24px_60px_-32px_rgba(0,0,0,0.75)] backdrop-blur-xl">
            <div className="min-w-0">
              <div className="text-base font-semibold tracking-tight">Risk Auditor Assistant</div>
              <p className="mt-0.5 text-sm text-muted-foreground">Enter the password to continue</p>
            </div>

            <div className="mt-5 grid gap-3">
              <input
                className="h-11 w-full rounded-xl border border-border/70 bg-background/60 px-3.5 text-sm shadow-sm outline-none transition focus:border-blue-500/60 focus:ring-2 focus:ring-blue-500/20"
                placeholder="Password"
                type="password"
                autoFocus
                value={adminPwDraft}
                onChange={(e) => setAdminPwDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') void persistLogin(adminPwDraft)
                }}
              />
              {loginErr && (
                <div className="rounded-xl border border-destructive/30 bg-destructive/10 px-3.5 py-2 text-xs text-destructive">
                  {loginErr}
                </div>
              )}
              <div className="flex justify-end">
                <Button
                  onClick={() => void persistLogin(adminPwDraft)}
                  disabled={loginPending || !adminPwDraft.trim()}
                  className="h-10 rounded-xl bg-blue-600 px-5 text-white shadow-md shadow-blue-900/20 hover:bg-blue-700 disabled:opacity-50"
                >
                  {loginPending ? 'Checking…' : 'Login'}
                </Button>
              </div>
            </div>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="flex h-dvh w-full flex-row overflow-hidden bg-background">
      <input
        ref={hiddenFileRef}
        type="file"
        accept=".pdf,application/pdf"
        className="hidden"
        onChange={(e) => {
          const f = e.target.files?.[0]
          if (f) void handleUploadFile(f)
          e.target.value = ''
        }}
      />

      <LibrarySidebar
        collapsed={sidebarCollapsed}
        onToggleCollapsed={() => setSidebarCollapsed((c) => !c)}
        documents={documents}
        documentsLoading={documentsLoading}
        onRefreshDocuments={loadDocuments}
        selectedDocId={docId}
        onSelectDocument={onSelectDocument}
        onDeleteDocument={onDeleteDocument}
        threads={threads}
        activeThreadId={threadId}
        pendingTitleThreadId={pendingTitleThreadId}
        onSelectThread={onSelectThread}
        onNewChat={onNewChat}
        onDeleteThread={onDeleteThread}
      />

      <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
        <header className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-b border-border bg-card/80 px-4 py-2.5 backdrop-blur-md">
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold tracking-tight text-foreground">Risk Auditor Assistant</p>
            <p className="truncate text-xs text-muted-foreground">Grounded regulatory Q&A</p>
          </div>
          <div className="flex shrink-0 flex-wrap items-center gap-2">
            <Button
              type="button"
              variant="default"
              size="sm"
              className="gap-2 border-0 bg-blue-600 text-white shadow-md hover:bg-blue-700 focus-visible:ring-2 focus-visible:ring-blue-400/80 disabled:opacity-60 active:scale-[0.97] dark:bg-blue-600 dark:text-white dark:hover:bg-blue-500"
              disabled={uploadPending}
              onClick={() => hiddenFileRef.current?.click()}
            >
              {uploadPending ? <Loader2 className="h-5 w-5 animate-spin" aria-hidden /> : <Upload className="h-5 w-5 stroke-[1.85]" aria-hidden />}
              {uploadPending ? 'Indexing…' : 'Upload PDF'}
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="gap-2 active:scale-[0.97]"
              disabled={!docId}
              onClick={() =>
                exportText(
                  docName || 'document',
                  exportMsgs.length ? exportMsgs : [{ role: 'user', content: '(no messages yet)' }],
                )
              }
            >
              <Download className="h-5 w-5 stroke-[1.85] text-foreground/95" aria-hidden />
              Export
            </Button>

            <Button
              type="button"
              size="sm"
              className="gap-2 border-0 bg-rose-600 text-white shadow-md hover:bg-rose-700 focus-visible:ring-2 focus-visible:ring-rose-400/70 disabled:opacity-60 active:scale-[0.97]"
              onClick={logout}
            >
              <LogOut className="h-4 w-4 text-white" aria-hidden />
              Log out
            </Button>
          </div>
        </header>

        <div className="scrollbar-minimal flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto p-4">
          {uploadErr && (
            <div className="rounded-xl border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">{uploadErr}</div>
          )}

          <div className="flex min-h-0 flex-1 flex-col">
            <ChatPanel
              docId={docId}
              docName={docName}
              threadLabel={activeThreadLabel}
              threadId={threadId}
              hydrateVersion={hydrateVersion}
              onMessagesChange={setExportMsgs}
              onOpenCitation={openCitation}
              onThreadCatalogChanged={bumpThreadCatalog}
              onTitleGenerating={handleTitleGenerating}
              onNewChat={onNewChat}
            />
          </div>
        </div>
      </div>

      <CitationSheet open={citationOpen} onOpenChange={setCitationOpen} source={citationSource} />

      {dialogState && (
        <ConfirmDialog
          open={true}
          title={dialogState.title}
          description={dialogState.description}
          confirmLabel={dialogState.confirmLabel}
          cancelLabel={dialogState.cancelLabel}
          variant={dialogState.variant}
          showCancel={dialogState.showCancel}
          onConfirm={() => closeDialog(true)}
          onCancel={() => closeDialog(false)}
        />
      )}
    </div>
  )
}
