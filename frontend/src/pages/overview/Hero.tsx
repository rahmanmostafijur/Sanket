import { Search, SlidersHorizontal, Sparkles } from 'lucide-react'
import { motion } from 'motion/react'
import { useState, type FormEvent } from 'react'
import { cn } from '@/lib/cn'

interface HeroHeadingProps {
  greeting: string
  name: string | null
}

export function HeroHeading({ greeting, name }: HeroHeadingProps) {
  return (
    <div className="relative">
      <HeroDecoration />
      <p className="text-[19px] text-fg-2 sm:text-[22px]">
        {greeting}
        {name ? `, ${name}` : ''} <span aria-hidden>👋</span>
      </p>
      <h1 className="mt-2 text-[34px] font-semibold leading-[1.08] tracking-[-0.035em] text-fg sm:text-[44px] xl:text-[46px]">
        Find <span className="text-accent">opportunities.</span> Not just jobs.
      </h1>
      <p className="mt-3 text-[15px] text-fg-2 sm:text-[17px]">Your personal job intelligence system.</p>
    </div>
  )
}

/** The arc and glowing point behind the heading. Purely decorative. */
function HeroDecoration() {
  return (
    <>
    <div aria-hidden className="pointer-events-none absolute -top-24 right-0 hidden size-[360px] bg-[radial-gradient(closest-side,rgb(184_243_107/0.13),rgb(184_243_107/0.04)_55%,transparent)] md:block" />
    <svg aria-hidden viewBox="0 0 520 220" className="pointer-events-none absolute -top-10 right-0 hidden h-[220px] w-[520px] md:block" fill="none">
      <defs>
        <radialGradient id="hero-glow" gradientUnits="userSpaceOnUse" cx="430" cy="70" r="170">
          <stop offset="0" stopColor="#b8f36b" stopOpacity="0.14" />
          <stop offset="0.6" stopColor="#b8f36b" stopOpacity="0.04" />
          <stop offset="1" stopColor="#b8f36b" stopOpacity="0" />
        </radialGradient>
        <linearGradient id="hero-arc" x1="0" x2="1" y1="1" y2="0">
          <stop offset="0" stopColor="#b8f36b" stopOpacity="0" />
          <stop offset="0.7" stopColor="#b8f36b" stopOpacity="0.45" />
          <stop offset="1" stopColor="#b8f36b" stopOpacity="0.9" />
        </linearGradient>
      </defs>
      <path d="M40 210 C 180 190, 330 140, 430 60" stroke="url(#hero-arc)" strokeWidth="1.4" />
      <path d="M120 220 C 250 200, 380 150, 470 40" stroke="#b8f36b" strokeOpacity="0.12" strokeWidth="1" />
      <motion.circle
        cx="430"
        cy="60"
        r="6"
        fill="#c9ff7f"
        initial={{ opacity: 0.6 }}
        animate={{ opacity: [0.6, 1, 0.6] }}
        transition={{ duration: 3, repeat: Infinity, ease: 'easeInOut' }}
        style={{ filter: 'drop-shadow(0 0 10px #b8f36b) drop-shadow(0 0 22px #b8f36b)' }}
      />
    </svg>
    </>
  )
}

interface HeroSearchProps {
  onSearch: (query: string) => void
  onToggleFilters?: () => void
  filtersActive?: boolean
}

export function HeroSearch({ onSearch, onToggleFilters, filtersActive = false }: HeroSearchProps) {
  const [value, setValue] = useState('')
  const [focused, setFocused] = useState(false)
  const submit = (event: FormEvent) => {
    event.preventDefault()
    onSearch(value)
  }
  return (
    <form role="search" onSubmit={submit} className="relative">
      <motion.div
        animate={{ boxShadow: focused ? '0 0 0 4px rgb(184 243 107 / 0.08), 0 0 40px -12px rgb(184 243 107 / 0.35)' : '0 0 0 0 rgb(0 0 0 / 0)' }}
        className={cn(
          'flex h-[56px] items-center gap-3 rounded-full border bg-surface pl-5 pr-2 transition-colors',
          focused ? 'border-accent/45' : 'border-line-strong',
        )}
      >
        <Search className="size-[22px] shrink-0 text-accent" strokeWidth={2.2} />
        <input
          value={value}
          onChange={(event) => setValue(event.target.value)}
          onFocus={() => setFocused(true)}
          onBlur={() => setFocused(false)}
          placeholder="Try “remote Python backend” or describe your next role"
          aria-label="Search jobs with keywords or natural language"
          className="h-full min-w-0 flex-1 bg-transparent text-[16px] text-fg outline-none sm:text-[17px]"
        />
        <button
          type="submit"
          disabled={!value.trim()}
          className="inline-flex h-9 shrink-0 items-center gap-1.5 rounded-full bg-accent px-3.5 text-[13.5px] font-semibold text-accent-ink transition-[background,opacity] hover:bg-accent-strong disabled:opacity-60"
        >
          <span className="hidden sm:inline">AI Search</span>
          <Sparkles className="size-4" />
        </button>
        {onToggleFilters ? (
          <button
            type="button"
            onClick={onToggleFilters}
            aria-label="Show filters"
            aria-pressed={filtersActive}
            className={cn('grid size-10 shrink-0 place-items-center rounded-full transition-colors hover:bg-elevated', filtersActive ? 'text-accent' : 'text-fg-2')}
          >
            <SlidersHorizontal className="size-5" />
          </button>
        ) : null}
      </motion.div>
    </form>
  )
}
