import { FileUp, LoaderCircle, Upload } from 'lucide-react'
import { useRef, useState, type DragEvent } from 'react'
import { Button } from '@/components/ui/Button'
import { cn } from '@/lib/cn'
import { CV_ACCEPT, CV_PRIVACY_NOTE } from './cvFile'
import type { CvImport as CvImportState } from './useCvImport'

/**
 * The one way to import a CV: a compact strip with a single button and a single file input, and the
 * same strip takes a dropped file.
 */
export function CvImport({ cv }: { cv: CvImportState }) {
  const input = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)
  const onDrop = (event: DragEvent) => {
    event.preventDefault()
    setDragging(false)
    const file = event.dataTransfer.files[0]
    if (file && !cv.pending) cv.importFile(file)
  }
  return (
    <div className="space-y-3">
      <div
        onDragOver={(event) => {
          event.preventDefault()
          if (!cv.pending) setDragging(true)
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        className={cn(
          'rounded-xl border border-dashed px-4 py-3 transition-colors',
          dragging ? 'border-accent/60 bg-accent/[0.06]' : 'border-line-strong bg-surface/40',
        )}
      >
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="flex min-w-0 items-center gap-2.5 text-[13.5px] text-muted">
            <FileUp className="size-4 shrink-0" />
            <span>Have a CV? Drop a PDF or DOCX here (up to 5 MB) to fill in your profile.</span>
          </p>
          <Button variant="outline" size="sm" disabled={cv.pending} onClick={() => input.current?.click()}>
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
        </div>
        <p className="mt-2 text-[12.5px] leading-relaxed text-subtle">{CV_PRIVACY_NOTE}</p>
        {cv.pending ? (
          <p role="status" className="mt-2 inline-flex items-center gap-2 text-[13px] font-medium text-fg-2">
            <LoaderCircle className="size-4 animate-spin" /> Reading your CV...
          </p>
        ) : null}
      </div>
      {cv.error ? <p role="alert" className="text-[13px] text-danger">{cv.error}</p> : null}
    </div>
  )
}
