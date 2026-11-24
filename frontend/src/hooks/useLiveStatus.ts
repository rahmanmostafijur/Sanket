import { useActiveProfile } from '@/hooks/data'
import { useLiveFeed } from '@/stores/liveFeed'

export interface LiveStatusView {
  label: string
  tone: 'accent' | 'amber' | 'danger' | 'muted'
  pulse: boolean
  description: string
}

/** Failed attempts in a row before the UI says "Reconnecting". */
const RECONNECT_NOTICE_ATTEMPT = 2

const LIVE: LiveStatusView = { label: 'Live', tone: 'accent', pulse: true, description: 'Connected to the live match feed.' }
const CONNECTING: LiveStatusView = { label: 'Connecting', tone: 'amber', pulse: false, description: 'Opening the live match feed…' }

/** One honest wording of the feed state, shared by every place that shows it. */
export function useLiveStatus(): LiveStatusView {
  const stream = useLiveFeed((s) => s.stream)
  const simulated = useLiveFeed((s) => s.simulated)
  const { profile, isLoading, error } = useActiveProfile()
  if (!profile && error && !simulated) {
    return { label: 'Disconnected', tone: 'danger', pulse: false, description: 'The Sanket API is not answering, so the live feed cannot start.' }
  }
  if (!profile) {
    return isLoading
      ? { label: 'Connecting', tone: 'amber', pulse: false, description: 'Loading your profile.' }
      : { label: 'No profile', tone: 'muted', pulse: false, description: 'Create a profile to receive live matches.' }
  }
  if (simulated) return { label: 'Demo stream', tone: 'amber', pulse: true, description: 'Simulated events from demo data. Not connected to the API.' }
  switch (stream.status) {
    case 'open':
      return LIVE
    case 'connecting':
      return CONNECTING
    case 'reconnecting':
      // The first retry runs about a second after a refused or dropped connection (for example a 429
      // on the stream token under load) and nearly always succeeds. Showing "Reconnecting" for it is
      // a flash, and wrong when the feed never opened, so keep the last state the user saw.
      if (stream.attempt < RECONNECT_NOTICE_ATTEMPT) return stream.connectedAt != null ? LIVE : CONNECTING
      return { label: 'Reconnecting', tone: 'amber', pulse: false, description: stream.error ?? 'The connection dropped. Reconnecting…' }
    case 'offline':
      return { label: 'Offline', tone: 'muted', pulse: false, description: 'You are offline. The feed resumes when you reconnect.' }
    case 'failed':
      return { label: 'Disconnected', tone: 'danger', pulse: false, description: stream.error ?? 'The live feed is unavailable.' }
    default:
      return { label: 'Not connected', tone: 'muted', pulse: false, description: 'The live feed is not running.' }
  }
}
