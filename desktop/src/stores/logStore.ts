import { create } from 'zustand'
import type { RuntimeEventResponse } from '@/api/types'

export type LogLevel = 'info' | 'warn' | 'error'

export interface LogEntry {
  id: string
  timestamp: number
  level: LogLevel
  content: string
  taskId?: string
  serverTaskId?: string
  sequence?: number
  eventType?: string
  stage?: string
  detail?: string
  data?: Record<string, unknown>
}

interface LogStore {
  logs: LogEntry[]
  levelFilter: LogLevel[]
  maxLogs: number

  addLog: (entry: Omit<LogEntry, 'id' | 'timestamp'>) => void
  addRuntimeEvent: (event: RuntimeEventResponse, taskId?: string) => void
  clearLogs: () => void
  setLevelFilter: (levels: LogLevel[]) => void
}

let nextLogId = 1

export const useLogStore = create<LogStore>((set) => ({
  logs: [],
  levelFilter: ['info', 'warn', 'error'],
  maxLogs: 500,

  addLog: (entry) =>
    set((s) => {
      const newLog: LogEntry = {
        ...entry,
        id: `log-${nextLogId++}`,
        timestamp: Date.now(),
      }
      const logs = [...s.logs, newLog]
      if (logs.length > s.maxLogs) {
        return { logs: logs.slice(logs.length - s.maxLogs) }
      }
      return { logs }
    }),

  addRuntimeEvent: (event, taskId) =>
    set((s) => {
      const id = `runtime-${event.task_id}-${event.sequence}`
      if (s.logs.some((entry) => entry.id === id)) return s
      const level: LogLevel =
        event.level === 'error'
          ? 'error'
          : event.level === 'warning'
            ? 'warn'
            : 'info'
      const entry: LogEntry = {
        id,
        timestamp: Date.parse(event.time) || Date.now(),
        level,
        content: event.message || event.type,
        taskId: taskId ?? event.task_id,
        serverTaskId: event.task_id,
        sequence: event.sequence,
        eventType: event.type,
        stage: event.stage ?? undefined,
        detail: event.detail ?? undefined,
        data: event.data,
      }
      const logs = [...s.logs, entry]
      return {
        logs:
          logs.length > s.maxLogs
            ? logs.slice(logs.length - s.maxLogs)
            : logs,
      }
    }),

  clearLogs: () => set({ logs: [] }),

  setLevelFilter: (levels) => set({ levelFilter: levels }),
}))
