import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { Career, CareerListInputs, CareerListKey, CareerPersonal, Me } from '@/api/types'
import { useIsGuest } from '@/lib/auth'
import { useDataSource } from './data'

/** The career profile (`GET /career`). A 404 means the credential is not an account. */
export function useCareer() {
  const { source, key } = useDataSource()
  const guest = useIsGuest()
  return useQuery({
    queryKey: ['career', key],
    queryFn: ({ signal }) => source.getCareer(signal),
    enabled: !guest,
  })
}

/** Saves the personal part and updates the shared `me` data, so the sidebar shows the new name at once. */
export function useSaveCareerPersonal() {
  const { source, key } = useDataSource()
  const client = useQueryClient()
  return useMutation({
    mutationFn: (personal: CareerPersonal) => source.saveCareerPersonal(personal),
    onSuccess: (saved) => {
      client.setQueryData<Career>(['career', key], (career) => (career ? { ...career, personal: saved } : career))
      client.setQueryData<Me>(['me', key], (me) => (me ? { ...me, full_name: saved.full_name, headline: saved.headline } : me))
      void client.invalidateQueries({ queryKey: ['career', key] })
      void client.invalidateQueries({ queryKey: ['me', key] })
    },
  })
}

/** Replaces a whole list section. The completeness figure and years of experience are refetched. */
export function useSaveCareerList<K extends CareerListKey>(section: K) {
  const { source, key } = useDataSource()
  const client = useQueryClient()
  return useMutation({
    mutationFn: (items: CareerListInputs[K][]) => source.replaceCareerList(section, items),
    onSuccess: (saved) => {
      client.setQueryData<Career>(['career', key], (career) => (career ? { ...career, [section]: saved } : career))
      void client.invalidateQueries({ queryKey: ['career', key] })
    },
  })
}

/** Asks for a matching profile suggested by the career profile. Nothing is created. */
export function useMatchingDraft() {
  const { source } = useDataSource()
  return useMutation({ mutationFn: () => source.createMatchingDraft() })
}
