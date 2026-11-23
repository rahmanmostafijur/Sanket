import { cn } from '@/lib/cn'

const PALETTE = ['#8aa8ff', '#b8f36b', '#a98bff', '#5eead4', '#f5c451', '#fb923c', '#f0abfc', '#93c5fd']

function hash(text: string): number {
  let value = 0
  for (const char of text) value = (value * 31 + char.charCodeAt(0)) >>> 0
  return value
}

function initials(company: string): string {
  const words = company.replace(/[^\p{L}\p{N} ]/gu, ' ').split(/\s+/).filter(Boolean)
  const letters = words.length > 1 ? `${words[0]?.[0] ?? ''}${words[1]?.[0] ?? ''}` : (words[0]?.slice(0, 2) ?? '?')
  return letters.toUpperCase()
}

const SIZES = { sm: 'size-10 rounded-[10px] text-[13px]', md: 'size-12 rounded-xl text-[15px]', lg: 'size-16 rounded-2xl text-xl' } as const

/**
 * Monogram tile for a company. The API carries no logos, so each company gets a stable colour
 * from its name instead of a made-up logo.
 */
export function CompanyAvatar({ company, size = 'md', className }: { company: string; size?: keyof typeof SIZES; className?: string }) {
  const color = PALETTE[hash(company) % PALETTE.length] ?? PALETTE[0]
  return (
    <div
      aria-hidden
      className={cn('grid shrink-0 place-items-center font-semibold tracking-tight', SIZES[size], className)}
      style={{
        color,
        background: `linear-gradient(145deg, color-mix(in srgb, ${color} 20%, #0f1722), color-mix(in srgb, ${color} 7%, #0f1722))`,
        boxShadow: `inset 0 0 0 1px color-mix(in srgb, ${color} 26%, transparent)`,
      }}
    >
      {initials(company)}
    </div>
  )
}
