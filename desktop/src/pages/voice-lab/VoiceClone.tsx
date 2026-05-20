import { NeuCard } from '@/components/ui'

export default function VoiceClone() {
  return (
    <NeuCard>
      <div
        style={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          padding: '48px 0',
          gap: '12px',
        }}
      >
        <span style={{ fontSize: '32px', opacity: 0.3 }}>⧉</span>
        <span style={{ color: 'var(--text-secondary)', fontSize: '1rem' }}>
          音色克隆功能即将上线
        </span>
        <span style={{ color: 'var(--text-secondary)', fontSize: '0.8125rem' }}>
          上传参考音频，克隆音色特征
        </span>
      </div>
    </NeuCard>
  )
}
