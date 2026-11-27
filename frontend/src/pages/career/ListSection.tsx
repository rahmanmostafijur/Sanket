import { Inbox, Plus, Trash } from 'lucide-react'
import { useEffect, useId, useRef, useState, type ReactNode } from 'react'
import { errorMessage } from '@/api/client'
import type { CareerListInputs, CareerListKey } from '@/api/types'
import { Button } from '@/components/ui/Button'
import { EmptyState } from '@/components/ui/States'
import { useSaveCareerList } from '@/hooks/career'
import { cn } from '@/lib/cn'
import { toast } from '@/stores/toasts'
import { useCvDraft } from './cvDraft'
import { mergeList } from './cvMerge'
import type { DraftOf, SectionModel } from './drafts'
import { errorsFromServer, errorSummary, firstInvalid, type FieldErrors } from './fieldErrors'
import { focusField } from './focusField'
import { CvBanner, SectionCard } from './SectionCard'

/** What a row editor gets: the row, its errors (keyed by field name) and a way to change some of its fields. */
export interface RowEditorProps<K extends CareerListKey> {
  row: DraftOf[K]
  index: number
  /** Errors of this row only, by field name. */
  errors: FieldErrors
  /** An id prefix that is unique to this row, for `htmlFor`. */
  idBase: string
  onChange: (patch: Partial<DraftOf[K]>) => void
}

interface ListSectionProps<K extends CareerListKey> {
  model: SectionModel<K>
  title: string
  description?: string
  /** What one row is called: "education entry" gives "Add education entry". */
  noun: string
  items: readonly (CareerListInputs[K] & { id: number })[]
  empty: { title: string; description: string }
  ReadItem: (props: { item: CareerListInputs[K] }) => ReactNode
  EditRow: (props: RowEditorProps<K>) => ReactNode
  /** The part of a row that names it in the row's header, such as the company. */
  rowName?: (row: DraftOf[K]) => string
}

interface KeyedRow<K extends CareerListKey> {
  id: number
  draft: DraftOf[K]
}

/** Row ids only have to differ from each other, so one counter serves every section. */
let nextRowId = 0

function rowErrors(errors: FieldErrors, index: number): FieldErrors {
  const prefix = `${index}.`
  return Object.fromEntries(Object.entries(errors).filter(([key]) => key.startsWith(prefix)).map(([key, message]) => [key.slice(prefix.length), message]))
}

/**
 * One list section of the career profile: a read view, and an editor with a row per entry that is
 * saved as a whole. A CV's rows are appended for review and kept out of the saved list until Save.
 */
