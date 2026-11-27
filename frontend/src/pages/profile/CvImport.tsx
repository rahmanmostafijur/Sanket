import { FileUp, LoaderCircle, Upload, X } from 'lucide-react'
import { useRef, useState, type DragEvent } from 'react'
import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/primitives'
import type { CvImport } from './useCvImport'
import { cn } from '@/lib/cn'
import { CV_ACCEPT, CV_PRIVACY_NOTE } from './cvProposal'

/** The "Import from CV" button with its hidden file picker. */
export function CvImportButton({ cv }: { cv: CvImport }) {
  const input = useRef<HTMLInputElement>(null)
  return (
    <>
      <Button variant="outline" disabled={cv.pending} onClick={() => input.current?.click()}>
        {cv.pending ? <LoaderCircle className="animate-spin" /> : <Upload />} Import from CV
      </Button>
      <input
        ref={input}
        type="file"
        hidden
        accept={CV_ACCEPT}
        data-testid="cv-file-input"
        onChange={(event) => {
          const file = event.target.files?.[0]
          // Clearing the value lets the same file be chosen again after a failure.
          event.target.value = ''
          if (file) cv.importFile(file)
        }}
      />
    </>
  )
}

interface CvImportCardProps {
  cv: CvImport
  /** How many fields the last import filled, or null when there is nothing to report. */
  filledCount: number | null
  onDismiss: () => void
}

export function CvImportCard({ cv, filledCount, onDismiss }: CvImportCardProps) {
  const [dragging, setDragging] = useState(false)
  const onDrop = (event: DragEvent) => {
    event.preventDefault()
    setDragging(false)
    const file = event.dataTransfer.files[0]
    if (file && !cv.pending) cv.importFile(file)
  }
  return (
    <Card className="p-5 sm:p-6">
      <div
        onDragOver={(event) => {
          event.preventDefault()
          if (!cv.pending) setDragging(true)
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        className={cn(
          'flex flex-col items-center gap-3 rounded-xl border border-dashed px-4 py-5 text-center transition-colors',
          dragging ? 'border-accent/60 bg-accent/[0.06]' : 'border-line-strong',
        )}
      >
        <FileUp className="size-6 text-muted" />
        <div>
          <h2 className="text-[15px] font-semibold text-fg">Import from CV</h2>
          <p className="mt-1 text-[13px] text-muted">Drop a PDF or DOCX here (up to 5 MB) to fill in this form for you.</p>
        </div>
        {cv.pending ? (
          <p role="status" className="inline-flex items-center gap-2 text-[13.5px] font-medium text-fg-2">
            <LoaderCircle className="size-4 animate-spin" /> Reading your CV...
          </p>
        ) : (
          <CvImportButton cv={cv} />
        )}
      </div>
      <p className="mt-3 text-[12.5px] leading-relaxed text-subtle">{CV_PRIVACY_NOTE}</p>
      {cv.error ? <p role="alert" className="mt-3 text-[13px] text-danger">{cv.error}</p> : null}
      {filledCount !== null ? (
        <div className="mt-3 flex items-start justify-between gap-3 rounded-xl border border-accent/30 bg-accent/[0.07] px-4 py-3 text-[13.5px] text-fg-2">
          <p>
            Imported from your CV: {filledCount} {filledCount === 1 ? 'field' : 'fields'} filled. Review them, then press Save. Nothing is saved yet.
          </p>
          <Button variant="ghost" size="sm" onClick={onDismiss}><X /> Dismiss</Button>
        </div>
      ) : null}
    </Card>
  )
}
