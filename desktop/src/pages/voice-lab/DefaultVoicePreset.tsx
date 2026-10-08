import { useState } from 'react'
import { api } from '@/api/client'

export default function DefaultVoicePreset({ onChanged, disabled }: { onChanged: () => Promise<void>; disabled?: boolean }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  return <details className="recipe-advanced"><summary>默认音色</summary>
    <p className="muted">Edge 中文·晓晓需联网及 edge-tts 依赖。删除后可在此重新添加。</p>
    <button type="button" disabled={disabled || busy} onClick={async () => {
      setBusy(true); setError(''); setNotice('')
      try { await api.post('/speech/default-preset/add'); await onChanged(); setNotice('默认预设已入库。') }
      catch (cause) { setError(String(cause)) }
      finally { setBusy(false) }
    }}>添加 Edge 默认预设</button>
    {error && <p role="alert" className="error">{error}</p>}{notice && <p role="status" className="muted">{notice}</p>}
  </details>
}
