import QuickStartHelp from '@/components/QuickStartHelp'
import { t, format, useI18n } from '@/i18n'
import { confirmAction } from '@/utils/confirmAction'
import { useEffect, useRef, useState } from 'react'
import { settingsApi } from '@/api/settings'
import type { SettingsView } from '@/api/settings'
import { useFileSelector } from '@/hooks/useFileSelector'
import { useNavStore } from '@/stores/navStore'
import './Settings.css'
import AppearanceSettings from '@/components/AppearanceSettings'
import WorkspaceSettings from '@/components/WorkspaceSettings'
import AgentMcpSettings from '@/components/AgentMcpSettings'

type Paths = SettingsView['paths']
type Category = 'appearance' | 'paths' | 'agent'

const EMPTY_PATHS: Paths = { output_dir: '', vtt_dir: '', model_cache_dir: '', temp_dir: '' }
const PATH_FIELDS: { key: keyof Paths; label: string; placeholder: string; hint: string; compatibility?: boolean }[] = [
  { key: 'output_dir', label: '输出目录', placeholder: '留空使用工作区 / output', hint: '默认结果位置；任务指定的输出位置优先。' },
  { key: 'vtt_dir', label: 'VTT 字幕目录', placeholder: '留空保留默认配置', hint: '兼容字段；节点流水线仍在创作台指定字幕输入。', compatibility: true },
  { key: 'model_cache_dir', label: '默认模型目录', placeholder: '留空使用工作区 / models', hint: '外部目录只读；缺失权重下载到本项目 models。' },
  { key: 'temp_dir', label: '临时文件目录', placeholder: '留空使用工作区 / debug / runtime', hint: '供工作区会话存放处理中间文件。' },
]
const reason = (error: unknown) => error instanceof Error ? error.message : String(error)

function Icon({ kind }: { kind: 'graph' | 'folder' | 'refresh' }) {
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true">
      {kind === 'graph' ? (
        <path d="M2 3h6v6H2zM12 11h6v6h-6zM8 6h7v5M5 9v5h7" />
      ) : kind === 'folder' ? (
        <path d="M2 5h6l2 2h8v9H2zM2 5V3h6l2 2" />
      ) : (
        <path d="M16 7a6 6 0 1 0 0 7M16 3v4h-4" />
      )}
    </svg>
  )
}

