/** Moves to the field with this key inside `form` and focuses it, so nobody has to hunt for what is wrong. */
export function focusField(form: HTMLElement | null, key: string | null): void {
  if (!key) return
  const field = form?.querySelector<HTMLElement>(`[data-field="${key}"]`)
  field?.querySelector<HTMLElement>('input, textarea, select, button')?.focus()
  field?.scrollIntoView?.({ block: 'center', behavior: 'smooth' })
}
