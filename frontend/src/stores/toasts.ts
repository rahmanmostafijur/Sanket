import { create } from 'zustand'

export type ToastTone = 'default' | 'success' | 'error' | 'match'

export interface Toast {
  id: number
  title: string
  description?: string
  tone: ToastTone
  action?: { label: string; href: string }
}

interface ToastState {
  toasts: Toast[]
  push: (toast: Omit<Toast, 'id' | 'tone'> & { tone?: ToastTone }) => void
  dismiss: (id: number) => void
}

const MAX_TOASTS = 4
let nextId = 1

export const useToasts = create<ToastState>()((set, get) => ({
  toasts: [],
  push: (toast) => {
    const entry: Toast = { tone: 'default', ...toast, id: nextId++ }
    set({ toasts: [...get().toasts, entry].slice(-MAX_TOASTS) })
  },
  dismiss: (id) => set({ toasts: get().toasts.filter((toast) => toast.id !== id) }),
}))

/** Show a toast from outside React (mutation callbacks and the like). */
export const toast = (input: Parameters<ToastState['push']>[0]): void => useToasts.getState().push(input)
