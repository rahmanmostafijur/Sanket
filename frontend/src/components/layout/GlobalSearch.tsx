import { ArrowRight, Clock, Search, Sparkles } from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'
import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router'
import { Kbd } from '@/components/ui/primitives'
import { useActiveProfile } from '@/hooks/data'
import { cn } from '@/lib/cn'
import { usePreferences } from '@/stores/preferences'

/** Example phrasings to show that the search understands natural language. */
const EXAMPLES = ['remote Python backend roles', 'senior data engineer in Europe', 'contract React developer']

const isMac = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform)

interface Suggestion {
  kind: 'recent' | 'profile' | 'example'
  text: string
}

function useSearchNavigation(): (query: string) => void {
  const navigate = useNavigate()
  const addRecent = usePreferences((s) => s.addRecentSearch)
  return (query: string) => {
    const q = query.trim()
    if (!q) return
    addRecent(q)
    navigate(`/discover?q=${encodeURIComponent(q)}`)
  }
}

export function GlobalSearch({ className }: { className?: string }) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [value, setValue] = useState('')
  const [focused, setFocused] = useState(false)
  const [highlight, setHighlight] = useState(-1)
  const recent = usePreferences((s) => s.recentSearches)
  const { profile } = useActiveProfile()
  const go = useSearchNavigation()

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        inputRef.current?.focus()
        inputRef.current?.select()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const suggestions = useMemo<Suggestion[]>(() => {
    const needle = value.trim().toLowerCase()
    const pool: Suggestion[] = [
      ...recent.map((text) => ({ kind: 'recent' as const, text })),
      ...(profile?.desired_titles ?? []).map((text) => ({ kind: 'profile' as const, text })),
      ...EXAMPLES.map((text) => ({ kind: 'example' as const, text })),
    ]
    const seen = new Set<string>()
    return pool
      .filter((item) => (needle ? item.text.toLowerCase().includes(needle) : true))
      .filter((item) => !seen.has(item.text.toLowerCase()) && seen.add(item.text.toLowerCase()))
      .slice(0, 7)
  }, [value, recent, profile])

  const submit = (event?: FormEvent) => {
    event?.preventDefault()
    const chosen = highlight >= 0 ? suggestions[highlight]?.text : undefined
    go(chosen ?? value)
    setValue('')
    setHighlight(-1)
    inputRef.current?.blur()
  }

  const open = focused && suggestions.length > 0
  return (
    <form role="search" onSubmit={submit} className={cn('relative', className)}>
      <div
        className={cn(
          'flex h-12 items-center gap-3 rounded-2xl border bg-surface px-4 transition-[border-color,box-shadow] duration-200',
          focused ? 'border-accent/40 shadow-[0_0_0_4px_rgb(184_243_107/0.07)]' : 'border-line-strong hover:border-[#34445b]',
        )}
      >
        <Search className="size-5 shrink-0 text-muted" />
        <input
          ref={inputRef}
          value={value}
          onChange={(event) => {
            setValue(event.target.value)
            setHighlight(-1)
          }}
          onFocus={() => setFocused(true)}
          onBlur={() => setTimeout(() => setFocused(false), 120)}
          onKeyDown={(event) => {
            if (event.key === 'ArrowDown') setHighlight((h) => Math.min(suggestions.length - 1, h + 1))
            else if (event.key === 'ArrowUp') setHighlight((h) => Math.max(-1, h - 1))
            else if (event.key === 'Escape') inputRef.current?.blur()
            else return
            event.preventDefault()
          }}
          placeholder="Search jobs with keywords or natural language..."
          aria-label="Search jobs"
          aria-expanded={open}
          aria-autocomplete="list"
          role="combobox"
          className="h-full min-w-0 flex-1 bg-transparent text-[15px] text-fg outline-none"
        />
        <Kbd className="hidden sm:inline-flex">{isMac ? '⌘' : 'Ctrl'} K</Kbd>
      </div>
      <AnimatePresence>
        {open ? (
          <motion.ul
            role="listbox"
            initial={{ opacity: 0, y: -6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -6 }}
            transition={{ duration: 0.15 }}
            className="absolute inset-x-0 top-[calc(100%+8px)] z-40 overflow-hidden rounded-2xl border border-line-strong bg-[#111a26] p-1.5 shadow-[var(--shadow-pop)]"
          >
            {suggestions.map((item, index) => {
              const Icon = item.kind === 'recent' ? Clock : item.kind === 'profile' ? Sparkles : Search
              return (
                <li key={`${item.kind}-${item.text}`} role="option" aria-selected={index === highlight}>
                  <button
                    type="button"
                    onMouseDown={(event) => event.preventDefault()}
                    onMouseEnter={() => setHighlight(index)}
                    onClick={() => {
                      go(item.text)
                      setValue('')
                      inputRef.current?.blur()
                    }}
                    className={cn('flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left text-sm', index === highlight ? 'bg-elevated text-fg' : 'text-fg-2')}
                  >
                    <Icon className={cn('size-4 shrink-0', item.kind === 'profile' ? 'text-accent' : 'text-muted')} />
                    <span className="flex-1 truncate">{item.text}</span>
                    <span className="text-[11px] text-subtle">{item.kind === 'recent' ? 'Recent' : item.kind === 'profile' ? 'From your profile' : 'Try'}</span>
                    {index === highlight ? <ArrowRight className="size-3.5 text-muted" /> : null}
                  </button>
                </li>
              )
            })}
          </motion.ul>
        ) : null}
      </AnimatePresence>
    </form>
  )
}
