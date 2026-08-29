import { useEffect, useRef } from 'react'
import { useTaskStore } from '@/stores/taskStore'
import { tasksApi } from '@/api/tasks'

/**
 * Poll backend task status every `intervalMs` when there are active (pending/running) tasks.
 * Automatically stops polling when all tasks are in terminal state.
 */
export function useTaskPolling(intervalMs = 3000, enabled = true) {
    const tasks = useTaskStore((s) => s.tasks)
    const syncFromServer = useTaskStore((s) => s.syncFromServer)
    const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

    const hasActiveTasks = tasks.some(
        (t) => t.status === 'pending' || t.status === 'running'
    )

    useEffect(() => {
        if (!enabled) return
        let disposed = false

        const poll = async () => {
            let shouldSchedule = hasActiveTasks
            try {
                const response = await tasksApi.list()
                if (disposed) return
                syncFromServer(response.tasks)
                shouldSchedule = response.tasks.some(
                    (task) => task.state === 'pending' || task.state === 'running'
                )
            } catch {
                shouldSchedule = true
            }

            if (!disposed && shouldSchedule) {
                timerRef.current = setTimeout(() => { void poll() }, intervalMs)
            }
        }

        // Poll immediately on activation, then wait for each request before scheduling the next.
        void poll()

        return () => {
            disposed = true
            if (timerRef.current) {
                clearTimeout(timerRef.current)
                timerRef.current = null
            }
        }
    }, [enabled, hasActiveTasks, intervalMs, syncFromServer])
}
