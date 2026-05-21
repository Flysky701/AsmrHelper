import { useEffect, useRef } from 'react'
import { useTaskStore } from '@/stores/taskStore'
import { tasksApi } from '@/api/tasks'

/**
 * Poll backend task status every `intervalMs` when there are active (pending/running) tasks.
 * Automatically stops polling when all tasks are in terminal state.
 */
export function useTaskPolling(intervalMs = 3000) {
    const tasks = useTaskStore((s) => s.tasks)
    const syncFromServer = useTaskStore((s) => s.syncFromServer)
    const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)

    const hasActiveTasks = tasks.some(
        (t) => t.status === 'pending' || t.status === 'running'
    )

    useEffect(() => {
        if (!hasActiveTasks) {
            if (timerRef.current) {
                clearInterval(timerRef.current)
                timerRef.current = null
            }
            return
        }

        const poll = async () => {
            try {
                const response = await tasksApi.list()
                syncFromServer(response.tasks)
            } catch {
                // Silently retry on next interval
            }
        }

        // Poll immediately on activation
        poll()

        timerRef.current = setInterval(poll, intervalMs)

        return () => {
            if (timerRef.current) {
                clearInterval(timerRef.current)
                timerRef.current = null
            }
        }
    }, [hasActiveTasks, intervalMs, syncFromServer])
}
