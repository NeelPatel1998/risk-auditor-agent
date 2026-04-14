import { Loader2, Sparkles } from 'lucide-react'
import { useEffect, useState } from 'react'
import { fetchSuggestedQuestions } from '../lib/api'

type Props = {
  docId: string | null
  onPick: (question: string) => void
  disabled?: boolean
}

const POLL_MS = 2000
const MAX_POLL_ATTEMPTS = 45

export function SuggestedPrompts({ docId, onPick, disabled }: Props) {
  const [state, setState] = useState<{
    docId: string | null
    questions: string[]
    status: string
    pollExhausted: boolean
  }>({ docId: null, questions: [], status: 'none', pollExhausted: false })

  useEffect(() => {
    if (!docId) return

    let cancelled = false
    let attempt = 0
    let timeoutId: ReturnType<typeof window.setTimeout> | undefined

    const tick = async () => {
      let r: { questions: string[]; status: string }
      try {
        r = await fetchSuggestedQuestions(docId)
      } catch {
        r = { questions: [], status: 'none' }
      }
      if (cancelled) return
      attempt += 1
      setState({
        docId,
        questions: r.questions,
        status: r.status,
        pollExhausted: r.status === 'pending' && attempt >= MAX_POLL_ATTEMPTS,
      })
      if (r.status === 'pending' && attempt < MAX_POLL_ATTEMPTS) {
        timeoutId = window.setTimeout(tick, POLL_MS)
      }
    }

    void tick()
    return () => {
      cancelled = true
      window.clearTimeout(timeoutId)
    }
  }, [docId])

  if (!docId) return null

  const active = state.docId === docId
    ? state
    : { docId, questions: [], status: 'pending', pollExhausted: false }

  const loading = active.status === 'pending' && active.questions.length === 0 && !active.pollExhausted
  const pollExhaustedNoQ = active.pollExhausted && active.questions.length === 0
  const failed = active.status === 'failed' && active.questions.length === 0

  // Nothing meaningful to show yet — don't render at all.
  if (active.status === 'none' && active.questions.length === 0) return null

  return (
    <div className="space-y-2 border-t border-border bg-muted/35 px-3 py-3 sm:px-4">
      <div className="flex items-center gap-1.5 px-0.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-muted-foreground/70">
        <Sparkles className="h-3.5 w-3.5 shrink-0 stroke-[1.75]" aria-hidden />
        Try asking
      </div>

      {loading && (
        <div className="flex items-center gap-2 px-0.5 py-1 text-[11px] text-muted-foreground">
          <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin" aria-hidden />
          Generating suggestions…
        </div>
      )}

      {pollExhaustedNoQ && (
        <p className="px-0.5 text-[11px] leading-snug text-muted-foreground/80">
          Suggestions still processing — type your own question below.
        </p>
      )}

      {failed && (
        <p className="px-0.5 text-[11px] leading-snug text-muted-foreground/80">
          Suggestions unavailable — type your own question below.
        </p>
      )}

      {active.questions.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {active.questions.map((q, i) => (
            <button
              key={`${i}-${q.slice(0, 32)}`}
              type="button"
              disabled={disabled}
              onClick={() => onPick(q)}
              className="max-w-full rounded-lg border border-border bg-background px-2.5 py-1.5 text-left text-[11px] font-medium leading-snug text-foreground shadow-sm transition-all duration-150 hover:border-amber-500/45 hover:bg-amber-500/[0.07] active:scale-[0.97] active:brightness-90 disabled:pointer-events-none disabled:opacity-40 dark:hover:border-amber-500/35 dark:hover:bg-amber-950/35 sm:max-w-[calc(50%-0.2rem)] lg:max-w-[calc(33.333%-0.2rem)]"
              title={q}
            >
              <span className="line-clamp-2">{q}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
