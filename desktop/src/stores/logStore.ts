import { create } from 'zustand'

export type LogLevel = 'info' | 'warn' | 'error'

export interface LogEntry {
  id: string
  timestamp: number
  level: LogLevel
  content: string
  taskId?: string
}

interface LogStore {
  logs: LogEntry[]
  levelFilter: LogLevel[]
  maxLogs: number

  addLog: (entry: Omit<LogEntry, 'id' | 'timestamp'>) => void
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

  clearLogs: () => set({ logs: [] }),

  setLevelFilter: (levels) => set({ levelFilter: levels }),
}))
