import { Button } from '@/components/ui/button'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { ScrollArea } from '@/components/ui/scroll-area'
import type { DocumentSummary } from '@/lib/api'
import { parseStoredUtc } from '@/lib/datetime'
import { cn } from '@/lib/utils'
import { type ThreadCatalogEntry, formatThreadSummaryDisplay } from '@/lib/threadStorage'
import {
  ChevronDown,
  ChevronRight,
  FileText,
  Inbox,
  MessageSquare,
  PanelLeft,
  PanelLeftClose,
  Plus,
  RefreshCw,
  Trash2,
} from 'lucide-react'
import { useState, type ReactNode } from 'react'

type Props = {
  collapsed: boolean
  onToggleCollapsed: () => void
  documents: DocumentSummary[]
  documentsLoading: boolean
  onRefreshDocuments: () => void
  selectedDocId: string | null
  onSelectDocument: (doc: DocumentSummary) => void
  onDeleteDocument: (doc: DocumentSummary) => void | Promise<void>
  threads: ThreadCatalogEntry[]
  activeThreadId: string | null
  pendingTitleThreadId?: string | null
  onSelectThread: (threadId: string) => void
  onNewChat: () => void
  onDeleteThread: (threadId: string) => void | Promise<void>
}

function CountBadge({ children }: { children: ReactNode }) {
  return (
    <span className="inline-flex min-w-[1.25rem] shrink-0 items-center justify-center rounded-full bg-muted px-1.5 py-0.5 text-[10px] font-semibold tabular-nums text-foreground/80">
      {children}
    </span>
  )
}

