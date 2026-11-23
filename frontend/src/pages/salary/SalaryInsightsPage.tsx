import { ArrowRight, ChartNoAxesColumn, Globe, Layers, TrendingUp } from 'lucide-react'
import { motion } from 'motion/react'
import { useNavigate } from 'react-router'
import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/primitives'

const PLANNED = [
  { icon: TrendingUp, title: 'Salary trends', text: 'How pay for a role moves over time, from the salaries postings state.' },
  { icon: Layers, title: 'Ranges by seniority', text: 'What junior to lead roles pay for the skills you have.' },
  { icon: Globe, title: 'Market comparison', text: 'Remote and on-site pay across countries, in their own currencies.' },
]

/** Placeholder until salary analytics exist in the API. Everything here is illustrative. */
export default function SalaryInsightsPage() {
  const navigate = useNavigate()
  return (
    <div className="mx-auto max-w-[1080px] pt-4">
      <Card className="relative overflow-hidden px-6 py-14 text-center sm:px-12">
        <div aria-hidden className="pointer-events-none absolute left-1/2 top-0 h-[300px] w-[600px] -translate-x-1/2 bg-[radial-gradient(closest-side,rgb(184_243_107/0.12),transparent)]" />
        <svg aria-hidden viewBox="0 0 600 160" className="pointer-events-none absolute inset-x-0 bottom-0 h-40 w-full opacity-40" preserveAspectRatio="none">
          <motion.path
            d="M0 140 C 80 120, 120 130, 180 100 S 280 90, 330 70 S 430 60, 480 40 S 560 20, 600 10"
            fill="none"
            stroke="var(--color-accent)"
            strokeWidth="1.5"
            initial={{ pathLength: 0 }}
            animate={{ pathLength: 1 }}
            transition={{ duration: 1.6, ease: 'easeOut' }}
          />
        </svg>
        <div className="relative">
          <span className="inline-flex h-7 items-center rounded-full border border-accent/30 bg-accent/10 px-3 text-[12px] font-semibold uppercase tracking-wider text-accent">Coming soon</span>
          <div className="mx-auto mt-6 grid size-16 place-items-center rounded-2xl border border-line-strong bg-elevated text-accent shadow-[var(--shadow-glow)]">
            <ChartNoAxesColumn className="size-7" />
          </div>
          <h1 className="mt-6 text-[30px] font-semibold tracking-[-0.03em] text-fg sm:text-[38px]">Salary Insights is on the way</h1>
          <p className="mx-auto mt-3 max-w-xl text-[15.5px] leading-relaxed text-muted">
            Market salary intelligence built from the jobs Sanket indexes. Until it is ready, you can filter jobs by stated salary in Discover.
          </p>
          <Button variant="primary" size="lg" className="mt-8" onClick={() => navigate('/discover?min_salary=4000')}>
            Filter jobs by salary <ArrowRight />
          </Button>
        </div>
      </Card>
      <div className="mt-6 grid gap-4 md:grid-cols-3">
        {PLANNED.map(({ icon: Icon, title, text }, index) => (
          <motion.div key={title} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 + index * 0.08 }}>
            <Card className="h-full p-5">
              <Icon className="size-5 text-info" />
              <h2 className="mt-4 text-[15px] font-semibold text-fg">{title}</h2>
              <p className="mt-1.5 text-[13.5px] leading-relaxed text-muted">{text}</p>
              <p className="mt-4 text-[11.5px] font-medium uppercase tracking-wider text-subtle">Planned</p>
            </Card>
          </motion.div>
        ))}
      </div>
    </div>
  )
}
