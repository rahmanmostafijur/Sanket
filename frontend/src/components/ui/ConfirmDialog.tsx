import type { ReactNode } from 'react'
import { Button } from '@/components/ui/Button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'

interface ConfirmDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  description: ReactNode
  cancelLabel: string
  confirmLabel: ReactNode
  onConfirm: () => void
  pending?: boolean
}

/** Confirmation for a destructive action. The content renders in a portal, outside any form. */
export function ConfirmDialog({ open, onOpenChange, title, description, cancelLabel, confirmLabel, onConfirm, pending = false }: ConfirmDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent showCloseButton={false} className="border border-line-strong ring-0 sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="text-[16px] font-semibold text-fg">{title}</DialogTitle>
          <DialogDescription className="text-[13.5px] leading-relaxed text-muted">{description}</DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>{cancelLabel}</Button>
          <Button variant="danger" onClick={onConfirm} disabled={pending}>{confirmLabel}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
