import { CheckCircle2, FileText } from 'lucide-react'

type Props = {
  filename: string
}

export function ActiveDocumentBanner({ filename }: Props) {
  return (
    <div className="flex flex-wrap items-center gap-4 rounded-2xl border border-border bg-card/95 p-4 shadow-card backdrop-blur-sm">
      <div className="flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl bg-muted/80 text-foreground/55">
        <FileText className="h-7 w-7" strokeWidth={1.6} aria-hidden />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <p className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">Active document</p>
          <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/15 px-2 py-0.5 text-[10px] font-semibold text-emerald-200">
            <CheckCircle2 className="h-3 w-3" aria-hidden />
            Ready
          </span>
        </div>
        <p className="mt-1 truncate text-base font-semibold text-foreground" title={filename}>
          {filename}
        </p>
        <p className="mt-0.5 text-xs text-muted-foreground">Switch files from the library or with a new upload when you need a different PDF.</p>
      </div>
    </div>
  )
}
