import { useTaskStore } from '@/stores/taskStore'
import { useLogStore } from '@/stores/logStore'
import { useAudioPlayerStore } from '@/stores/audioPlayerStore'
import { useTaskPolling } from '@/hooks/useTaskPolling'
import { tasksApi } from '@/api/tasks'
import { NeuButton, NeuCard, NeuProgress, NeuTag } from '@/components/ui'
import StatusBadge from '@/components/shared/StatusBadge'
import EmptyState from '@/components/shared/EmptyState'
import LogEntryComp from '@/components/sidebar/LogEntry'
import type { LogLevel } from '@/stores/logStore'

const FILTER_OPTIONS: { value: 'all' | 'running' | 'completed' | 'failed'; label: string }[] = [
    { value: 'all', label: '全部' },
    { value: 'running', label: '运行中' },
    { value: 'completed', label: '已完成' },
    { value: 'failed', label: '失败' },
]

const LOG_LEVEL_OPTIONS: { value: LogLevel; label: string }[] = [
    { value: 'info', label: 'INFO' },
    { value: 'warn', label: 'WARN' },
    { value: 'error', label: 'ERROR' },
]

export default function TaskCenter() {
    // Enable automatic polling
    useTaskPolling(3000)

    const tasks = useTaskStore((s) => s.tasks)
    const filter = useTaskStore((s) => s.filter)
    const setFilter = useTaskStore((s) => s.setFilter)
    const selectedTaskId = useTaskStore((s) => s.selectedTaskId)
    const selectTask = useTaskStore((s) => s.selectTask)
    const removeTask = useTaskStore((s) => s.removeTask)
    const updateTask = useTaskStore((s) => s.updateTask)

    const logs = useLogStore((s) => s.logs)
    const levelFilter = useLogStore((s) => s.levelFilter)
    const setLevelFilter = useLogStore((s) => s.setLevelFilter)
    const clearLogs = useLogStore((s) => s.clearLogs)
    const addLog = useLogStore((s) => s.addLog)

    const showAudio = useAudioPlayerStore((s) => s.show)

    const filteredTasks = filter === 'all' ? tasks : tasks.filter((t) => t.status === filter)
    const selectedTask = tasks.find((t) => t.id === selectedTaskId)
    const taskLogs = selectedTaskId
        ? logs.filter((l) => l.taskId === selectedTaskId)
        : logs
    const filteredLogs = taskLogs.filter((l) => levelFilter.includes(l.level))

    const toggleLogLevel = (level: LogLevel) => {
        if (levelFilter.includes(level)) {
            setLevelFilter(levelFilter.filter((l) => l !== level))
        } else {
            setLevelFilter([...levelFilter, level])
        }
    }

    const handleCancel = async (taskId: string) => {
        try {
            await tasksApi.cancel(taskId)
            updateTask(taskId, { status: 'failed', message: 'cancelled' })
            addLog({ level: 'info', content: `任务已取消: ${taskId}`, taskId })
        } catch (err) {
            addLog({ level: 'error', content: `取消失败: ${err}`, taskId })
        }
    }

    const handleRetry = async (taskId: string) => {
        try {
            await tasksApi.retry(taskId)
            updateTask(taskId, { status: 'pending', progress: 0, message: 'queued for retry' })
            addLog({ level: 'info', content: `任务已重试: ${taskId}`, taskId })
        } catch (err) {
            addLog({ level: 'error', content: `重试失败: ${err}`, taskId })
        }
    }

    const handlePlayArtifact = (path: string, type: string) => {
        showAudio(path, type)
    }

    return (
        <div style={{ display: 'flex', gap: '16px', height: '100%' }}>
            {/* Left: Task List */}
            <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '12px', minWidth: 0 }}>
                {/* Filters */}
                <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                    {FILTER_OPTIONS.map((opt) => (
                        <NeuButton
                            key={opt.value}
                            size="sm"
                            variant={filter === opt.value ? 'primary' : 'secondary'}
                            onClick={() => setFilter(opt.value)}
                        >
                            {opt.label}
                        </NeuButton>
                    ))}
                </div>

                {/* Task List */}
                <div style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '8px' }}>
                    {filteredTasks.length === 0 ? (
                        <EmptyState message="暂无任务" />
                    ) : (
                        filteredTasks.map((task) => (
                            <NeuCard
                                key={task.id}
                                hoverable
                                onClick={() => selectTask(task.id)}
                                style={{
                                    border: selectedTaskId === task.id ? '2px solid var(--accent-text)' : '2px solid transparent',
                                    padding: '12px 16px',
                                }}
                            >
                                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '8px' }}>
                                    <div style={{ flex: 1, minWidth: 0 }}>
                                        <div style={{ fontWeight: 500, fontSize: '0.875rem', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                            {task.sourceName}
                                        </div>
                                        <div style={{ display: 'flex', gap: '8px', alignItems: 'center', marginTop: '4px' }}>
                                            <NeuTag>{task.jobType}</NeuTag>
                                            <StatusBadge status={task.status} />
                                            <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
                                                {new Date(task.createdAt).toLocaleTimeString()}
                                            </span>
                                        </div>
                                        {task.status === 'running' && (
                                            <div style={{ marginTop: '8px' }}>
                                                <NeuProgress value={task.progress} />
                                            </div>
                                        )}
                                        {task.message && (
                                            <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginTop: '4px' }}>
                                                {task.message}
                                            </div>
                                        )}
                                        {/* Artifacts */}
                                        {task.status === 'completed' && task.artifacts && (
                                            <div style={{ marginTop: '8px', display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
                                                {Object.entries(task.artifacts.files).map(([type, path]) => (
                                                    <NeuButton
                                                        key={type}
                                                        size="sm"
                                                        variant="ghost"
                                                        onClick={(e) => {
                                                            e.stopPropagation()
                                                            if (type.includes('audio') || type.includes('mix')) {
                                                                handlePlayArtifact(path, type)
                                                            }
                                                        }}
                                                    >
                                                        {type.includes('audio') || type.includes('mix') ? '▶ ' : '📄 '}
                                                        {type}
                                                    </NeuButton>
                                                ))}
                                            </div>
                                        )}
                                    </div>
                                    <div style={{ display: 'flex', gap: '4px', flexShrink: 0 }}>
                                        {(task.status === 'pending' || task.status === 'running') && (
                                            <NeuButton size="sm" variant="ghost" onClick={() => handleCancel(task.id)}>
                                                取消
                                            </NeuButton>
                                        )}
                                        {(task.status === 'failed') && (
                                            <NeuButton size="sm" variant="ghost" onClick={() => handleRetry(task.id)}>
                                                重试
                                            </NeuButton>
                                        )}
                                        <NeuButton size="sm" variant="ghost" onClick={() => removeTask(task.id)}>
                                            删除
                                        </NeuButton>
                                    </div>
                                </div>
                            </NeuCard>
                        ))
                    )}
                </div>
            </div>

            {/* Right: Logs */}
            <div style={{ width: '360px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span style={{ fontWeight: 600, fontSize: '0.875rem', color: 'var(--text-primary)' }}>
                        {selectedTask ? `${selectedTask.sourceName} 日志` : '系统日志'}
                    </span>
                    <div style={{ display: 'flex', gap: '4px' }}>
                        {LOG_LEVEL_OPTIONS.map((opt) => (
                            <NeuButton
                                key={opt.value}
                                size="sm"
                                variant={levelFilter.includes(opt.value) ? 'primary' : 'ghost'}
                                onClick={() => toggleLogLevel(opt.value)}
                                style={{ fontSize: '0.6875rem', padding: '2px 8px' }}
                            >
                                {opt.label}
                            </NeuButton>
                        ))}
                        <NeuButton size="sm" variant="ghost" onClick={clearLogs}>
                            清空
                        </NeuButton>
                    </div>
                </div>
                <div style={{ flex: 1, overflowY: 'auto', background: 'var(--bg-base)', borderRadius: '12px', boxShadow: 'var(--shadow-pressed)', padding: '8px 0' }}>
                    {filteredLogs.length === 0 ? (
                        <EmptyState message="暂无日志" />
                    ) : (
                        filteredLogs.map((entry) => <LogEntryComp key={entry.id} entry={entry} />)
                    )}
                </div>
            </div>
        </div>
    )
}