export default function Settings() {
  useI18n()
  const { selectFolder } = useFileSelector()
  const [category, setCategory] = useState<Category>('appearance')
  const [workspaceBusy, setWorkspaceBusy] = useState(false)
  const [paths, setPaths] = useState<Paths>(EMPTY_PATHS)
  const [savedPaths, setSavedPaths] = useState<Paths | null>(null)
  const [pathsLoading, setPathsLoading] = useState(false)
  const [pathsSaving, setPathsSaving] = useState(false)
  const [pathsLoadError, setPathsLoadError] = useState('')
  const [pathsMessage, setPathsMessage] = useState('')
  const [pathsSaveError, setPathsSaveError] = useState(false)
  const [browsing, setBrowsing] = useState<keyof Paths | null>(null)
  const mounted = useRef(true)
  const loadGeneration = useRef(0)
  const actionRef = useRef(false)
  const versions = useRef({ output_dir: 0, vtt_dir: 0, model_cache_dir: 0, temp_dir: 0 })
  const pathState = useRef({ paths, savedPaths, pathsSaving, browsing })
  pathState.current = { paths, savedPaths, pathsSaving, browsing }
  const dirty = !!savedPaths && PATH_FIELDS.some(field => paths[field.key] !== savedPaths[field.key])
  const busy = workspaceBusy || pathsSaving || browsing !== null
  const navigation = useRef({ dirty, busy: false })
  navigation.current = { dirty, busy }

  async function loadPaths() {
    if (pathState.current.pathsSaving || pathState.current.browsing) return
    const generation = ++loadGeneration.current
    const readVersions = { ...versions.current }
    const previous = pathState.current.savedPaths
    setPathsLoading(true)
    setPathsLoadError('')
    try {
      const response = await settingsApi.get()
      if (!mounted.current || generation !== loadGeneration.current) return
      const fresh = response.settings.paths
      setSavedPaths({ ...fresh })
      setPaths(current => Object.fromEntries(PATH_FIELDS.map(({ key }) => [key,
        versions.current[key] === readVersions[key] && (previous === null || current[key] === previous[key]) ? fresh[key] : current[key],
      ])) as Paths)
    } catch (error) {
      if (mounted.current && generation === loadGeneration.current) {
        setPathsLoadError(`无法读取路径设置：${reason(error)}。当前输入已保留。`)
      }
    } finally {
      if (mounted.current && generation === loadGeneration.current) setPathsLoading(false)
    }
  }

  useEffect(() => {
    mounted.current = true
    void loadPaths()
    return () => { mounted.current = false; loadGeneration.current++ }
  }, [])

  useEffect(() => {
    const guard = async () => {
      if (navigation.current.busy || actionRef.current) return false
      return !navigation.current.dirty || await confirmAction(t('路径有未保存的修改。离开设置页将放弃这些路径修改，继续离开？'))
    }
    useNavStore.getState().setNavigationGuard(guard)
    const beforeUnload = (event: BeforeUnloadEvent) => {
      if (navigation.current.dirty || navigation.current.busy || actionRef.current) {
        event.preventDefault()
        event.returnValue = ''
      }
    }
    window.addEventListener('beforeunload', beforeUnload)
    return () => {
      if (useNavStore.getState().navigationGuard === guard) useNavStore.getState().setNavigationGuard(null)
      window.removeEventListener('beforeunload', beforeUnload)
    }
  }, [])

  function changePath(key: keyof Paths, value: string) {
    versions.current[key]++
    setPaths(current => ({ ...current, [key]: value }))
    setPathsMessage('')
  }

  async function browse(key: keyof Paths) {
    if (busy || !savedPaths || pathsLoadError) return
    const version = versions.current[key]
    setBrowsing(key)
    actionRef.current = true
    try {
      const value = await selectFolder()
      if (!mounted.current || value === null) return
      if (version === versions.current[key]) changePath(key, value)
      else {
        setPathsMessage('选择文件夹期间该字段已有修改，已保留最新输入。')
        setPathsSaveError(false)
      }
    } catch (error) {
      if (mounted.current) {
        setPathsMessage(`选择失败：${reason(error)}`)
        setPathsSaveError(true)
      }
    } finally {
      actionRef.current = false
      if (mounted.current) setBrowsing(null)
    }
  }

  async function savePaths() {
    if (busy || pathsLoading || pathsLoadError || !savedPaths || !dirty || actionRef.current) return
    const changed = Object.fromEntries(PATH_FIELDS.filter(({ key }) => paths[key] !== savedPaths[key]).map(({ key }) => [key, paths[key]]))
    const submittedVersions = { ...versions.current }
    const previous = savedPaths
    actionRef.current = true
    setPathsSaving(true)
    setPathsMessage('')
    setPathsSaveError(false)
    try {
      const validation = await settingsApi.validate({ paths: changed })
      if (!mounted.current) return
      if (!validation.valid) {
        setPathsMessage(`验证失败：${validation.errors.join('；')}`)
        setPathsSaveError(true)
        return
      }
      const response = await settingsApi.update({ paths: changed })
      if (!mounted.current) return
      const fresh = response.settings.paths
      setSavedPaths({ ...fresh })
      setPaths(current => Object.fromEntries(PATH_FIELDS.map(({ key }) => [key,
        versions.current[key] === submittedVersions[key] && (key in changed || current[key] === previous[key]) ? fresh[key] : current[key],
      ])) as Paths)
      setPathsMessage('路径已保存，已有文件未移动。')
    } catch (error) {
      if (mounted.current) {
        setPathsMessage(`保存失败：${reason(error)}。当前输入已保留。`)
        setPathsSaveError(true)
      }
    } finally {
      actionRef.current = false
      if (mounted.current) setPathsSaving(false)
    }
  }

  return (
    <div className="settings-page">
      <header className="page-heading app-page-heading settings-page-heading">
        <div className="page-title-row"><h1 className="page-title">{t('设置')}</h1><QuickStartHelp topic={category === 'appearance' ? 'appearance' : 'paths'} /></div>
      </header>
      <aside className="settings-sidebar">
        <p className="settings-sidebar-caption">{t('系统与工作区')}</p>
        <nav className="settings-categories" aria-label={t('设置分类')}>
          <button type="button" aria-current={category === 'appearance' ? 'page' : undefined} onClick={() => setCategory('appearance')}>
            <span aria-hidden="true">◐</span><span>{t('外观与语言')}</span>
          </button>
          <button type="button" aria-current={category === 'paths' ? 'page' : undefined} onClick={() => setCategory('paths')}>
            <Icon kind="folder" /><span>{t('文件与缓存')}</span>
          </button>
          <button type="button" aria-current={category === 'agent' ? 'page' : undefined} onClick={() => setCategory('agent')}>
            <Icon kind="graph" /><span>{t('Agent / MCP 接入')}</span>
          </button>
        </nav>
        <div style={{ marginTop: 'auto', paddingTop: 14, borderTop: '1px solid var(--border)' }}>
          <button
            type="button"
            className="settings-button quiet"
            style={{ width: '100%', justifyContent: 'center' }}
            onClick={() => void useNavStore.getState().setPage('workflow-presets')}
          >
            {t('高级流程编排 ↗')}
          </button>
        </div>
      </aside>

      <main className="settings-main" aria-label={t('设置内容')}>
        <header className="settings-header page-heading">
          <div className="page-heading__copy">
            <div className="page-title-row">
              <h2 className="panel-title">
                {category === 'appearance' ? t('外观与语言') : category === 'agent' ? t('Agent / MCP 接入') : t('文件与缓存')}
              </h2>
            </div>
          </div>
          <div className="settings-header-actions page-heading__actions">
            {category === 'paths' ? (
              <button className="settings-button quiet" disabled={busy || pathsLoading} onClick={() => void loadPaths()}>
                <Icon kind="refresh" />{t('重新读取')}
              </button>
            ) : null}
          </div>
        </header>

        <div className="settings-body">
          {category === 'appearance' ? (
            <AppearanceSettings />
          ) : category === 'agent' ? (
            <AgentMcpSettings />
          ) : (
            <>
              <WorkspaceSettings disabled={busy || dirty || pathsLoading} onBusy={setWorkspaceBusy} />
              {dirty && <p className="settings-paths-summary">{t('请先保存或放弃下方路径草稿，再切换工作目录。')}</p>}
              {pathsLoading && <p className="settings-status" role="status">{t('正在读取路径…')}</p>}
              {pathsLoadError && (
                <p className="settings-status error" role="alert">
                  {t(pathsLoadError)}
                  <button onClick={() => void loadPaths()} disabled={pathsLoading || busy}>{t('重试')}</button>
                </p>
              )}
              {pathsMessage && (
                <p className={`settings-status${pathsSaveError ? ' error' : ''}`} role={pathsSaveError ? 'alert' : 'status'}>
                  {t(pathsMessage)}
                </p>
              )}
              {[0, 2].map(start => (
                <section className="settings-path-section" key={start}>
                  <h3><Icon kind="folder" />{start === 0 ? t('输出与字幕') : t('模型与临时文件')}</h3>
                  {PATH_FIELDS.slice(start, start + 2).map(field => (
                    <div className="settings-path-field" key={field.key}>
                      <div className="settings-field-label">
                        <label htmlFor={`settings-${field.key}`}>{t(field.label)}</label>
                        {field.compatibility && <span>{t('兼容')}</span>}
                      </div>
                      <div className="settings-path-row">
                        <input
                          id={`settings-${field.key}`}
                          value={paths[field.key]}
                          disabled={!savedPaths || pathsSaving || !!pathsLoadError}
                          placeholder={t(field.placeholder)}
                          autoComplete="off"
                          spellCheck={false}
                          onChange={event => changePath(field.key, event.target.value)}
                        />
                        <button
                          className="settings-button"
                          disabled={!savedPaths || busy || !!pathsLoadError}
                          aria-label={format('浏览{0}', [t(field.label)])}
                          onClick={() => void browse(field.key)}
                        >
                          <Icon kind="folder" />{browsing === field.key ? t('选择中…') : t('浏览')}
                        </button>
                      </div>
                      <p>{t(field.hint)}</p>
                    </div>
                  ))}
                </section>
              ))}
            </>
          )}
        </div>

        {category === 'paths' && (
          <footer className="settings-save-bar">
            <span className={dirty ? 'changed' : ''}>
              ● {dirty ? t('有未保存的修改') : savedPaths ? t('使用已保存的路径') : t('尚未读取路径')}
            </span>
            <div>
              <button
                className="settings-button quiet"
                disabled={!dirty || busy || pathsLoading}
                onClick={() => {
                  if (savedPaths) {
                    PATH_FIELDS.forEach(({ key }) => versions.current[key]++)
                    setPaths({ ...savedPaths })
                    setPathsMessage('')
                  }
                }}
              >
                {t('放弃修改')}
              </button>
              <button
                className="settings-button primary"
                disabled={!dirty || busy || pathsLoading || !!pathsLoadError}
                onClick={() => void savePaths()}
              >
                {pathsSaving ? t('正在保存…') : t('保存路径')}
              </button>
            </div>
          </footer>
        )}
      </main>
    </div>
  )
}
