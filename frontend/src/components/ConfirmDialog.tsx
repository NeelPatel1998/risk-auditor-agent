import { AlertTriangle, Info } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'

export type ConfirmDialogProps = {
  open: boolean
  title: string
  description: string
  confirmLabel?: string
  cancelLabel?: string
  variant?: 'danger' | 'info'
  showCancel?: boolean
  onConfirm: () => void
  onCancel: () => void
}

export function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel = 'Confirm',
  cancelLabel = 'Cancel',
  variant = 'danger',
  showCancel = true,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const isDanger = variant === 'danger'

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) onCancel() }}>
      <DialogContent className="w-full max-w-sm border border-white/[0.08] bg-[#111318] p-0 shadow-2xl sm:rounded-2xl">
        <div className="px-6 pb-5 pt-6">
          <DialogHeader className="mb-5 gap-0">

            {/* Icon + Title row */}
            <div className="mb-3 flex items-center gap-3">
              <div className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-lg ${
                isDanger ? 'bg-red-500/10' : 'bg-blue-500/10'
              }`}>
                {isDanger
                  ? <AlertTriangle className={`h-4 w-4 ${isDanger ? 'text-red-400' : 'text-blue-400'}`} strokeWidth={2} />
                  : <Info className="h-4 w-4 text-blue-400" strokeWidth={2} />
                }
              </div>
              <DialogTitle className="text-sm font-semibold text-white/90">
                {title}
              </DialogTitle>
            </div>

            {/* Description */}
            <DialogDescription className="text-[13px] leading-relaxed text-white/50">
              {description}
            </DialogDescription>
          </DialogHeader>

          <DialogFooter className="flex flex-row items-center justify-end gap-2">
            {showCancel && (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="h-8 px-3 text-xs text-white/60 hover:bg-white/[0.06] hover:text-white/90 active:scale-95"
                onClick={onCancel}
              >
                {cancelLabel}
              </Button>
            )}
            <Button
              type="button"
              size="sm"
              className={`h-8 px-4 text-xs font-semibold text-white shadow-sm transition-all active:scale-95 ${
                isDanger
                  ? 'bg-red-600 hover:bg-red-500'
                  : 'bg-blue-600 hover:bg-blue-500'
              }`}
              onClick={onConfirm}
            >
              {confirmLabel}
            </Button>
          </DialogFooter>
        </div>
      </DialogContent>
    </Dialog>
  )
}
