import clsx from 'clsx'
import { Loader2, Upload } from 'lucide-react'
import { useRef, useState } from 'react'

type Props = {
  onUpload: (f: File) => void
  loading: boolean
}

export function FileUpload({ onUpload, loading }: Props) {
  const [drag, setDrag] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  return (
    <div
      role="button"
      tabIndex={loading ? -1 : 0}
      aria-label="Upload PDF document"
      aria-busy={loading}
      className={clsx(
        'group flex flex-col items-center justify-center rounded-2xl border-2 border-dashed px-6 py-12 transition-all duration-200',
        loading ? 'pointer-events-none cursor-wait opacity-90' : 'cursor-pointer',
        drag
          ? 'border-foreground/25 bg-muted/50 shadow-card'
          : 'border-border bg-card/90 shadow-card hover:border-foreground/15 hover:bg-muted/40',
      )}
      onDragOver={(e) => {
        e.preventDefault()
        setDrag(true)
      }}
      onDragLeave={() => setDrag(false)}
      onDrop={(e) => {
        e.preventDefault()
        setDrag(false)
        const f = e.dataTransfer.files[0]
        if (f?.type === 'application/pdf') onUpload(f)
      }}
      onClick={() => inputRef.current?.click()}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          inputRef.current?.click()
        }
      }}
    >
      <input
        ref={inputRef}
        type="file"
        accept=".pdf,application/pdf"
        className="hidden"
        onChange={(e) => {
          const f = e.target.files?.[0]
          if (f) onUpload(f)
          e.target.value = ''
        }}
      />
      {loading ? (
        <div className="flex flex-col items-center gap-3">
          <Loader2 className="h-9 w-9 shrink-0 animate-spin text-foreground/45" aria-hidden />
          <p className="text-sm font-medium text-foreground">Indexing PDF…</p>
        </div>
      ) : (
        <>
          <div className="flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl bg-muted text-muted-foreground transition-colors group-hover:bg-accent group-hover:text-foreground">
            <Upload className="h-7 w-7" strokeWidth={1.65} aria-hidden />
          </div>
          <div className="text-center">
            <p className="text-sm font-semibold text-foreground">Drop a PDF or click to browse</p>
            <p className="mt-1.5 text-xs text-muted-foreground">OSFI E‑23, policies, model risk — one file at a time</p>
          </div>
        </>
      )}
    </div>
  )
}
