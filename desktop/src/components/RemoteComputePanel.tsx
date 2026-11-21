import { useState } from 'react'
import { api } from '@/api/client'
import { t, useI18n } from '@/i18n'

const STORAGE_URL_KEY = 'asmr_helper_remote_worker_url'
const STORAGE_TOKEN_KEY = 'asmr_helper_remote_worker_token'

interface ProbeState {
  ok: boolean
  message: string
  details?: Record<string, unknown> | null
}

function loadStored(key: string): string {
  try {
    return window.localStorage.getItem(key) || ''
  } catch {
    return ''
  }
}

export default function RemoteComputePanel() {
  useI18n()
  const [workerUrl, setWorkerUrl] = useState(() => loadStored(STORAGE_URL_KEY))
  const [token, setToken] = useState(() => loadStored(STORAGE_TOKEN_KEY))
  const [testing, setTesting] = useState(false)
  const [probe, setProbe] = useState<ProbeState | null>(null)
  const [copied, setCopied] = useState('')

  const saveLocal = () => {
    try {
      window.localStorage.setItem(STORAGE_URL_KEY, workerUrl.trim())
      window.localStorage.setItem(STORAGE_TOKEN_KEY, token.trim())
      setProbe({ ok: true, message: '已保存远端算力连接草稿。启动后端前可使用下方环境变量生效。' })
    } catch {
      setProbe({ ok: false, message: '无法写入本地存储。' })
    }
  }

  const testConnection = async () => {
    setTesting(true)
    setProbe(null)
    try {
      const status = await api.get<{
        configured: boolean
        capabilities: Record<string, unknown> | null
        error: string | null
      }>('/runtime/remote-worker')
      if (!status.configured) {
        setProbe({ ok: false, message: '桌面后端还未接入远端算力。请用下方环境变量重新启动桌面端。' })
      } else if (status.error) {
        setProbe({ ok: false, message: `桌面后端连接 Worker 失败（${status.error}）。请检查会话、转发和密钥。` })
      } else {
        setProbe({
          ok: true,
          message: '桌面后端已连接远端 GPU Worker。',
          details: status.capabilities,
        })
      }
    } catch (err) {
      setProbe({
        ok: false,
        message: `无法检查桌面后端的 Worker 连接（${err instanceof Error ? err.message : String(err)}）。`,
      })
    } finally {
      setTesting(false)
    }
  }

  const envCommand = (value: string) => `'${value.replace(/'/g, "''")}'`
  const envSnippet = (showToken: boolean) => [
    `$env:ASMR_HELPER_REMOTE_WORKER_URL=${envCommand(workerUrl.trim() || 'http://127.0.0.1:8765')}`,
    `$env:ASMR_HELPER_REMOTE_WORKER_TOKEN=${envCommand((showToken && token.trim()) || '<Worker Token>')}`,
    '.\\RUNGUI.bat',
  ].join('\n')

  const copyEnv = async () => {
    try {
      await navigator.clipboard.writeText(envSnippet(true))
      setCopied('已复制 PowerShell 环境变量命令')
      window.setTimeout(() => setCopied(''), 2500)
    } catch {
      setCopied('复制失败，请手动选中下方命令')
    }
  }

  return (
    <div style={{ maxWidth: 920, display: 'flex', flexDirection: 'column', gap: 18 }}>
      <section
        style={{
          background: 'var(--surface)',
          border: '1px solid var(--border)',
          borderRadius: 'var(--radius-card)',
          padding: 20,
          boxShadow: 'var(--shadow-xs)',
          display: 'flex',
          flexDirection: 'column',
          gap: 14,
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 10 }}>
          <div>
            <h2 className="panel-title" style={{ margin: 0 }}>{t('远端 GPU 算力节点（Colab / 局域网 Worker）')}</h2>
            <p style={{ margin: '4px 0 0', fontSize: 'var(--text-help)', color: 'var(--muted)' }}>
              {t('无独立显卡或显存受限时，将人声分离（Demucs / Roformer）、语音识别、本地 TTS 与 Seed-VC 托管至远端 GPU Worker。')}
            </p>
          </div>
          <span
            style={{
              padding: '4px 10px',
              borderRadius: 999,
              fontSize: 12,
              fontWeight: 600,
              background: workerUrl.trim() ? 'var(--accent-soft)' : 'var(--panel-muted)',
              color: workerUrl.trim() ? 'var(--accent)' : 'var(--muted)',
            }}
          >
            {probe?.ok ? t('桌面已接入') : t('连接设置')}
          </span>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: 12 }}>
          <label style={{ display: 'flex', flexDirection: 'column', gap: 6, fontSize: 13 }}>
            <span style={{ fontWeight: 600 }}>{t('Worker 服务地址（URL）')}</span>
            <input
              type="url"
              value={workerUrl}
              placeholder="http://127.0.0.1:8765"
              onChange={(e) => setWorkerUrl(e.target.value)}
              style={{ padding: '8px 10px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)', background: 'var(--surface-elevated)', color: 'var(--fg)' }}
            />
          </label>
          <label style={{ display: 'flex', flexDirection: 'column', gap: 6, fontSize: 13 }}>
            <span style={{ fontWeight: 600 }}>{t('鉴权密钥（Bearer Token）')}</span>
            <input
              type="password"
              autoComplete="off"
              value={token}
              placeholder={t('输入启动 Worker 时设置的 Token')}
              onChange={(e) => setToken(e.target.value)}
              style={{ padding: '8px 10px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)', background: 'var(--surface-elevated)', color: 'var(--fg)' }}
            />
          </label>
        </div>

        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, alignItems: 'center' }}>
          <button
            type="button"
            onClick={saveLocal}
            style={{ padding: '7px 14px', borderRadius: 'var(--radius-button)', border: '1px solid var(--accent)', background: 'var(--accent)', color: '#fff', fontWeight: 600, cursor: 'pointer' }}
          >
            {t('保存连接')}
          </button>
          <button
            type="button"
            disabled={testing}
            onClick={() => void testConnection()}
            style={{ padding: '7px 14px', borderRadius: 'var(--radius-button)', border: '1px solid var(--border)', background: 'var(--surface-elevated)', color: 'var(--fg)', cursor: 'pointer' }}
          >
            {testing ? t('正在探测远端能力…') : t('测试连通性')}
          </button>
          <button
            type="button"
            onClick={() => void copyEnv()}
            style={{ padding: '7px 14px', borderRadius: 'var(--radius-button)', border: '1px solid var(--border)', background: 'var(--panel-muted)', color: 'var(--fg)', cursor: 'pointer' }}
          >
            {t('复制后端环境变量')}
          </button>
          {copied && <span style={{ fontSize: 12, color: 'var(--success)' }}>{t(copied)}</span>}
        </div>

        {probe && (
          <div
            role="status"
            style={{
              padding: '10px 14px',
              borderRadius: 'var(--radius-sm)',
              background: probe.ok ? 'var(--success-soft)' : 'var(--warning-soft)',
              color: probe.ok ? 'var(--success)' : 'var(--fg)',
              fontSize: 13,
            }}
          >
            <div>{t(probe.message)}</div>
            {probe.details && (
              <pre style={{ marginTop: 8, fontSize: 11.5, overflowX: 'auto', fontFamily: 'var(--font-mono)' }}>
                {JSON.stringify(probe.details, null, 2)}
              </pre>
            )}
          </div>
        )}

        <pre
          style={{
            margin: 0,
            padding: '10px 12px',
            borderRadius: 'var(--radius-sm)',
            background: 'var(--panel-muted)',
            border: '1px solid var(--border)',
            fontFamily: 'var(--font-mono)',
            fontSize: 12,
            overflowX: 'auto',
          }}
        >
          {envSnippet(false)}
        </pre>
      </section>

      <section
        style={{
          background: 'var(--surface)',
          border: '1px solid var(--border)',
          borderRadius: 'var(--radius-card)',
          padding: 20,
          boxShadow: 'var(--shadow-xs)',
          display: 'flex',
          flexDirection: 'column',
          gap: 10,
        }}
      >
        <h3 className="section-title">{t('Google Colab GPU 会话')}</h3>
        <ol style={{ margin: 0, paddingLeft: 20, display: 'flex', flexDirection: 'column', gap: 6, fontSize: 13, color: 'var(--muted-strong)' }}>
          <li>{t('在已启动的 Colab 会话部署项目 Worker，再通过 Colab SSH 转发本地端口。')}</li>
          <li>{t('使用上方的环境变量启动桌面端，随后测试后端连接。')}</li>
          <li>{t('在创作台选择本地音频。流水线在需要时上传音频并取回结果，无需挂载 Google Drive。')}</li>
        </ol>
      </section>
    </div>
  )
}
