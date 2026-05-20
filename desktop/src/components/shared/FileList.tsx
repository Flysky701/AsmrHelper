import { NeuButton } from '@/components/ui'

interface FileListProps {
  files: string[]
  onRemove: (path: string) => void
}

export default function FileList({ files, onRemove }: FileListProps) {
  if (files.length === 0) return null

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: '4px',
        maxHeight: '120px',
        overflowY: 'auto',
      }}
    >
      {files.map((file) => (
        <div
          key={file}
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '6px 12px',
            background: 'var(--bg-base)',
            borderRadius: '8px',
            boxShadow: 'var(--shadow-pressed)',
            fontSize: '0.8125rem',
          }}
        >
          <span
            style={{
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
              flex: 1,
              color: 'var(--text-primary)',
            }}
            title={file}
          >
            {file}
          </span>
          <NeuButton
            size="sm"
            variant="ghost"
            onClick={() => onRemove(file)}
            style={{ marginLeft: '8px', padding: '2px 6px', fontSize: '0.75rem' }}
          >
            ✕
          </NeuButton>
        </div>
      ))}
    </div>
  )
}
