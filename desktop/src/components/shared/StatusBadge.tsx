import type { TaskStatus } from '@/stores/taskStore'
import { NeuTag } from '@/components/ui'

const STATUS_VARIANT: Record<TaskStatus, 'default' | 'info' | 'success' | 'error'> = {
  pending: 'default',
  running: 'info',
  completed: 'success',
  failed: 'error',
}

const STATUS_LABEL: Record<TaskStatus, string> = {
  pending: '等待中',
  running: '运行中',
  completed: '已完成',
  failed: '失败',
}

interface StatusBadgeProps {
  status: TaskStatus
}

export default function StatusBadge({ status }: StatusBadgeProps) {
  return <NeuTag variant={STATUS_VARIANT[status]}>{STATUS_LABEL[status]}</NeuTag>
}
