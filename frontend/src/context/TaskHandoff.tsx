import { createContext, useContext, useRef } from 'react'
import type { ReactNode } from 'react'
import type { SourceDescriptor } from '@/lib/types'

export interface PendingTask {
  taskId: string
  source: SourceDescriptor
}

interface HandoffValue {
  set: (task: PendingTask) => void
  take: () => PendingTask | null
}

const TaskHandoffContext = createContext<HandoffValue | null>(null)

/* Lets the RSS page create a task and hand it to the Transcribe view on
   navigation, replacing the original single-object cross-mixin reference. */
export function TaskHandoffProvider({ children }: { children: ReactNode }) {
  const pending = useRef<PendingTask | null>(null)
  const set = (task: PendingTask) => { pending.current = task }
  const take = () => {
    const v = pending.current
    pending.current = null
    return v
  }
  return <TaskHandoffContext.Provider value={{ set, take }}>{children}</TaskHandoffContext.Provider>
}

export function useTaskHandoff(): HandoffValue {
  const ctx = useContext(TaskHandoffContext)
  if (!ctx) throw new Error('useTaskHandoff must be used within TaskHandoffProvider')
  return ctx
}
