import { useState } from 'react'
import { t, useI18n } from '@/i18n'
import { useNavStore } from '@/stores/navStore'

const MCP_TOOLS = [
  { name: 'asmr_inspect_work', desc: '扫描作品目录，自动配对无损主轨、分轨与同名字幕/台本' },
  { name: 'asmr_prepare_draft', desc: '阶段一：执行分离/ASR/翻译/样音提取，生成待确认草稿' },
  { name: 'asmr_get_draft_audit', desc: '读取客观质检报告（漏译、假名残留、超速挤压预警）' },
  { name: 'asmr_patch_draft', desc: '按修订版本号批量修改译文、发声风格或音色方案' },
  { name: 'asmr_commit_draft', desc: '阶段二：渲染双耳声像跟随成品，支持指定单句重抽' },
  { name: 'asmr_list_voices_and_presets', desc: '枚举当前可用的声音库配方、连接与引擎列表' },
]

export default function AgentMcpSettings() {
  useI18n()
  const [projectRoot, setProjectRoot] = useState('D:/WorkSpace/AsmrHelper')
  const [copied, setCopied] = useState('')
  const openReview = useNavStore((s) => s.openReview)

  const normalizedRoot = projectRoot.trim().replace(/\\/g, '/').replace(/\/+$/, '') || 'D:/WorkSpace/AsmrHelper'
  const mcpJson = JSON.stringify(
    {
      mcpServers: {
        'asmr-helper': {
          command: `${normalizedRoot}/.venv/Scripts/python.exe`,
          args: ['-m', 'packages.mcp_server.server'],
          cwd: normalizedRoot,
          env: {
            PYTHONPATH: normalizedRoot,
            ASMR_HELPER_DOWNLOAD_REGION: 'cn',
          },
        },
      },
    },
    null,
    2,
  )

  const copyText = async (text: string, label: string) => {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(label)
      window.setTimeout(() => setCopied(''), 2500)
    } catch {
      setCopied('复制失败，请手动选中复制')
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 18, maxWidth: 880 }}>
      <section className="settings-path-section" style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 10 }}>
          <div>
            <h3 style={{ margin: 0 }}>{t('MCP Server 接入配置（Antigravity / Cursor / Claude Code）')}</h3>
            <p style={{ margin: '4px 0 0', fontSize: 'var(--text-help)', color: 'var(--muted)' }}>
              {t('Agent 通过 MCP 自动完成阶段一预审后，草稿会实时同步至桌面端「精修与字幕」，供你试听样音与确认交付。')}
            </p>
          </div>
          <button
            type="button"
            className="settings-button"
            onClick={() => void openReview('drafts')}
          >
            {t('打开待审草稿 ↗')}
          </button>
        </div>

        <label style={{ display: 'flex', flexDirection: 'column', gap: 6, fontSize: 13 }}>
          <span style={{ fontWeight: 600 }}>{t('项目根目录（用于生成下方配置）')}</span>
          <input
            value={projectRoot}
            onChange={(e) => setProjectRoot(e.target.value)}
            style={{ padding: '8px 10px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)', background: 'var(--surface-elevated)', color: 'var(--fg)', fontFamily: 'var(--font-mono)', fontSize: 12.5 }}
          />
        </label>

        <pre
          style={{
            margin: 0,
            padding: '12px 14px',
            borderRadius: 'var(--radius-sm)',
            background: 'var(--panel-muted)',
            border: '1px solid var(--border)',
            fontFamily: 'var(--font-mono)',
            fontSize: 12,
            overflowX: 'auto',
          }}
        >
          {mcpJson}
        </pre>

        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          <button
            type="button"
            className="settings-button primary"
            onClick={() => void copyText(mcpJson, '已复制 mcp_config.json 配置')}
          >
            {t('一键复制 MCP JSON')}
          </button>
          <button
            type="button"
            className="settings-button"
            onClick={() => void copyText(`claude mcp add asmr-helper -- ${normalizedRoot}/.venv/Scripts/python.exe -m packages.mcp_server.server`, '已复制 Claude Code 命令')}
          >
            {t('复制 Claude Code 注册命令')}
          </button>
          {copied && <span style={{ fontSize: 12.5, color: 'var(--success)' }}>{t(copied)}</span>}
        </div>
      </section>

      <section className="settings-path-section" style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        <h3 style={{ margin: 0 }}>{t('已暴露的 V2 正交 MCP 工具（6 项）')}</h3>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: 10 }}>
          {MCP_TOOLS.map((tool) => (
            <div
              key={tool.name}
              style={{
                padding: '10px 12px',
                borderRadius: 'var(--radius-sm)',
                border: '1px solid var(--border)',
                background: 'var(--surface-elevated)',
              }}
            >
              <code style={{ fontSize: 12.5, fontWeight: 650, color: 'var(--accent)' }}>{tool.name}</code>
              <p style={{ margin: '4px 0 0', fontSize: 12, color: 'var(--muted-strong)', lineHeight: 1.45 }}>
                {t(tool.desc)}
              </p>
            </div>
          ))}
        </div>
      </section>
    </div>
  )
}