export function LibrarySidebar({
  collapsed,
  onToggleCollapsed,
  documents,
  documentsLoading,
  onRefreshDocuments,
  selectedDocId,
  onSelectDocument,
  onDeleteDocument,
  threads,
  activeThreadId,
  pendingTitleThreadId,
  onSelectThread,
  onNewChat,
  onDeleteThread,
}: Props) {
  const [docsOpen, setDocsOpen] = useState(true)
  const [threadsOpen, setThreadsOpen] = useState(true)
  const [deletingDocId, setDeletingDocId] = useState<string | null>(null)

  if (collapsed) {
    return (
      <aside className="flex h-full min-h-0 w-14 shrink-0 flex-col items-center gap-3 border-r border-border bg-card/95 py-3 backdrop-blur-md">
        <Button type="button" size="icon" variant="ghost" className="shrink-0 text-foreground/90" onClick={onToggleCollapsed} aria-label="Expand library">
          <PanelLeft className="h-6 w-6 stroke-[1.85]" />
        </Button>
        <Button type="button" size="icon" variant="ghost" className="shrink-0 text-foreground/90" onClick={onNewChat} disabled={!selectedDocId} aria-label="New chat">
          <Plus className="h-5 w-5 stroke-[1.85]" />
        </Button>
      </aside>
    )
  }

  return (
    <aside className="flex h-full min-h-0 w-[min(100%,20rem)] max-w-[min(100%,20rem)] shrink-0 flex-col overflow-hidden border-r border-border bg-gradient-to-b from-card via-card to-muted/30 shadow-card backdrop-blur-md">
      <div className="shrink-0 border-b border-border/80 bg-muted/15 px-4 py-3.5">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <h2 className="text-sm font-semibold leading-none tracking-tight text-foreground">Library</h2>
            <p className="mt-1.5 text-[11px] leading-relaxed text-muted-foreground">PDFs and saved conversations for each file</p>
          </div>
          <Button type="button" size="icon" variant="ghost" className="mt-0.5 h-9 w-9 shrink-0 text-foreground/85 hover:text-foreground" onClick={onToggleCollapsed} aria-label="Collapse library">
            <PanelLeftClose className="h-5 w-5 stroke-[1.85]" />
          </Button>
        </div>
      </div>

      <ScrollArea className="min-h-0 min-w-0 flex-1">
        <div className="flex min-w-0 max-w-full flex-col gap-4 p-4 pb-6">
          {/* PDFs list */}
          <section className="overflow-hidden rounded-xl border border-border/70 bg-card/80 shadow-sm ring-1 ring-border/40">
            <Collapsible open={docsOpen} onOpenChange={setDocsOpen}>
              <div className="flex items-center gap-1 border-b border-border/50 bg-muted/25 px-2 py-1.5 pr-1.5">
                <CollapsibleTrigger
                  type="button"
                  className="flex min-w-0 flex-1 items-center gap-2 rounded-lg px-2 py-2 text-left transition-colors hover:bg-muted/60"
                >
                  <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-muted/80 text-foreground/55">
                    <FileText className="h-5 w-5 stroke-[1.75]" aria-hidden />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="text-[13px] font-semibold text-foreground">PDFs</span>
                      {!documentsLoading && <CountBadge>{documents.length}</CountBadge>}
                    </div>
                  </div>
                  {docsOpen ? <ChevronDown className="h-5 w-5 shrink-0 text-foreground/75" /> : <ChevronRight className="h-5 w-5 shrink-0 text-foreground/75" />}
                </CollapsibleTrigger>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="h-9 w-9 shrink-0 text-foreground/80 hover:text-foreground"
                  onClick={(e) => {
                    e.stopPropagation()
                    void onRefreshDocuments()
                  }}
                  disabled={documentsLoading}
                  aria-label="Refresh PDF list"
                >
                  <RefreshCw className={cn('h-5 w-5 stroke-[1.85]', documentsLoading && 'animate-spin')} />
                </Button>
              </div>

              <CollapsibleContent>
                <div className="p-3 pt-2">
                  {documentsLoading ? (
                    <p className="py-6 text-center text-xs text-muted-foreground">Loading PDFs…</p>
                  ) : documents.length === 0 ? (
                    <div className="rounded-lg border border-dashed border-border/90 bg-muted/20 px-4 py-8 text-center">
                      <Inbox className="mx-auto h-10 w-10 text-foreground/50" strokeWidth={1.35} aria-hidden />
                      <p className="mt-3 text-xs font-medium text-foreground">No PDFs yet</p>
                      <p className="mx-auto mt-1.5 max-w-[14rem] text-[11px] leading-relaxed text-muted-foreground">Use <span className="font-medium text-foreground/90">Upload PDF</span> in the top bar to add a file.</p>
                    </div>
                  ) : (
                    <ul className="flex flex-col gap-1.5">
                      {documents.map((d) => (
                        <li
                          key={d.doc_id}
                          className={cn(
                            'group grid min-w-0 max-w-full grid-cols-[minmax(0,1fr)_auto] items-center gap-2 rounded-lg border transition-colors',
                            selectedDocId === d.doc_id
                              ? 'border-border/90 bg-muted/50 shadow-sm ring-1 ring-foreground/[0.06]'
                              : 'border-transparent bg-muted/12 hover:border-border/70 hover:bg-muted/30',
                          )}
                        >
                          <button
                            type="button"
                            onClick={() => onSelectDocument(d)}
                            className="flex min-w-0 items-center gap-3 overflow-hidden rounded-lg py-2.5 pl-3 pr-1 text-left transition-colors"
                          >
                            <span
                              className={cn(
                                'flex h-6 w-6 shrink-0 items-center justify-center rounded shadow-sm ring-1 ring-border/45',
                                selectedDocId === d.doc_id ? 'bg-background/95 text-foreground/65' : 'bg-background/70 text-foreground/45',
                              )}
                            >
                              <FileText className="h-3.5 w-3.5 stroke-[1.5]" aria-hidden />
                            </span>
                            <span
                              className="block min-w-0 flex-1 truncate text-[13px] font-medium leading-snug text-foreground"
                              title={d.filename}
                            >
                              {d.filename}
                            </span>
                          </button>
                          <div className="flex shrink-0 items-center justify-self-end pr-1.5">
                            <Button
                              type="button"
                              variant="ghost"
                              size="icon"
                              className="h-8 w-8 shrink-0 rounded-md border border-transparent text-foreground/65 transition-colors hover:border-destructive/45 hover:bg-destructive/10 hover:text-destructive"
                              disabled={deletingDocId === d.doc_id}
                              aria-label={`Remove ${d.filename} from index`}
                              onClick={(e) => {
                                e.preventDefault()
                                e.stopPropagation()
                                void (async () => {
                                  setDeletingDocId(d.doc_id)
                                  try {
                                    await onDeleteDocument(d)
                                  } finally {
                                    setDeletingDocId(null)
                                  }
                                })()
                              }}
                            >
                              <Trash2 className="h-4 w-4 stroke-[1.65]" />
                            </Button>
                          </div>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </CollapsibleContent>
            </Collapsible>
          </section>

          {/* Conversations */}
          <section className="overflow-hidden rounded-xl border border-border/70 bg-card/80 shadow-sm ring-1 ring-border/40">
            <Collapsible open={threadsOpen} onOpenChange={setThreadsOpen}>
              <div className="flex items-center gap-1 border-b border-border/50 bg-muted/25 px-2 py-1.5 pr-1.5">
                <CollapsibleTrigger
                  type="button"
                  className="flex min-w-0 flex-1 items-center gap-2 rounded-lg px-2 py-2 text-left transition-colors hover:bg-muted/60"
                >
                  <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-muted/80 text-foreground/55">
                    <MessageSquare className="h-5 w-5 stroke-[1.75]" aria-hidden />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="text-[13px] font-semibold text-foreground">Conversations</span>
                      {selectedDocId && threads.length > 0 && <CountBadge>{threads.length}</CountBadge>}
                    </div>
                  </div>
                  {threadsOpen ? <ChevronDown className="h-5 w-5 shrink-0 text-foreground/75" /> : <ChevronRight className="h-5 w-5 shrink-0 text-foreground/75" />}
                </CollapsibleTrigger>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="h-9 w-9 shrink-0 text-foreground/80 hover:text-foreground"
                  disabled={!selectedDocId}
                  aria-label="New conversation"
                  onClick={(e) => {
                    e.preventDefault()
                    e.stopPropagation()
                    onNewChat()
                  }}
                >
                  <Plus className="h-5 w-5 stroke-[1.85]" />
                </Button>
              </div>

              <CollapsibleContent>
                <div className="space-y-3 p-3 pt-3">
                  {!selectedDocId ? (
                    <div className="rounded-lg border border-dashed border-border/90 bg-muted/15 px-4 py-7 text-center">
                      <MessageSquare className="mx-auto h-10 w-10 text-foreground/45" strokeWidth={1.35} aria-hidden />
                      <p className="mt-3 text-xs font-medium text-foreground">Choose a PDF first</p>
                      <p className="mx-auto mt-1.5 max-w-[14rem] text-[11px] leading-relaxed text-muted-foreground">Pick a row under PDFs to list conversations for that upload.</p>
                    </div>
                  ) : threads.length === 0 ? (
                    <div className="rounded-lg border border-dashed border-border/90 bg-muted/15 px-4 py-7 text-center">
                      <p className="text-xs font-medium text-foreground">No saved threads</p>
                      <p className="mx-auto mt-1.5 max-w-[14rem] text-[11px] leading-relaxed text-muted-foreground">
                        Tap <span className="font-medium text-foreground/90">+</span> beside Conversations, then send a message to save a thread here.
                      </p>
                    </div>
                  ) : (
                    <ul className="flex flex-col gap-1.5">
                      {threads.filter((t) => t.title !== '…' && t.title !== '...').map((t) => {
                        const isGenerating = pendingTitleThreadId === t.threadId
                        // Use the full AI-generated title — the backend already keeps it ≤52 chars.
                        const displayTitle = isGenerating
                          ? null
                          : formatThreadSummaryDisplay(t.title.trim() || 'New chat')
                        return (
                        <li
                          key={t.threadId}
                          className={cn(
                            'group grid min-w-0 max-w-full grid-cols-[minmax(0,1fr)_auto] items-start gap-2 rounded-lg border transition-colors',
                            activeThreadId === t.threadId
                              ? 'border-border/90 bg-muted/45 shadow-sm ring-1 ring-foreground/[0.05]'
                              : 'border-transparent bg-muted/10 hover:border-border/70 hover:bg-muted/35',
                          )}
                        >
                          <button
                            type="button"
                            onClick={() => onSelectThread(t.threadId)}
                            className="flex min-w-0 flex-col gap-1 overflow-hidden rounded-lg py-2.5 pl-3 pr-1 text-left transition-colors"
                          >
                            {isGenerating ? (
                              <span className="flex min-w-0 items-center gap-1.5">
                                <span className="h-2.5 w-2.5 shrink-0 rounded-full bg-blue-400/70 animate-pulse" />
                                <span className="block min-w-0 flex-1 truncate text-[13px] font-medium text-muted-foreground">Generating title…</span>
                              </span>
                            ) : (
                              <span
                                className="line-clamp-2 min-w-0 overflow-hidden break-words text-[13px] font-medium leading-snug text-foreground"
                                title={displayTitle ?? undefined}
                              >
                                {displayTitle}
                              </span>
                            )}
                            <span className="min-w-0 truncate text-[10px] text-muted-foreground">
                              {parseStoredUtc(t.updatedAt).toLocaleString(undefined, {
                                dateStyle: 'medium',
                                timeStyle: 'short',
                              })}
                            </span>
                          </button>
                          <div className="flex shrink-0 items-start justify-self-end pr-1.5 pt-2">
                            <Button
                              type="button"
                              variant="ghost"
                              size="icon"
                              className="h-8 w-8 shrink-0 rounded-md border border-transparent text-foreground/65 transition-colors hover:border-destructive/45 hover:bg-destructive/10 hover:text-destructive"
                              aria-label={`Delete conversation: ${t.title}`}
                              onClick={(e) => {
                                e.preventDefault()
                                e.stopPropagation()
                                onDeleteThread(t.threadId)
                              }}
                            >
                              <Trash2 className="h-4 w-4 stroke-[1.65]" />
                            </Button>
                          </div>
                        </li>
                        )
                      })}
                    </ul>
                  )}
                </div>
              </CollapsibleContent>
            </Collapsible>
          </section>
        </div>
      </ScrollArea>
    </aside>
  )
}
