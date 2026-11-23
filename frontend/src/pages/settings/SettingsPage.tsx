import { LayoutGrid, List, Trash } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { errorMessage } from '@/api/client'
import { Avatar } from '@/components/layout/Sidebar'
import { PageHeader } from '@/components/layout/PageHeader'
import { Button } from '@/components/ui/Button'
import { SwitchRow } from '@/components/ui/Field'
import { FilterMenu } from '@/components/ui/FilterMenu'
import { Card } from '@/components/ui/primitives'
import { Segmented } from '@/components/ui/Tabs'
import { useActiveProfile, useClearSaved, useSavedJobs } from '@/hooks/data'
import { describeIdentity } from '@/lib/identity'
import { usePreferences, type ResultsView } from '@/stores/preferences'
import { useSession, type DataMode } from '@/stores/session'
import { toast } from '@/stores/toasts'
import { DevelopersSection } from './DevelopersSection'

const LOCAL_KEYS = ['sanket.session', 'sanket.saved', 'sanket.prefs']
const SESSION_KEYS = ['sanket.token', 'sanket.jobs']

function Section({ title, description, children }: { title: string; description?: string; children: ReactNode }) {
  return (
    <Card className="p-5 sm:p-6">
      <h2 className="text-[16px] font-semibold text-fg">{title}</h2>
      {description ? <p className="mt-1 text-[13.5px] text-muted">{description}</p> : null}
      <div className="mt-3 divide-y divide-line">{children}</div>
    </Card>
  )
}

function Row({ label, description, children }: { label: string; description?: ReactNode; children: ReactNode }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-4 py-3.5">
      <div className="min-w-0">
        <p className="text-[14px] font-medium text-fg">{label}</p>
        {description ? <p className="mt-0.5 text-[13px] text-muted">{description}</p> : null}
      </div>
      {children}
    </div>
  )
}

function resetLocalData(): void {
  try {
    for (const key of LOCAL_KEYS) window.localStorage.removeItem(key)
    for (const key of SESSION_KEYS) window.sessionStorage.removeItem(key)
  } catch {
    // Storage blocked: nothing was stored to begin with.
  }
  window.location.assign('/')
}

export default function SettingsPage() {
  const { mode, setMode, token, clearToken, rememberToken, setActiveProfileId } = useSession()
  const prefs = usePreferences()
  const savedCount = useSavedJobs().entries.length
  const clearSaved = useClearSaved()
  const { profile, profiles } = useActiveProfile()
  const [confirmReset, setConfirmReset] = useState(false)
  const identity = describeIdentity(mode, token)

  return (
    <div className="mx-auto max-w-[900px]">
      <PageHeader title="Settings" description="Account, preferences, notifications, the data this browser keeps and developer access." />
      <div className="space-y-5">
        <Section title="Account">
          {identity.kind === 'none' ? null : (
            <div className="flex items-center gap-4 py-3.5">
              <Avatar initials={identity.initials} className="size-12" />
              <div className="min-w-0 flex-1">
                <p className="truncate text-[15px] font-semibold text-fg">{identity.name}</p>
                <p className="truncate text-[13px] text-muted">{identity.detail}</p>
              </div>
            </div>
          )}
          <Row label="Data source" description={mode === 'demo' ? 'Labelled sample data in this browser.' : 'Live data from your Sanket API.'}>
            <Segmented<DataMode>
              id="settings-mode"
              value={mode}
              onChange={setMode}
              items={[{ value: 'api', label: 'Sanket API' }, { value: 'demo', label: 'Demo data' }]}
            />
          </Row>
          {profiles.length > 0 ? (
            <Row label="Matching profile" description="Used for matches, the live feed and match scores.">
              <FilterMenu label="Matching profile" summary={profile?.name ?? 'Choose'} align="end" options={profiles.map((p) => ({ value: p.id, label: p.name }))} value={profile?.id ?? 0} onChange={(id) => setActiveProfileId(id)} />
            </Row>
          ) : null}
        </Section>

        <Section title="Preferences">
          <Row label="Default job view">
            <Segmented<ResultsView>
              id="settings-view"
              value={prefs.view}
              onChange={prefs.setView}
              items={[{ value: 'list', label: 'List', icon: <List /> }, { value: 'grid', label: 'Grid', icon: <LayoutGrid /> }]}
            />
          </Row>
          <SwitchRow checked={prefs.sidebarCollapsed} onCheckedChange={() => prefs.toggleSidebar()} label="Compact sidebar" description="Show only icons in the navigation on large screens." />
          <SwitchRow
            checked={prefs.motion === 'reduced'}
            onCheckedChange={(on) => prefs.setMotion(on ? 'reduced' : 'system')}
            label="Reduce motion"
            description="Turn off animations. When off, Sanket follows your system setting."
          />
        </Section>

        <Section title="Notifications">
          <SwitchRow checked={prefs.notifyOnMatch} onCheckedChange={prefs.setNotifyOnMatch} label="New match alerts" description="Show a notification when the live feed delivers a new match. Matches always appear in Live Matches and the bell." />
        </Section>

        <Section title="Security and privacy" description="What this browser stores. Nothing here is sent anywhere except the Sanket API.">
          <Row label="Credential" description={token ? (rememberToken ? 'Remembered on this device.' : 'Kept for this tab only.') : 'None stored.'}>
            <Button size="sm" variant="outline" disabled={!token} onClick={clearToken}>Forget</Button>
          </Row>
          <Row label="Recent searches" description={`${prefs.recentSearches.length} kept for suggestions.`}>
            <Button size="sm" variant="outline" disabled={!prefs.recentSearches.length} onClick={prefs.clearRecentSearches}>Clear</Button>
          </Row>
          <Row label="Saved jobs" description={mode === 'api' ? `${savedCount} saved with your Sanket account.` : `${savedCount} demo jobs saved in this browser.`}>
            <Button
              size="sm"
              variant="outline"
              disabled={!savedCount}
              onClick={() => clearSaved().then(() => toast({ title: 'Saved jobs cleared' }), (error: unknown) => toast({ tone: 'error', title: 'Could not clear every saved job', description: errorMessage(error) }))}
            >
              Clear
            </Button>
          </Row>
          <Row label="Reset this browser" description="Removes the credential, saved jobs, preferences and cached jobs, then reloads.">
            {confirmReset ? (
              <span className="flex gap-2">
                <Button size="sm" variant="ghost" onClick={() => setConfirmReset(false)}>Cancel</Button>
                <Button size="sm" variant="danger" onClick={resetLocalData}><Trash /> Reset everything</Button>
              </span>
            ) : (
              <Button size="sm" variant="danger" onClick={() => setConfirmReset(true)}>Reset</Button>
            )}
          </Row>
        </Section>

        <DevelopersSection />
      </div>
    </div>
  )
}
