import { Button } from '@/components/ui'

interface FileListProps {
  files: string[]
  onRemove: (path: string) => void
}

export default function FileList({ files, onRemove }: FileListProps) {
  if (files.length === 0) return null

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 2, maxHeight: 120, overflowY: 'auto' }}>
      {files.map((file) => (
        <div
          key={file}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 10,
            padding: '6px 12px',
            borderRadius: 'var(--radius-sm)',
            fontSize: 13,
            transition: 'background 0.1s',
          }}
          onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.background = 'var(--bg)' }}
          onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.background = 'transparent' }}
        >
          <span style={{ color: 'var(--muted)', fontSize: 14 }}>♪</span>
          <span
            style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontWeight: 500, color: 'var(--fg)' }}
            title={file}
          >
            {file.split(/[/\\]/).pop()}
          </span>
          <span style={{ color: 'var(--muted)', fontSize: 11, maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {file.replace(/[/\\][^/\\]+$/, '')}
          </span>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => onRemove(file)}
            style={{ padding: '2px 6px', fontSize: 12 }}
          >
            ×
          </Button>
        </div>
      ))}
    </div>
  )
}
