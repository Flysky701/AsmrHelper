import { NeuCard } from '@/components/ui'

export default function TaskCenter() {
    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            <NeuCard>
                <div style={{ padding: '24px', textAlign: 'center', color: 'var(--text-secondary)' }}>
                    任务中心 — 正在建设中
                </div>
            </NeuCard>
        </div>
    )
}
