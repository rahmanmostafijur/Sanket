import type { EmploymentType, Job, Seniority, WorkMode } from '@/api/types'
import { sourceMeta } from '@/lib/sources'

/**
 * DEMO DATA. Fictional companies and listings, shown only in demo mode and always labelled as
 * such. Nothing here comes from the Sanket API, and no listing links anywhere.
 */

interface Spec {
  id: number
  title: string
  company: string
  source: string
  minutesAgo: number
  workMode: WorkMode
  seniority: Seniority
  type: EmploymentType
  skills: string[]
  salary?: [number, number, 'month' | 'year']
  location?: string
  years?: number
}

const LOADED_AT = Date.now()

function iso(minutesAgo: number): string {
  return new Date(LOADED_AT - minutesAgo * 60_000).toISOString()
}

function toJob(spec: Spec): Job {
  const meta = sourceMeta(spec.source)
  return {
    job_id: spec.id,
    title: spec.title,
    company: spec.company,
    location: spec.location ?? (spec.workMode === 'remote' ? 'Remote' : null),
    source: spec.source,
    source_name: meta?.name ?? spec.source,
    url: null,
    attribution: null,
    sources: [{ source: spec.source, name: meta?.name ?? spec.source }],
    published_at: iso(spec.minutesAgo),
    first_seen_at: iso(spec.minutesAgo),
    salary_text: null,
    extracted: {
      work_mode: spec.workMode,
      seniority: spec.seniority,
      employment_type: spec.type,
      country: null,
      city: null,
      skills: spec.skills,
      min_years_experience: spec.years ?? null,
      salary: spec.salary
        ? { min_amount: spec.salary[0], max_amount: spec.salary[1], currency: 'USD', period: spec.salary[2] }
        : null,
    },
  }
}

const SPECS: Spec[] = [
  { id: 9001, title: 'Senior Python Backend Engineer', company: 'Lumen Grid', source: 'remoteok', minutesAgo: 120, workMode: 'remote', seniority: 'senior', type: 'full_time', skills: ['Python', 'FastAPI', 'PostgreSQL', 'Docker', 'AWS'], salary: [4000, 6000, 'month'], years: 5 },
  { id: 9002, title: 'Backend Engineer', company: 'Northwind Labs', source: 'weworkremotely', minutesAgo: 180, workMode: 'remote', seniority: 'mid', type: 'full_time', skills: ['Python', 'Django', 'PostgreSQL', 'Redis'], salary: [3000, 5000, 'month'], years: 3 },
  { id: 9003, title: 'Python Developer', company: 'Peakline', source: 'himalayas', minutesAgo: 240, workMode: 'remote', seniority: 'mid', type: 'contract', skills: ['Python', 'FastAPI', 'Docker'], salary: [4000, 7000, 'month'] },
  { id: 9004, title: 'Platform Engineer (Python)', company: 'Orbital Health', source: 'greenhouse', minutesAgo: 320, workMode: 'hybrid', seniority: 'senior', type: 'full_time', skills: ['Python', 'Kubernetes', 'AWS', 'Terraform', 'PostgreSQL'], salary: [90000, 130000, 'year'], location: 'Berlin, Germany' },
  { id: 9005, title: 'Full Stack Developer', company: 'Brightpath', source: 'weworkremotely', minutesAgo: 360, workMode: 'remote', seniority: 'mid', type: 'full_time', skills: ['TypeScript', 'React', 'Python', 'PostgreSQL'], salary: [3500, 5500, 'month'] },
  { id: 9006, title: 'Data Engineer', company: 'Tidewater Analytics', source: 'remotive', minutesAgo: 420, workMode: 'remote', seniority: 'senior', type: 'full_time', skills: ['Python', 'Airflow', 'PostgreSQL', 'AWS', 'dbt'], salary: [5000, 7500, 'month'] },
  { id: 9007, title: 'API Engineer, Payments', company: 'Coinlane', source: 'lever', minutesAgo: 500, workMode: 'onsite', seniority: 'senior', type: 'full_time', skills: ['Go', 'PostgreSQL', 'Kafka', 'gRPC'], location: 'London, United Kingdom' },
  { id: 9008, title: 'Junior Backend Developer', company: 'Fernhill Studio', source: 'jobicy', minutesAgo: 600, workMode: 'remote', seniority: 'junior', type: 'full_time', skills: ['Python', 'Flask', 'SQL'], salary: [1800, 2600, 'month'] },
  { id: 9009, title: 'Machine Learning Engineer', company: 'Quanta Forge', source: 'greenhouse', minutesAgo: 720, workMode: 'hybrid', seniority: 'senior', type: 'full_time', skills: ['Python', 'PyTorch', 'FastAPI', 'Kubernetes'], salary: [8000, 11000, 'month'], location: 'Amsterdam, Netherlands' },
  { id: 9010, title: 'Site Reliability Engineer', company: 'Stackwise', source: 'remoteok', minutesAgo: 900, workMode: 'remote', seniority: 'mid', type: 'full_time', skills: ['Kubernetes', 'AWS', 'Terraform', 'Python', 'Prometheus'] },
  { id: 9011, title: 'Backend Engineer (Django)', company: 'Harbor & Co', source: 'himalayas', minutesAgo: 1100, workMode: 'remote', seniority: 'mid', type: 'part_time', skills: ['Python', 'Django', 'Celery', 'Redis'], salary: [2000, 3200, 'month'] },
  { id: 9012, title: 'Lead Software Engineer', company: 'Verdant Systems', source: 'lever', minutesAgo: 1400, workMode: 'hybrid', seniority: 'lead', type: 'full_time', skills: ['Python', 'FastAPI', 'PostgreSQL', 'AWS', 'Leadership'], salary: [140000, 175000, 'year'], location: 'Toronto, Canada' },
  { id: 9013, title: 'Frontend Engineer', company: 'Pixelmint', source: 'remotive', minutesAgo: 1700, workMode: 'remote', seniority: 'mid', type: 'full_time', skills: ['TypeScript', 'React', 'CSS'], salary: [4000, 6000, 'month'] },
  { id: 9014, title: 'DevOps Engineer', company: 'Cloudmere', source: 'jobicy', minutesAgo: 2100, workMode: 'onsite', seniority: 'mid', type: 'contract', skills: ['Docker', 'Kubernetes', 'AWS', 'Bash'], location: 'Dhaka, Bangladesh' },
  { id: 9015, title: 'Python Automation Engineer', company: 'Relay Works', source: 'weworkremotely', minutesAgo: 2600, workMode: 'remote', seniority: 'junior', type: 'internship', skills: ['Python', 'Selenium', 'Docker'] },
  { id: 9016, title: 'Senior Data Platform Engineer', company: 'Meridian Bio', source: 'greenhouse', minutesAgo: 3200, workMode: 'hybrid', seniority: 'senior', type: 'full_time', skills: ['Python', 'Spark', 'AWS', 'PostgreSQL', 'Docker'], salary: [110000, 150000, 'year'], location: 'Boston, United States' },
]

