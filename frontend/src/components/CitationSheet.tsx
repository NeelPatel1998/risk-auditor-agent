import type { ChatSource } from '@/components/MessageBubble'
import { fetchDocumentPages, type DocPage } from '@/lib/api'
import { cn } from '@/lib/utils'
import { Sheet, SheetContent, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { BookOpen, FileText } from 'lucide-react'
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'

/* ─── text cleanup ────────────────────────────────────────────────────────── */

/** Lines that are PDF chrome — repeating headers, footers, page numbers. */
const ARTIFACT_RES = [
  /^Office of the Superintendent of Financial Institutions$/,
  /^Bureau du surintendant des institutions financi[eè]res/i,
  /^Guideline\s+E[- ]?\d+/i,
  /^Page\s*\d+$/i,
  /^\d{1,3}$/,
  /^www\.\S+$/i,
]

function isArtifact(line: string): boolean {
  const t = line.trim()
  if (!t) return true
  return ARTIFACT_RES.some((re) => re.test(t))
}

/** Heading patterns — same as the backend chunker */
const HEADING_RE =
  /^(?:(?:Principle|Section|Annex|Appendix|Chapter|Article|Outcome|Footnotes?|Table of Contents)\s.*|[A-Z]\.\d*\s+\S.*|\d+\.\d+(?:\.\d+)*\s+[A-Z].*|[A-Z][A-Z , -]{3,60})$/

/** Top-level bullet: • ▪ ● – */
const BULLET_RE  = /^[\u2022\u25AA\u25CF•▪●–]\s/
/** Sub-bullet: ○ ◦ ▫ ‣  or  "- " when indented */
const SUBBULLET_RE = /^[\u25CB\u25E6\u25AB\u2023○◦▫‣]\s/

function isBulletLine(line: string): boolean {
  return BULLET_RE.test(line) || SUBBULLET_RE.test(line)
}

/**
 * Clean raw PyMuPDF page text:
 * 1. Strip artifact lines
 * 2. Join hard-wrapped lines (PDF line breaks mid-sentence)
 * 3. Preserve bullet and sub-bullet items as separate paragraphs
 * 4. Return clean paragraphs
 */
function cleanPageText(raw: string): string[] {
  const lines = raw.split('\n')
  const cleaned: string[] = []

  for (const line of lines) {
    const t = line.trimEnd()
    if (isArtifact(t)) continue
    cleaned.push(t)
  }

  const paragraphs: string[] = []
  let buf = ''

  const flush = () => { if (buf) { paragraphs.push(buf); buf = '' } }

  for (const line of cleaned) {
    const t = line.trim()
    if (!t) { flush(); continue }

    if (!buf) { buf = t; continue }

    const currIsBullet  = isBulletLine(t)
    const currIsHeading = HEADING_RE.test(t)
    const prevIsBullet  = isBulletLine(buf)
    const prevIsHeading = HEADING_RE.test(buf)

    // New heading or bullet always starts a new block
    if (currIsHeading || currIsBullet) {
      flush()
      buf = t
      continue
    }

    // Previous was a heading — flush UNLESS it looks like a wrapped continuation
    // e.g. "Principle 3.3: ... performance and\n documentation." → join
    if (prevIsHeading) {
      const prevEndsClean = /[.!?:"\u201D]\s*$/.test(buf)
      if (prevEndsClean || /^[A-Z]/.test(t)) {
        flush()
        buf = t
        continue
      }
      buf += ' ' + t
      continue
    }

    // If we're inside a bullet and the next line is a lowercase continuation
    // of that bullet (hard-wrapped), join it to the bullet
    if (prevIsBullet && /^[a-z(]/.test(t)) {
      buf += ' ' + t
      continue
    }

    // Previous line ends with colon → next line is likely a list or new block
    if (/:\s*$/.test(buf)) {
      flush()
      buf = t
      continue
    }

    // Previous ends with sentence-ending punctuation + next starts uppercase
    const prevEndsStop  = /[.!?"\u201D]\s*$/.test(buf)
    const currStartsUp  = /^[A-Z]/.test(t)

    if (prevEndsStop && currStartsUp) {
      // Short prior line = likely a standalone item, break
      if (buf.length < 55) { flush(); buf = t; continue }
      // Long prior line = probably full-width PDF wrap, join
      buf += ' ' + t
      continue
    }

    // Previous ends with comma/semicolon + next starts lowercase → join
    // (mid-sentence wrap, common in bullet continuations)
    if (/[,;]\s*$/.test(buf) && /^[a-z(]/.test(t)) {
      buf += ' ' + t
      continue
    }

    // Default: join (hard-wrapped continuation of the same paragraph)
    buf += ' ' + t
  }
  flush()

  return paragraphs
}

/* ─── citation matching ───────────────────────────────────────────────────── */

function pageFromContent(content: string): number {
  const m = content.match(/\[Page\s*(\d+)\]/)
  return m ? parseInt(m[1], 10) : 1
}

/** Return every unique page number referenced inside a chunk's content. */
function allPagesFromContent(content: string): Set<number> {
  const pages = new Set<number>()
  const re = /\[Page\s*(\d+)\]/g
  let m: RegExpExecArray | null
  while ((m = re.exec(content)) !== null) pages.add(parseInt(m[1], 10))
  if (pages.size === 0) pages.add(1)
  return pages
}

function normalize(text: string): string {
  return text.replace(/\[Page\s*\d+\]\n?/g, '').replace(/\s+/g, ' ').trim()
}

/**
 * Find which paragraph indices in a page's cleaned paragraphs match
 * the cited chunk. Returns a Set of paragraph indices to highlight.
 */
function findCitedParagraphs(paragraphs: string[], chunkContent: string): Set<number> {
  const chunkNorm = normalize(chunkContent)
  if (!chunkNorm || chunkNorm.length < 20) return new Set()

  const matched = new Set<number>()

  // Try to match each paragraph against substrings of the chunk
  for (let i = 0; i < paragraphs.length; i++) {
    const paraNorm = paragraphs[i].replace(/\s+/g, ' ').trim()
    if (paraNorm.length < 10) continue

    // Check if this paragraph appears in the chunk
    const paraSlice = paraNorm.slice(0, 120)
    if (chunkNorm.includes(paraSlice)) {
      matched.add(i)
      continue
    }

    // Check if the chunk starts/ends within this paragraph
    const chunkStart = chunkNorm.slice(0, 100)
    const chunkEnd = chunkNorm.slice(-100)
    if (paraNorm.includes(chunkStart) || paraNorm.includes(chunkEnd)) {
      matched.add(i)
    }
  }

  // If no individual matches, try a broader approach — find consecutive
  // paragraphs that overlap with the full chunk text
  if (matched.size === 0) {
    let running = ''
    for (let i = 0; i < paragraphs.length; i++) {
      const paraNorm = paragraphs[i].replace(/\s+/g, ' ').trim()
      running += ' ' + paraNorm

      // Check if we've accumulated enough text to contain the chunk start
      const chunkStart = chunkNorm.slice(0, 80)
      if (running.includes(chunkStart)) {
        // Found the start — now mark paragraphs until we cover the chunk
        for (let j = Math.max(0, i - 3); j <= Math.min(paragraphs.length - 1, i + 3); j++) {
          const pn = paragraphs[j].replace(/\s+/g, ' ').trim()
          if (pn.length > 10 && chunkNorm.includes(pn.slice(0, 80))) {
            matched.add(j)
          }
        }
        break
      }
    }
  }

  return matched
}

/* ─── paragraph renderer ──────────────────────────────────────────────────── */

function renderParagraph(text: string, highlighted: boolean): ReactNode {
  const t = text.trim()
  const isHeading = HEADING_RE.test(t)
  const isBulletTop = BULLET_RE.test(t)
  const isSubBullet = SUBBULLET_RE.test(t)

  if (isHeading) {
    return (
      <h3 className={cn(
        'text-[13px] font-bold leading-snug',
        highlighted ? 'text-blue-200' : 'text-foreground',
      )}>
        {t}
      </h3>
    )
  }

  if (isSubBullet) {
    const content = t.replace(SUBBULLET_RE, '').trim()
    return (
      <div className="ml-7 flex gap-2">
        <span className="mt-[7px] h-1 w-1 shrink-0 rounded-full border border-muted-foreground/50" />
        <span>{content}</span>
      </div>
    )
  }

  if (isBulletTop) {
    const content = t.replace(BULLET_RE, '').trim()
    return (
      <div className="ml-3 flex gap-2">
        <span className="mt-[7px] h-1.5 w-1.5 shrink-0 rounded-full bg-muted-foreground/50" />
        <span>{content}</span>
      </div>
    )
  }

  return <p>{t}</p>
}

/* ─── component ───────────────────────────────────────────────────────────── */

type Props = {
  open: boolean
  onOpenChange: (open: boolean) => void
  source: ChatSource | null
}

export function CitationSheet({ open, onOpenChange, source }: Props) {
  const docId    = typeof source?.metadata?.doc_id   === 'string' ? source.metadata.doc_id   : null
  const filename = typeof source?.metadata?.filename === 'string' ? source.metadata.filename : null
  const targetPage = source ? pageFromContent(source.content) : 1

  /** All PDF pages referenced inside this chunk (chunks can span multiple pages). */
  const chunkPageSet = useMemo(
    () => source ? allPagesFromContent(source.content) : new Set<number>([1]),
    [source],
  )

  const [pages,     setPages]     = useState<DocPage[]>([])
  const [loading,   setLoading]   = useState(false)
  const [loadedDoc, setLoadedDoc] = useState<string | null>(null)

  const scrollContainerRef = useRef<HTMLDivElement>(null)
  const highlightRef = useRef<HTMLDivElement>(null)

  /* Reset scroll position every time the panel opens or source changes */
  useEffect(() => {
    if (open && scrollContainerRef.current) {
      scrollContainerRef.current.scrollTop = 0
    }
  }, [open, source])

  /* Fetch raw pages (cached per doc_id) */
  useEffect(() => {
    if (!open || !docId) return
    if (docId === loadedDoc) return
    let cancelled = false
    setLoading(true)
    fetchDocumentPages(docId).then((p) => {
      if (cancelled) return
      setPages(p)
      setLoadedDoc(docId)
      setLoading(false)
    })
    return () => { cancelled = true }
  }, [open, docId, loadedDoc])

  /**
   * Only process the pages this chunk spans.  Previously ALL pages were
   * processed and rendered, which was slow and showed irrelevant content.
   */
  const processedPages = useMemo(() => {
    return pages
      .filter((pg) => chunkPageSet.has(pg.page))
      .map((pg) => {
        const paragraphs = cleanPageText(pg.content)
        const cited = source
          ? findCitedParagraphs(paragraphs, source.content)
          : new Set<number>()
        return { page: pg.page, paragraphs, cited }
      })
  }, [pages, source, chunkPageSet])

  /**
   * If text-matching found no highlighted paragraphs on any chunk page, fall
   * back to checking one page either side so we never show a blank highlight.
   */
  const pagesWithCitations = useMemo(() => {
    const hasAny = processedPages.some((p) => p.cited.size > 0)
    if (hasAny || !source) return processedPages

    // Build an expanded set: all chunk pages ± 1
    const expanded = new Set<number>()
    chunkPageSet.forEach((p) => { expanded.add(p - 1); expanded.add(p); expanded.add(p + 1) })

    return pages
      .filter((pg) => expanded.has(pg.page))
      .map((pg) => {
        const paragraphs = cleanPageText(pg.content)
        const cited = findCitedParagraphs(paragraphs, source.content)
        return { page: pg.page, paragraphs, cited }
      })
  }, [processedPages, source, chunkPageSet, pages])

  /* Smooth-scroll to highlight — retry until the ref is mounted */
  useEffect(() => {
    if (!open) return
    let cancelled = false
    let attempts = 0
    const tryScroll = () => {
      if (cancelled) return
      if (highlightRef.current) {
        highlightRef.current.scrollIntoView({ behavior: 'smooth', block: 'center' })
        return
      }
      if (attempts < 15) {
        attempts++
        setTimeout(tryScroll, 100)
      }
    }
    const timer = setTimeout(tryScroll, 150)
    return () => { cancelled = true; clearTimeout(timer) }
  }, [open, source, pagesWithCitations])

  let firstHighlightDone = false

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="flex w-full max-w-lg flex-col gap-0 p-0">

        {/* ── Header ── */}
        <SheetHeader className="shrink-0 border-b border-border bg-muted/20 px-5 py-4">
          <div className="flex items-start gap-3 pr-8">
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-blue-500/10 text-blue-400">
              <BookOpen className="h-4 w-4" strokeWidth={1.75} aria-hidden />
            </div>
            <div className="min-w-0">
              <SheetTitle className="text-sm font-semibold leading-snug text-foreground">
                Source {source?.index ?? '—'}
                {source && (() => {
                  const sortedPages = [...allPagesFromContent(source.content)].sort((a, b) => a - b)
                  const label = sortedPages.length > 1
                    ? `pp.\u00a0${sortedPages[0]}–${sortedPages[sortedPages.length - 1]}`
                    : `p.\u00a0${sortedPages[0] ?? targetPage}`
                  return (
                    <span className="ml-2 rounded-md bg-blue-500/10 px-1.5 py-0.5 text-[11px] font-medium text-blue-400 ring-1 ring-blue-500/20">
                      {label}
                    </span>
                  )
                })()}
              </SheetTitle>
              {filename && (
                <p className="mt-0.5 flex items-center gap-1 truncate text-[11px] text-muted-foreground">
                  <FileText className="h-3 w-3 shrink-0" aria-hidden />
                  {filename}
                </p>
              )}
            </div>
          </div>
        </SheetHeader>

        {/* ── Document ── */}
        <div ref={scrollContainerRef} className="flex-1 overflow-y-auto">
          {loading ? (
            <div className="flex h-40 items-center justify-center text-sm text-muted-foreground">
              <span className="animate-pulse">Loading document…</span>
            </div>
          ) : pagesWithCitations.length === 0 ? (
            <div className="flex h-40 items-center justify-center text-sm text-muted-foreground">
              No source selected.
            </div>
          ) : (
            <div className="pb-10">
              {pagesWithCitations.map((pg) => (
                <div key={pg.page}>
                  {/* Sticky page header */}
                  <div className="sticky top-0 z-10 border-b border-border/50 bg-muted/60 px-5 py-1.5 backdrop-blur-sm">
                    <span className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">
                      Page {pg.page}
                    </span>
                  </div>

                  {/* Page content */}
                  <div className="space-y-2 px-5 py-3 text-[12.5px] leading-relaxed text-muted-foreground">
                    {pg.paragraphs.map((para, i) => {
                      const isCited = pg.cited.has(i)
                      const needsRef = isCited && !firstHighlightDone
                      if (needsRef) firstHighlightDone = true

                      return (
                        <div
                          key={i}
                          ref={needsRef ? highlightRef : undefined}
                          className={cn(
                            isCited && 'rounded-md bg-blue-500/10 border-l-2 border-blue-500 py-1.5 pl-3 pr-2 -ml-1',
                          )}
                        >
                          {renderParagraph(para, isCited)}
                        </div>
                      )
                    })}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </SheetContent>
    </Sheet>
  )
}