export function ListSection<K extends CareerListKey>({ model, title, description, noun, items, empty, ReadItem, EditRow, rowName }: ListSectionProps<K>) {
  const { proposal, clear } = useCvDraft()
  const save = useSaveCareerList(model.key)
  const formRef = useRef<HTMLFormElement>(null)
  const idBase = useId()
  const keyRows = (drafts: readonly DraftOf[K][]): KeyedRow<K>[] => drafts.map((draft) => ({ id: nextRowId++, draft }))

  const [merged] = useState(() => {
    const current = items.map((item) => model.toDraft(item))
    const merge = proposal ? mergeList(model, current, proposal[model.key] as CareerListInputs[K][]) : null
    return merge && merge.added > 0 ? { ...merge, kept: current.length } : null
  })
  const [rows, setRows] = useState<KeyedRow<K>[]>(() => keyRows(merged ? merged.rows : items.map((item) => model.toDraft(item))))
  const [editing, setEditing] = useState(merged !== null)
  // The rows that came from the CV, until the user edits them.
  const [filled, setFilled] = useState<ReadonlySet<number>>(() => new Set(merged ? rows.slice(merged.kept).map((row) => row.id) : []))
  const [bannerCount, setBannerCount] = useState<number | null>(merged?.added ?? null)
  const [errors, setErrors] = useState<FieldErrors>({})
  const [problem, setProblem] = useState<string | null>(null)
  const focusLast = useRef(false)

  // A row that was just added gets the focus, so it can be typed into at once.
  useEffect(() => {
    if (!focusLast.current) return
    focusLast.current = false
    const last = formRef.current?.querySelectorAll<HTMLElement>('[data-row]')
    last?.item(last.length - 1)?.querySelector<HTMLElement>('input, select, textarea')?.focus()
  }, [rows.length])

  const reset = (drafts: readonly DraftOf[K][]) => {
    setRows(keyRows(drafts))
    setFilled(new Set())
    setBannerCount(null)
    setErrors({})
    setProblem(null)
  }
  const close = () => {
    clear(model.key)
    setEditing(false)
  }
  const edit = () => {
    reset(items.map((item) => model.toDraft(item)))
    setEditing(true)
  }
  const cancel = () => {
    reset(items.map((item) => model.toDraft(item)))
    close()
  }
  const change = (rowId: number, index: number, patch: Partial<DraftOf[K]>) => {
    setRows((current) => current.map((row) => (row.id === rowId ? { ...row, draft: { ...row.draft, ...patch } } : row)))
    setErrors((current) => {
      const next = { ...current }
      for (const field of Object.keys(patch)) delete next[`${index}.${field}`]
      return Object.keys(next).length === Object.keys(current).length ? current : next
    })
    setFilled((current) => {
      if (!current.has(rowId)) return current
      const next = new Set(current)
      next.delete(rowId)
      return next
    })
  }
  const add = () => {
    focusLast.current = true
    setRows((current) => [...current, ...keyRows([model.blank()])])
  }
  const remove = (rowId: number) => {
    setRows((current) => current.filter((row) => row.id !== rowId))
    // The rows after it moved up, so errors by position no longer match; Save finds them again.
    setErrors({})
    setProblem(null)
  }
  const showErrors = (found: FieldErrors, fallback: string) => {
    setErrors(found)
    const first = firstInvalid(found, model.fields)
    setProblem(first ? null : fallback)
    focusField(formRef.current, first)
  }
  const submit = () => {
    const drafts = rows.map((row) => row.draft)
    const invalid = model.validate(drafts)
    if (firstInvalid(invalid, model.fields)) {
      showErrors(invalid, '')
      return
    }
    setErrors({})
    setProblem(null)
    save.mutate(drafts.map((draft) => model.toInput(draft)), {
      onSuccess: () => {
        close()
        toast({ tone: 'success', title: `${title} saved` })
      },
      onError: (failure) => showErrors(errorsFromServer(failure, model.fields, true), errorMessage(failure)),
    })
  }

  const full = rows.length >= model.maxRows
  return (
    <SectionCard
      title={title}
      description={description}
      editing={editing}
      onEdit={edit}
      onCancel={cancel}
      onSubmit={submit}
      saving={save.isPending}
      formRef={formRef}
      message={errorSummary(errors, model.fields) ?? problem}
      banner={bannerCount !== null ? <CvBanner count={bannerCount} unit="row" onDismiss={() => setBannerCount(null)} /> : null}
      read={
        items.length ? (
          <ul className="divide-y divide-line">
            {items.map((item) => <li key={item.id} className="py-3.5 first:pt-0 last:pb-0"><ReadItem item={item} /></li>)}
          </ul>
        ) : (
          <EmptyState className="py-8" icon={<Inbox />} title={empty.title} description={empty.description} />
        )
      }
      editor={
        <>
          {rows.length === 0 ? <p className="text-[13.5px] text-muted">Nothing here yet. Add a row, or press Save to keep this section empty.</p> : null}
          {rows.map((row, index) => {
            const name = rowName?.(row.draft).trim()
            return (
              <div key={row.id} data-row className={cn('space-y-4 rounded-xl border border-line-strong bg-bg/30 p-4', filled.has(row.id) && 'border-accent/45')}>
                <div className="flex items-center justify-between gap-3">
                  <p className="flex min-w-0 items-center gap-2 text-[13.5px] font-medium text-fg-2">
                    <span className="truncate">{name ? `${index + 1}. ${name}` : `${noun[0]?.toUpperCase()}${noun.slice(1)} ${index + 1}`}</span>
                    {filled.has(row.id) ? <span className="shrink-0 text-[11px] font-medium text-accent">Filled from CV</span> : null}
                  </p>
                  <Button variant="ghost" size="sm" aria-label={`Remove ${noun} ${index + 1}`} onClick={() => remove(row.id)}><Trash /> Remove</Button>
                </div>
                <EditRow row={row.draft} index={index} errors={rowErrors(errors, index)} idBase={`${idBase}-${row.id}`} onChange={(patch) => change(row.id, index, patch)} />
              </div>
            )
          })}
          <div className="flex flex-wrap items-center gap-3">
            <Button variant="outline" size="sm" disabled={full} onClick={add}><Plus /> Add {noun}</Button>
            {full ? <span className="text-[12.5px] text-subtle">Up to {model.maxRows} rows.</span> : null}
          </div>
        </>
      }
    />
  )
}
