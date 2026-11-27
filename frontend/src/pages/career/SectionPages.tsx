import { CertificationsSection, ProjectsSection } from './AccomplishmentSections'
import { CareerGate } from './CareerGate'
import { EducationSection } from './EducationSection'
import { ExperienceSection } from './ExperienceSection'
import { PersonalSection } from './PersonalSection'
import { LanguagesSection, SkillsSection } from './SkillsSections'

export function PersonalPage() {
  return <CareerGate>{(career) => <PersonalSection personal={career.personal} />}</CareerGate>
}

export function EducationPage() {
  return <CareerGate>{(career) => <EducationSection items={career.education} />}</CareerGate>
}

export function ExperiencePage() {
  return <CareerGate>{(career) => <ExperienceSection items={career.experience} />}</CareerGate>
}

export function SkillsPage() {
  return (
    <CareerGate>
      {(career) => (
        <div className="space-y-5">
          <SkillsSection items={career.skills} />
          <LanguagesSection items={career.languages} />
        </div>
      )}
    </CareerGate>
  )
}

export function AccomplishmentsPage() {
  return (
    <CareerGate>
      {(career) => (
        <div className="space-y-5">
          <CertificationsSection items={career.certifications} />
          <ProjectsSection items={career.projects} />
        </div>
      )}
    </CareerGate>
  )
}
