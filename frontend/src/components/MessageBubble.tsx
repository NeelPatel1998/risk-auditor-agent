import { cn } from '@/lib/utils'
import { BookOpen } from 'lucide-react'
import ReactMarkdown from 'react-markdown'

export type ChatSource = {
  index: number
  content: string
  distance?: number | null
  metadata?: Record<string, unknown>
}

export type Msg = {
  role: 'user' | 'assistant'
  content: string
  sources?: ChatSource[]
}

type Props = {
  msg: Msg
  onOpenSource?: (s: ChatSource) => void
}

/**
 * Return only the sources the model actually cited.
 * Handles both [Source N] and [Source N, Page X] annotation styles.
 */
function citedSources(content: string, sources: ChatSource[]): ChatSource[] {
  const cited = new Set<number>()
  // Match [Source N] and [Source N, Page X] — allow any chars between N and ]
  const re = /\[Source\s*(\d+)[^\]]*\]/gi
  let m: RegExpExecArray | null
  while ((m = re.exec(content)) !== null) cited.add(parseInt(m[1], 10))
  // Fallback: if model cited nothing explicitly, show all retrieved sources
  if (cited.size === 0) return sources
  return sources.filter((s) => cited.has(s.index))
}

/** Pull a human-readable page label from a chunk (handles multi-page chunks). */
function pageFromContent(content: string): string | null {
  const pages: number[] = []
  const re = /\[Page\s*(\d+)\]/g
  let m: RegExpExecArray | null
  while ((m = re.exec(content)) !== null) {
    const n = parseInt(m[1], 10)
    if (!pages.includes(n)) pages.push(n)
  }
  if (pages.length === 0) return null
  pages.sort((a, b) => a - b)
  return pages.length > 1 ? `pp.\u00a0${pages[0]}–${pages[pages.length - 1]}` : `p.\u00a0${pages[0]}`
}

/** First meaningful sentence / phrase from a chunk (max ~120 chars). */
function previewFromContent(content: string): string {
  // Strip [Page N] headers, collapse whitespace, take the first 120 chars
  const clean = content
    .replace(/\[Page\s*\d+\]\s*/g, '')
    .replace(/\s+/g, ' ')
    .trim()
  if (clean.length <= 120) return clean
  const cut = clean.slice(0, 120)
  const lastSpace = cut.lastIndexOf(' ')
  return (lastSpace > 60 ? cut.slice(0, lastSpace) : cut) + '…'
}

export function MessageBubble({ msg, onOpenSource }: Props) {
  const isUser = msg.role === 'user'
  return (
    <div className={cn('mb-3 flex', isUser ? 'justify-end' : 'justify-start')}>
      <div
        className={cn(
          'max-w-[min(100%,44rem)] rounded-2xl px-4 py-3 text-sm leading-relaxed',
          isUser
            ? 'border border-border/80 bg-secondary text-secondary-foreground shadow-card'
            : 'border border-border bg-card text-card-foreground shadow-card',
        )}
      >
        {isUser ? (
          <p className="whitespace-pre-wrap">{msg.content}</p>
        ) : (
          <div className="max-w-none text-sm [&_a]:font-medium [&_a]:text-foreground/85 [&_a]:underline [&_a]:underline-offset-2 [&_code]:rounded-md [&_code]:bg-muted [&_code]:px-1.5 [&_code]:py-0.5 [&_code]:text-xs [&_h1]:mb-2 [&_h1]:text-base [&_h1]:font-semibold [&_h2]:mb-2 [&_h2]:mt-3 [&_h2]:text-sm [&_h2]:font-semibold [&_li]:my-0.5 [&_ol]:my-2 [&_ol]:list-decimal [&_ol]:pl-5 [&_p]:my-2 [&_strong]:font-semibold [&_strong]:text-foreground [&_ul]:my-2 [&_ul]:list-disc [&_ul]:pl-5">
            <ReactMarkdown>{msg.content}</ReactMarkdown>
          </div>
        )}

        {!isUser && msg.sources && msg.sources.length > 0 && (() => {
          const visible = citedSources(msg.content, msg.sources)
          if (visible.length === 0) return null
          return (
            <div className="mt-4 border-t border-border pt-3">
              {/* Header row */}
              <div className="mb-2.5 flex items-center gap-1.5">
                <BookOpen className="h-3.5 w-3.5 shrink-0 text-muted-foreground/70" strokeWidth={1.75} aria-hidden />
                <span className="text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground/70">
                  Sources · {visible.length} segment{visible.length === 1 ? '' : 's'}
                </span>
              </div>
              <p className="mb-2.5 text-[10px] leading-snug text-muted-foreground/65">
                Retrieved excerpts may include tables or disclosure prompts; open a segment to verify wording in the PDF.
              </p>

              {/* Citation cards */}
              <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-2">
                {visible.map((s) => {
                  const page = pageFromContent(s.content)
                  const preview = previewFromContent(s.content)
                  const clickable = !!onOpenSource
                  return (
                    <button
                      key={s.index}
                      type="button"
                      disabled={!clickable}
                      onClick={() => onOpenSource?.(s)}
                      className={cn(
                        'group flex flex-col gap-1 rounded-xl border border-border/70 bg-muted/30 px-3 py-2.5 text-left transition-all',
                        clickable
                          ? 'cursor-pointer hover:border-blue-500/40 hover:bg-blue-500/5 active:scale-[0.98]'
                          : 'cursor-default',
                      )}
                    >
                      {/* Badge row */}
                      <div className="flex items-center gap-2">
                        <span className="inline-flex items-center rounded-md bg-blue-500/10 px-1.5 py-0.5 text-[10px] font-bold tabular-nums text-blue-400 ring-1 ring-blue-500/20">
                          S{s.index}
                        </span>
                        {page && (
                          <span className="text-[10px] font-medium text-muted-foreground/70">
                            {page}
                          </span>
                        )}
                        {clickable && (
                          <span className="ml-auto text-[10px] text-muted-foreground/40 transition group-hover:text-blue-400/70">
                            View ↗
                          </span>
                        )}
                      </div>
                      {/* Content preview */}
                      <p className="line-clamp-2 text-[11px] leading-relaxed text-muted-foreground/80">
                        {preview}
                      </p>
                    </button>
                  )
                })}
              </div>
            </div>
          )
        })()}
      </div>
    </div>
  )
}