/** Listings that "arrive" while the demo stream runs. */
const INCOMING: Spec[] = [
  { id: 9101, title: 'Backend Engineer (Python)', company: 'Sundial Health', source: 'himalayas', minutesAgo: 0, workMode: 'remote', seniority: 'senior', type: 'full_time', skills: ['Python', 'FastAPI', 'PostgreSQL', 'AWS'], salary: [5000, 7000, 'month'] },
  { id: 9102, title: 'Senior API Engineer', company: 'Kestrel Pay', source: 'remoteok', minutesAgo: 0, workMode: 'remote', seniority: 'senior', type: 'full_time', skills: ['Python', 'FastAPI', 'Redis', 'Docker'] },
  { id: 9103, title: 'Python Platform Developer', company: 'Arcfield', source: 'lever', minutesAgo: 0, workMode: 'remote', seniority: 'mid', type: 'contract', skills: ['Python', 'PostgreSQL', 'Kubernetes'], salary: [4500, 6500, 'month'] },
  { id: 9104, title: 'Integrations Engineer', company: 'Copperleaf', source: 'remotive', minutesAgo: 0, workMode: 'remote', seniority: 'mid', type: 'full_time', skills: ['Python', 'REST', 'PostgreSQL', 'Docker'], salary: [3800, 5200, 'month'] },
]

export const DEMO_JOBS: readonly Job[] = SPECS.map(toJob)

/** A fresh incoming job for the simulated stream, timestamped now. */
export function demoIncomingJob(index: number): Job {
  const spec = INCOMING[index % INCOMING.length] as Spec
  const round = Math.floor(index / INCOMING.length)
  return { ...toJob(spec), job_id: spec.id + round * 1000, published_at: new Date().toISOString(), first_seen_at: new Date().toISOString() }
}
