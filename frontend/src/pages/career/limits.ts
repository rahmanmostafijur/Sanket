/** Text limits of the career profile, mirroring the API. The first number of a section's `rows` is its row cap. */
export const PERSONAL_LIMITS = { full_name: 100, headline: 120, summary: 1000, city: 100, url: 300 } as const

export const TEXT_LIMITS = {
  education: { institution: 150, degree: 100, field: 100, grade: 50 },
  experience: { company: 150, title: 150, description: 2000 },
  skills: { name: 60 },
  languages: { name: 60 },
  certifications: { title: 150, issuer: 100, url: 300 },
  projects: { title: 150, description: 1000, url: 300 },
} as const

export const MAX_ROWS = { education: 10, experience: 30, skills: 60, languages: 15, certifications: 30, projects: 30 } as const

export const MIN_CERTIFICATION_YEAR = 1950
