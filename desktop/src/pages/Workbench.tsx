import { useCallback, useEffect, useState } from 'react'
import type { CSSProperties, DragEvent, ReactNode } from 'react'

import { pipelineApi } from '@/api/pipeline'
import { capabilitiesApi } from '@/api/engines'
import { resourcesApi } from '@/api/resources'
import type {
  CapabilityDescriptorResponse,
  PipelineExecutionProfileRequest,
  PipelineRunRequest,
  TaskReadinessIssueResponse,
} from '@/api/types'
import { useFileSelector } from '@/hooks/useFileSelector'
import { useTaskPolling } from '@/hooks/useTaskPolling'
import { useLogStore } from '@/stores/logStore'
import { useNavStore } from '@/stores/navStore'
import { useTaskStore } from '@/stores/taskStore'
import type { TaskStatus } from '@/stores/taskStore'
import { useWorkbenchStore } from '@/stores/workbenchStore'

const LANG_OPTIONS = [
  { value: 'ja', label: '日语 (ja)' },
  { value: 'zh', label: '中文 (zh)' },
  { value: 'en', label: '英语 (en)' },
]

const TTS_ENGINE_OPTIONS = [
  { value: 'edge', label: 'Edge-TTS' },
  { value: 'qwen3', label: 'Qwen3-TTS' },
]

const TRANSLATE_PROVIDER_OPTIONS = [
  { value: 'deepseek', label: 'DeepSeek' },
  { value: 'openai', label: 'OpenAI' },
]

const ASR_MODEL_OPTIONS = [
  { value: 'tiny', label: 'tiny' },
  { value: 'base', label: 'base' },
  { value: 'small', label: 'small' },
  { value: 'medium', label: 'medium' },
  { value: 'large-v3', label: 'large-v3' },
]

const VOCAL_MODEL_OPTIONS = [
  { value: 'htdemucs', label: 'htdemucs' },
  { value: 'htdemucs_ft', label: 'htdemucs_ft' },
]

const STATUS_LABELS: Record<TaskStatus, string> = {
  pending: '排队中',
  running: '运行中',
  completed: '已完成',
  failed: '失败',
  cancelled: '已取消',
  skipped: '已跳过',
}

const SURFACE_STYLE: CSSProperties = {
  background: 'var(--surface)',
  border: '1px solid var(--border)',
  borderRadius: 'var(--radius-card)',
  boxShadow: 'var(--shadow-panel)',
}

const STAGE_NAMES = ['人声分离', 'ASR 识别', '字幕翻译', 'TTS 合成', '混音输出']

type Option = { value: string; label: string }

const PlayIcon = () => (
  <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.8">
    <path d="M4.5 3.25 10 7l-5.5 3.75z" fill="currentColor" stroke="none" />
  </svg>
)

const UploadIcon = () => (
  <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6">
    <path d="M8 3v7M5.25 5.75 8 3l2.75 2.75M3.25 11.75h9.5" />
  </svg>
)

const ArrowIcon = () => (
  <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.6">
    <path d="M3 7h8M7.75 3.5 11 7l-3.25 3.5" />
  </svg>
)

const ChevronIcon = ({ open }: { open: boolean }) => (
  <svg
    width="14"
    height="14"
    viewBox="0 0 14 14"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.6"
    style={{ transform: open ? 'rotate(0deg)' : 'rotate(-90deg)', transition: 'transform 0.16s ease' }}
  >
    <path d="m3.5 5.25 3.5 3.5 3.5-3.5" />
  </svg>
)

function mergeUniquePaths(current: string[], incoming: string[]) {
  return Array.from(new Set([...current, ...incoming]))
}

function fileName(path: string) {
  return path.split(/[/\\]/).pop() ?? path
}

function optionLabel(options: Option[], value: string) {
  return options.find((item) => item.value === value)?.label ?? value
}

function formatRelativeTime(timestamp: number) {
  const delta = Math.max(0, Date.now() - timestamp)
  const minutes = Math.floor(delta / 60000)
  if (minutes < 1) return '刚刚'
  if (minutes < 60) return `${minutes} 分钟前`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} 小时前`
  return `${Math.floor(hours / 24)} 天前`
}

function Section({
  title,
  caption,
  open = true,
  onToggle,
  actions,
  children,
}: {
  title: string
  caption?: string
  open?: boolean
  onToggle?: () => void
  actions?: ReactNode
  children: ReactNode
}) {
  return (
    <section style={{ ...SURFACE_STYLE, overflow: 'hidden' }}>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 12,
          padding: '16px 18px',
          borderBottom: open ? '1px solid var(--border)' : 'none',
        }}
      >
        {onToggle ? (
          <button
            type="button"
            onClick={onToggle}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 10,
              border: 'none',
              background: 'transparent',
              color: 'var(--fg)',
              cursor: 'pointer',
              padding: 0,
              textAlign: 'left',
            }}
          >
            <ChevronIcon open={open} />
            <div>
              <div style={{ fontSize: 14, fontWeight: 600 }}>{title}</div>
              {caption ? <div style={{ fontSize: 12, color: 'var(--muted)' }}>{caption}</div> : null}
            </div>
          </button>
        ) : (
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <div>
              <div style={{ fontSize: 14, fontWeight: 600 }}>{title}</div>
              {caption ? <div style={{ fontSize: 12, color: 'var(--muted)' }}>{caption}</div> : null}
            </div>
          </div>
        )}
        <div style={{ flex: 1 }} />
        {actions}
      </div>
      {open ? <div style={{ padding: 18 }}>{children}</div> : null}
    </section>
  )
}

function ActionButton({
  children,
  variant = 'secondary',
  disabled,
  onClick,
}: {
  children: ReactNode
  variant?: 'primary' | 'secondary' | 'ghost'
  disabled?: boolean
  onClick?: () => void
}) {
  const styles: Record<string, CSSProperties> = {
    primary: {
      background: 'var(--accent)',
      color: 'white',
      border: '1px solid var(--accent)',
      boxShadow: 'var(--shadow-float)',
    },
    secondary: {
      background: 'var(--surface)',
      color: 'var(--fg)',
      border: '1px solid var(--border)',
    },
    ghost: {
      background: 'transparent',
      color: 'var(--muted)',
      border: '1px solid transparent',
    },
  }

  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      style={{
        minHeight: 38,
        padding: '0 14px',
        borderRadius: 'var(--radius-button)',
        display: 'inline-flex',
        alignItems: 'center',
        gap: 8,
        fontSize: 13,
        fontWeight: 600,
        cursor: disabled ? 'not-allowed' : 'pointer',
        opacity: disabled ? 0.5 : 1,
        transition: 'transform 0.16s ease, box-shadow 0.16s ease, border-color 0.16s ease',
        ...styles[variant],
      }}
    >
      {children}
    </button>
  )
}

function FieldLabel({ title, hint }: { title: string; hint?: string }) {
  return (
    <div style={{ marginBottom: 8 }}>
      <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--fg)' }}>{title}</div>
      {hint ? <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>{hint}</div> : null}
    </div>
  )
}

function SelectField({
  title,
  hint,
  value,
  options,
  onChange,
}: {
  title: string
  hint?: string
  value: string
  options: Option[]
  onChange: (value: string) => void
}) {
  return (
    <div>
      <FieldLabel title={title} hint={hint} />
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        style={{
          width: '100%',
          minHeight: 40,
          padding: '0 12px',
          borderRadius: 'var(--radius-sm)',
          border: '1px solid var(--border)',
          background: 'var(--surface)',
          color: 'var(--fg)',
          fontSize: 13,
        }}
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </div>
  )
}

function RangeField({
  title,
  hint,
  value,
  min,
  max,
  step,
  displayValue,
  onChange,
}: {
  title: string
  hint?: string
  value: number
  min: number
  max: number
  step: number
  displayValue: string
  onChange: (value: number) => void
}) {
  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, marginBottom: 8 }}>
        <FieldLabel title={title} hint={hint} />
        <span style={{ fontSize: 12, color: 'var(--muted)', whiteSpace: 'nowrap' }}>{displayValue}</span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
        style={{ width: '100%', accentColor: 'var(--accent)' }}
      />
    </div>
  )
}

function ToggleField({
  title,
  hint,
  checked,
  onChange,
}: {
  title: string
  hint?: string
  checked: boolean
  onChange: (value: boolean) => void
}) {
  return (
    <button
      type="button"
      onClick={() => onChange(!checked)}
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        width: '100%',
        padding: '12px 14px',
        borderRadius: 'var(--radius-sm)',
        border: '1px solid var(--border)',
        background: checked ? 'var(--accent-soft)' : 'var(--surface)',
        cursor: 'pointer',
        textAlign: 'left',
      }}
    >
      <div>
        <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--fg)' }}>{title}</div>
        {hint ? <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>{hint}</div> : null}
      </div>
      <span
        style={{
          minWidth: 52,
          minHeight: 28,
          borderRadius: 999,
          background: checked ? 'var(--accent)' : 'var(--panel-muted)',
          color: checked ? 'white' : 'var(--muted)',
          display: 'inline-flex',
          alignItems: 'center',
          justifyContent: 'center',
          fontSize: 11,
          fontWeight: 700,
        }}
      >
        {checked ? '开启' : '关闭'}
      </span>
    </button>
  )
}

export default function Workbench() {
  useTaskPolling(3000)

  const {
    selectedFiles,
    preset,
    presets,
    params,
    commonExpanded,
    modelExpanded,
    advExpanded,
    setFiles,
    removeFile,
    setPreset,
    updateParam,
    toggleCommon,
    toggleModel,
    toggleAdv,
  } = useWorkbenchStore()

  const addTask = useTaskStore((state) => state.addTask)
  const updateTask = useTaskStore((state) => state.updateTask)
  const tasks = useTaskStore((state) => state.tasks)
  const addLog = useLogStore((state) => state.addLog)
  const setPage = useNavStore((state) => state.setPage)
  const { selectFiles } = useFileSelector()

  const [dragOver, setDragOver] = useState(false)
  const [capabilities, setCapabilities] = useState<CapabilityDescriptorResponse[]>([])
  const [capabilityError, setCapabilityError] = useState('')
  const [readinessIssues, setReadinessIssues] = useState<TaskReadinessIssueResponse[]>([])
  const [checkingReadiness, setCheckingReadiness] = useState(false)

  useEffect(() => {
    pipelineApi
      .presets()
      .then((response) => {
        useWorkbenchStore.getState().setPresets(response.presets)
        if (response.presets.length > 0 && !preset) {
          setPreset(response.presets[0]!.id)
        }
      })
      .catch(() => undefined)
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    capabilitiesApi
      .list()
      .then((items) => {
        setCapabilities(items)
        setCapabilityError('')
      })
      .catch((error) => {
        setCapabilities([])
        setCapabilityError(`能力目录加载失败：${error instanceof Error ? error.message : String(error)}`)
      })
  }, [])

  const runningCount = tasks.filter((task) => task.status === 'running').length
  const pendingCount = tasks.filter((task) => task.status === 'pending').length
  const completedCount = tasks.filter((task) => task.status === 'completed').length
  const recentTasks = tasks.slice(-5).reverse()

  const handleSelectFiles = useCallback(async () => {
    const files = await selectFiles()
    if (files.length > 0) {
      setFiles(mergeUniquePaths(selectedFiles, files))
    }
  }, [selectFiles, selectedFiles, setFiles])

  const handleDrop = useCallback((event: DragEvent<HTMLDivElement>) => {
    event.preventDefault()
    setDragOver(false)

    const dropped = Array.from(event.dataTransfer.files)
    if (dropped.length === 0) return

    const paths = dropped.map((file) => (file as File & { path?: string }).path || file.name)
    const hasFullPath = paths.some((path) => path.includes('/') || path.includes('\\'))

    if (hasFullPath) {
      setFiles(mergeUniquePaths(selectedFiles, paths))
      return
    }

    const dir = prompt(
      '浏览器模式无法获取完整路径。请输入文件所在目录：\n' + `（文件：${paths.join(', ')}）`,
      'D:\\Asmr',
    )

    if (!dir) return

    const sep = dir.includes('/') ? '/' : '\\'
    const fullPaths = paths.map((name) => `${dir}${sep}${name}`)
    setFiles(mergeUniquePaths(selectedFiles, fullPaths))
  }, [selectedFiles, setFiles])

  const handleExecute = async () => {
    if (selectedFiles.length === 0) return

    const executionProfile: PipelineExecutionProfileRequest = {
      version: 1,
      source_lang: params.sourceLang,
      target_lang: params.targetLang,
      skip_existing: params.skipExisting,
      stages: {
        separate: {
          enabled: params.useVocalSeparator,
          provider: params.vocalProvider,
          model: params.vocalModel,
          options: { mode: 'vocals' },
          provider_options: {},
        },
        asr: {
          enabled: true,
          provider: params.asrProvider,
          model: params.asrModel,
          options: {
            language: params.sourceLang,
            output_format: 'segments',
            timestamps: true,
          },
          provider_options: params.asrProvider === 'faster_whisper' ? { disable_vad: true } : {},
        },
        translate: {
          enabled: params.sourceLang !== params.targetLang,
          provider: params.translateProvider,
          model: null,
          options: {
            source_lang: params.sourceLang,
            target_lang: params.targetLang,
            preserve_timestamps: true,
          },
          provider_options: {},
        },
        tts: {
          enabled: true,
          provider: params.ttsEngine,
          model: null,
          options: {
            voice: params.ttsVoice,
            voice_profile_id: params.voiceProfileId,
            speed: params.ttsSpeed,
            language: params.targetLang,
          },
          provider_options: {},
        },
        mix: {
          enabled: true,
          provider: 'ffmpeg',
          model: null,
          options: {
            original_volume: params.originalVolume,
            tts_volume_ratio: params.ttsVolumeRatio,
            tts_delay_ms: params.ttsDelay * 1000,
            normalize: true,
          },
          provider_options: {},
        },
        export: {
          enabled: true,
          provider: 'ffmpeg',
          model: null,
          options: {
            subtitle_format: 'srt',
            include_intermediate_files: true,
          },
          provider_options: {},
        },
      },
    }

    setCheckingReadiness(true)
    setReadinessIssues([])
    try {
      const readiness = await resourcesApi.checkTaskReadiness('pipeline', executionProfile)
      if (!readiness.ready) {
        setReadinessIssues(readiness.issues)
        return
      }
    } catch (error) {
      setReadinessIssues([{
        stage: 'prepare',
        category: 'runtime',
        provider: '',
        model: null,
        code: 'READINESS_CHECK_FAILED',
        requirement: 'runtime readiness',
        message: error instanceof Error ? error.message : String(error),
        action: 'engines',
      }])
      return
    } finally {
      setCheckingReadiness(false)
    }

    for (const filePath of selectedFiles) {
      const request: PipelineRunRequest = {
        input: {
          path: filePath,
          companion_paths: [],
        },
        output: {},
        execution_profile: executionProfile,
      }

      const taskId = addTask({
        jobType: 'pipeline',
        sourceName: fileName(filePath),
        sourcePath: filePath,
        params: {
          input_path: filePath,
          source_lang: params.sourceLang,
          target_lang: params.targetLang,
          use_vocal_separator: params.useVocalSeparator,
          tts_engine: params.ttsEngine,
          tts_voice: params.ttsVoice,
          vocal_model: params.vocalModel,
          asr_model: params.asrModel,
          translate_provider: params.translateProvider,
          tts_speed: params.ttsSpeed,
          original_volume: params.originalVolume,
          tts_volume_ratio: params.ttsVolumeRatio,
          tts_delay: params.ttsDelay,
          skip_existing: params.skipExisting,
          voice_profile_id: params.voiceProfileId,
        },
      })

      updateTask(taskId, { message: '正在创建后端任务', progress: 0 })
      addLog({ level: 'info', content: `任务已创建：${filePath}`, taskId })

      try {
        const created = await pipelineApi.createTask(request)
        const remoteTask = created.task
        useTaskStore.getState().updateTask(taskId, {
          serverTaskId: remoteTask.task_id,
          status: remoteTask.state as TaskStatus,
          stage: remoteTask.stage ?? undefined,
          progress: Math.round(remoteTask.progress * 100),
          message: '后端已接管，等待执行',
          detail: remoteTask.detail,
        })
      } catch (error) {
          useTaskStore.getState().updateTask(taskId, {
            status: 'failed',
            progress: 0,
            message: '创建或启动任务失败',
            errorMessage: String(error),
          })
          addLog({ level: 'error', content: `任务异常：${String(error)}`, taskId })
      }
    }

    setPage('task-center')
  }

  const presetOptions = presets.length > 0
    ? presets.map((item) => ({ value: item.id, label: item.label || item.id }))
    : [{ value: '', label: '加载预设中...' }]

  const currentPreset = presets.find((item) => item.id === preset) ?? null

  const descriptorsFor = (category: string) =>
    capabilities.filter((item) => item.category === category)
  const providerOptions = (category: string, fallback: Option[]) => {
    const items = descriptorsFor(category)
    return items.length > 0
      ? items.map((item) => ({ value: item.provider, label: item.display_name }))
      : fallback
  }
  const modelsFor = (category: string, provider: string, fallback: Option[]) => {
    const descriptor = descriptorsFor(category).find((item) => item.provider === provider)
    return descriptor?.supported_models.length
      ? descriptor.supported_models.map((model) => ({ value: model, label: model }))
      : fallback
  }
  const defaultModelFor = (category: string, provider: string) =>
    descriptorsFor(category).find((item) => item.provider === provider)?.default_model ?? ''

  const ttsEngineOptions = providerOptions('tts', TTS_ENGINE_OPTIONS)
  const translateProviderOptions = providerOptions('llm', TRANSLATE_PROVIDER_OPTIONS)
  const asrProviderOptions = providerOptions('asr', [{ value: 'faster_whisper', label: 'faster-whisper' }])
  const asrModelOptions = modelsFor('asr', params.asrProvider, ASR_MODEL_OPTIONS)
  const vocalProviderOptions = providerOptions('separator', [{ value: 'demucs', label: 'Demucs' }])
  const vocalModelOptions = modelsFor('separator', params.vocalProvider, VOCAL_MODEL_OPTIONS)

  const ttsVoiceOptions = params.ttsEngine === 'qwen3'
    ? [
        { value: 'Serena', label: 'Serena (预设)' },
        { value: 'Vivian', label: 'Vivian (预设)' },
        { value: 'Chelsie', label: 'Chelsie (预设)' },
      ]
    : [
        { value: 'zh-CN-XiaoxiaoNeural', label: 'XiaoxiaoNeural' },
        { value: 'zh-CN-YunxiNeural', label: 'YunxiNeural' },
        { value: 'zh-CN-XiaoyiNeural', label: 'XiaoyiNeural' },
        { value: 'ja-JP-NanamiNeural', label: 'NanamiNeural' },
        { value: 'en-US-JennyNeural', label: 'JennyNeural' },
      ]

  const stageSummary = [
    {
      title: STAGE_NAMES[0],
      enabled: params.useVocalSeparator,
      detail: params.useVocalSeparator ? `模型：${params.vocalModel}` : '关闭后会直接进入 ASR',
    },
    {
      title: STAGE_NAMES[1],
      enabled: true,
      detail: `模型：${params.asrModel}`,
    },
    {
      title: STAGE_NAMES[2],
      enabled: params.sourceLang !== params.targetLang,
      detail: `${optionLabel(LANG_OPTIONS, params.sourceLang)} → ${optionLabel(LANG_OPTIONS, params.targetLang)} · ${params.translateProvider}`,
    },
    {
      title: STAGE_NAMES[3],
      enabled: true,
      detail: `${params.ttsEngine} · ${params.ttsVoice}`,
    },
    {
      title: STAGE_NAMES[4],
      enabled: true,
      detail: `原声 ${Math.round(params.originalVolume * 100)}% · TTS ${Math.round(params.ttsVolumeRatio * 100)}%`,
    },
  ]

  const outputSummary = [
    '混音成品音频',
    '字幕/文本产物',
    params.useVocalSeparator ? '分离人声中间产物' : '直接跳过人声分离',
  ]

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0 }}>
      <header
        style={{
          padding: '22px 28px 18px',
          borderBottom: '1px solid var(--border)',
          background: 'var(--surface)',
          display: 'flex',
          gap: 20,
          alignItems: 'flex-start',
          flexWrap: 'wrap',
        }}
      >
        <div style={{ minWidth: 260 }}>
          <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--accent)', letterSpacing: '0.08em', textTransform: 'uppercase' }}>
            Mainline Workspace
          </div>
          <h1 style={{ marginTop: 8, fontSize: 26, lineHeight: 1.15, fontWeight: 700, fontFamily: 'var(--font-display)' }}>
            工作台
          </h1>
          <p style={{ marginTop: 8, color: 'var(--muted)', maxWidth: 520 }}>
            先选择输入，再确认流水线和关键参数，最后把任务交给 TaskCenter 跟踪。
          </p>
        </div>

        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
          <ActionButton variant="secondary" onClick={handleSelectFiles}>
            <UploadIcon />
            添加音频
          </ActionButton>
          <div style={{ minWidth: 210 }}>
            <select
              value={preset}
              onChange={(event) => setPreset(event.target.value)}
              style={{
                width: '100%',
                minHeight: 38,
                padding: '0 12px',
                borderRadius: 'var(--radius-button)',
                border: '1px solid var(--border)',
                background: 'var(--surface)',
                color: 'var(--fg)',
                fontSize: 13,
                fontWeight: 600,
              }}
            >
              {presetOptions.map((option) => (
                <option key={option.value || 'loading'} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>
          <ActionButton variant="ghost" disabled={selectedFiles.length === 0} onClick={() => setFiles([])}>
            清空列表
          </ActionButton>
          <ActionButton
            variant="primary"
            disabled={selectedFiles.length === 0 || checkingReadiness || !!capabilityError}
            onClick={handleExecute}
          >
            <PlayIcon />
            {checkingReadiness ? '检查运行条件...' : '创建并执行'}
          </ActionButton>
        </div>

        <div style={{ marginLeft: 'auto', display: 'flex', gap: 10, flexWrap: 'wrap' }}>
          {[
            { label: '运行中', value: runningCount, background: 'var(--accent-soft)', color: 'var(--accent)' },
            { label: '排队', value: pendingCount, background: 'var(--panel-muted)', color: 'var(--muted-strong)' },
            { label: '已完成', value: completedCount, background: 'var(--success-soft)', color: 'var(--success)' },
          ].map((stat) => (
            <div
              key={stat.label}
              style={{
                minWidth: 88,
                padding: '10px 12px',
                borderRadius: 'var(--radius-sm)',
                background: stat.background,
              }}
            >
              <div style={{ fontSize: 11, color: 'var(--muted)' }}>{stat.label}</div>
              <div style={{ marginTop: 4, fontSize: 18, fontWeight: 700, color: stat.color }}>{stat.value}</div>
            </div>
          ))}
        </div>
      </header>

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'minmax(0, 1.45fr) minmax(280px, 360px)',
          gap: 20,
          flex: 1,
          minHeight: 0,
          padding: 20,
        }}
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: 18, minHeight: 0, overflow: 'auto', paddingRight: 4 }}>
          <Section
            title="文件队列"
            caption={selectedFiles.length === 0 ? '把音频拖进来，或点击“添加音频”' : `本次将处理 ${selectedFiles.length} 个音频文件`}
            actions={
              selectedFiles.length > 0 ? (
                <span style={{ fontSize: 12, color: 'var(--muted)' }}>{selectedFiles.length} items</span>
              ) : null
            }
          >
            <div
              onDragOver={(event) => {
                event.preventDefault()
                setDragOver(true)
              }}
              onDragLeave={() => setDragOver(false)}
              onDrop={handleDrop}
              style={{
                borderRadius: 'var(--radius-card)',
                border: `1px dashed ${dragOver ? 'var(--accent)' : 'var(--border)'}`,
                background: dragOver ? 'var(--accent-soft)' : 'var(--panel-muted)',
                padding: selectedFiles.length === 0 ? '36px 24px' : '14px',
              }}
            >
              {selectedFiles.length === 0 ? (
                <div style={{ textAlign: 'center' }}>
                  <div
                    style={{
                      width: 52,
                      height: 52,
                      borderRadius: 16,
                      margin: '0 auto 14px',
                      background: 'var(--surface)',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      color: 'var(--accent)',
                    }}
                  >
                    <UploadIcon />
                  </div>
                  <div style={{ fontSize: 15, fontWeight: 700 }}>先添加这次要处理的音频</div>
                  <div style={{ marginTop: 8, fontSize: 13, color: 'var(--muted)' }}>
                    Workbench 只关注主链路：输入、流水线、执行。
                  </div>
                </div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                  {selectedFiles.map((path) => (
                    <div
                      key={path}
                      style={{
                        display: 'grid',
                        gridTemplateColumns: 'minmax(0, 1fr) auto',
                        gap: 12,
                        alignItems: 'center',
                        padding: '12px 14px',
                        borderRadius: 'var(--radius-sm)',
                        background: 'var(--surface)',
                        border: '1px solid var(--border)',
                      }}
                    >
                      <div style={{ minWidth: 0 }}>
                        <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--fg)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                          {fileName(path)}
                        </div>
                        <div style={{ marginTop: 4, fontSize: 11, color: 'var(--muted)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                          {path}
                        </div>
                      </div>
                      <button
                        type="button"
                        onClick={() => removeFile(path)}
                        style={{
                          padding: '6px 10px',
                          borderRadius: 'var(--radius-sm)',
                          border: '1px solid var(--border)',
                          background: 'transparent',
                          color: 'var(--muted)',
                          cursor: 'pointer',
                        }}
                      >
                        移除
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </Section>

          <Section title="流水线预览" caption="让用户先看懂这次任务会经历什么">
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 12 }}>
              {stageSummary.map((stage, index) => (
                <div
                  key={stage.title}
                  style={{
                    padding: '14px 14px 12px',
                    borderRadius: 'var(--radius-sm)',
                    border: '1px solid var(--border)',
                    background: stage.enabled ? 'var(--surface)' : 'var(--panel-muted)',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                    <span
                      style={{
                        width: 26,
                        height: 26,
                        borderRadius: 999,
                        background: stage.enabled ? 'var(--accent-soft)' : 'var(--surface)',
                        color: stage.enabled ? 'var(--accent)' : 'var(--muted)',
                        display: 'inline-flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        fontSize: 12,
                        fontWeight: 700,
                      }}
                    >
                      {index + 1}
                    </span>
                    <div>
                      <div style={{ fontSize: 13, fontWeight: 700 }}>{stage.title}</div>
                      <div style={{ marginTop: 3, fontSize: 11, color: stage.enabled ? 'var(--muted)' : 'var(--warning)' }}>
                        {stage.enabled ? '启用' : '已降级/跳过'}
                      </div>
                    </div>
                  </div>
                  <div style={{ marginTop: 12, fontSize: 12, color: 'var(--muted)' }}>{stage.detail}</div>
                </div>
              ))}
            </div>
          </Section>

          <Section title="常用参数" caption="只保留会影响主链路判断的配置" open={commonExpanded} onToggle={toggleCommon}>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 16 }}>
              <SelectField
                title="源语言"
                value={params.sourceLang}
                options={LANG_OPTIONS}
                onChange={(value) => updateParam('sourceLang', value)}
              />
              <SelectField
                title="目标语言"
                value={params.targetLang}
                options={LANG_OPTIONS}
                onChange={(value) => updateParam('targetLang', value)}
              />
              <ToggleField
                title="人声分离"
                hint="开启后会先做 vocal separation"
                checked={params.useVocalSeparator}
                onChange={(value) => updateParam('useVocalSeparator', value)}
              />
              <ToggleField
                title="跳过已有输出"
                hint="适合重复执行同一批文件"
                checked={params.skipExisting}
                onChange={(value) => updateParam('skipExisting', value)}
              />
            </div>
          </Section>

          <Section title="模型与引擎" caption="这些设置决定流水线每一阶段由谁来执行" open={modelExpanded} onToggle={toggleModel}>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 16 }}>
              <SelectField
                title="TTS 引擎"
                value={params.ttsEngine}
                options={ttsEngineOptions}
                onChange={(value) => updateParam('ttsEngine', value)}
              />
              <SelectField
                title="TTS 声线"
                value={params.ttsVoice}
                options={ttsVoiceOptions}
                onChange={(value) => updateParam('ttsVoice', value)}
              />
              <SelectField
                title="ASR 引擎"
                value={params.asrProvider}
                options={asrProviderOptions}
                onChange={(value) => {
                  updateParam('asrProvider', value)
                  const defaultModel = defaultModelFor('asr', value)
                  if (defaultModel) updateParam('asrModel', defaultModel)
                }}
              />
              <SelectField
                title="ASR 模型"
                value={params.asrModel}
                options={asrModelOptions}
                onChange={(value) => updateParam('asrModel', value)}
              />
              <SelectField
                title="翻译提供方"
                value={params.translateProvider}
                options={translateProviderOptions}
                onChange={(value) => updateParam('translateProvider', value)}
              />
              <SelectField
                title="分离引擎"
                value={params.vocalProvider}
                options={vocalProviderOptions}
                onChange={(value) => {
                  updateParam('vocalProvider', value)
                  const defaultModel = defaultModelFor('separator', value)
                  if (defaultModel) updateParam('vocalModel', defaultModel)
                }}
              />
              <SelectField
                title="分离模型"
                value={params.vocalModel}
                options={vocalModelOptions}
                onChange={(value) => updateParam('vocalModel', value)}
              />
            </div>
          </Section>

          <Section title="高级参数" caption="保留，但不让它们占住主操作空间" open={advExpanded} onToggle={toggleAdv}>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 18 }}>
              <RangeField
                title="语速"
                value={params.ttsSpeed}
                min={0.6}
                max={1.6}
                step={0.05}
                displayValue={`${params.ttsSpeed.toFixed(2)}x`}
                onChange={(value) => updateParam('ttsSpeed', value)}
              />
              <RangeField
                title="原声保留"
                value={params.originalVolume}
                min={0}
                max={1}
                step={0.05}
                displayValue={`${Math.round(params.originalVolume * 100)}%`}
                onChange={(value) => updateParam('originalVolume', value)}
              />
              <RangeField
                title="TTS 音量占比"
                value={params.ttsVolumeRatio}
                min={0}
                max={1}
                step={0.05}
                displayValue={`${Math.round(params.ttsVolumeRatio * 100)}%`}
                onChange={(value) => updateParam('ttsVolumeRatio', value)}
              />
              <RangeField
                title="TTS 延迟"
                value={params.ttsDelay}
                min={-2}
                max={2}
                step={0.05}
                displayValue={`${params.ttsDelay.toFixed(2)}s`}
                onChange={(value) => updateParam('ttsDelay', value)}
              />
            </div>
          </Section>
        </div>

        <aside style={{ display: 'flex', flexDirection: 'column', gap: 16, minHeight: 0, overflow: 'auto', paddingRight: 4 }}>
          <Section title="执行前确认" caption="点击执行前，先确认这次任务会发生什么">
            <div style={{ display: 'grid', gap: 14 }}>
              {capabilityError ? (
                <div style={{ padding: '12px 14px', border: '1px solid var(--error)', borderRadius: 8, color: 'var(--error)', fontSize: 12 }}>
                  {capabilityError}
                </div>
              ) : null}
              {readinessIssues.length > 0 ? (
                <div style={{ padding: '12px 14px', border: '1px solid var(--warning)', borderRadius: 8, background: 'var(--warning-soft)', fontSize: 12 }}>
                  <div style={{ fontWeight: 700, color: 'var(--fg)' }}>当前配置暂不可执行</div>
                  {readinessIssues.map((issue, index) => (
                    <div key={`${issue.stage}-${issue.code}-${index}`} style={{ marginTop: 6, color: 'var(--muted-strong)' }}>
                      {issue.stage}：{issue.message}
                    </div>
                  ))}
                  <button
                    type="button"
                    onClick={() => setPage(readinessIssues.some((issue) => issue.action === 'settings') ? 'settings' : 'engines')}
                    style={{ marginTop: 10, border: 'none', background: 'transparent', color: 'var(--accent)', padding: 0, cursor: 'pointer', fontWeight: 700 }}
                  >
                    前往处理
                  </button>
                </div>
              ) : null}
              <div
                style={{
                  padding: '14px 16px',
                  borderRadius: 'var(--radius-sm)',
                  background: 'var(--panel-muted)',
                  border: '1px solid var(--border)',
                }}
              >
                <div style={{ fontSize: 11, color: 'var(--muted)' }}>当前预设</div>
                <div style={{ marginTop: 6, fontSize: 15, fontWeight: 700 }}>
                  {currentPreset?.label || preset || '尚未选择'}
                </div>
                <div style={{ marginTop: 6, fontSize: 12, color: 'var(--muted)' }}>
                  {currentPreset?.description || '如果预设尚未完善，也可以先按下方参数直接执行。'}
                </div>
              </div>

              <div style={{ display: 'grid', gap: 10 }}>
                {[
                  { label: '输入文件', value: selectedFiles.length === 0 ? '尚未选择' : `${selectedFiles.length} 个音频` },
                  { label: '目标语言', value: optionLabel(LANG_OPTIONS, params.targetLang) },
                  { label: 'TTS 引擎', value: optionLabel(ttsEngineOptions, params.ttsEngine) },
                  { label: '翻译提供方', value: optionLabel(translateProviderOptions, params.translateProvider) },
                ].map((item) => (
                  <div
                    key={item.label}
                    style={{
                      display: 'flex',
                      justifyContent: 'space-between',
                      gap: 12,
                      padding: '11px 0',
                      borderBottom: '1px solid var(--border)',
                    }}
                  >
                    <span style={{ fontSize: 12, color: 'var(--muted)' }}>{item.label}</span>
                    <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--fg)', textAlign: 'right' }}>{item.value}</span>
                  </div>
                ))}
              </div>
            </div>
          </Section>

          <Section title="预计输出" caption="主链路优先保证成品、字幕和可预览产物">
            <div style={{ display: 'grid', gap: 10 }}>
              {outputSummary.map((item) => (
                <div
                  key={item}
                  style={{
                    padding: '12px 14px',
                    borderRadius: 'var(--radius-sm)',
                    background: 'var(--surface)',
                    border: '1px solid var(--border)',
                    fontSize: 13,
                  }}
                >
                  {item}
                </div>
              ))}
            </div>
          </Section>

          <Section
            title="最近任务"
            caption="如果已经开始跑任务，去 TaskCenter 跟踪阶段和产物"
            actions={
              <ActionButton variant="ghost" onClick={() => setPage('task-center')}>
                查看任务中心
                <ArrowIcon />
              </ActionButton>
            }
          >
            {recentTasks.length === 0 ? (
              <div style={{ fontSize: 13, color: 'var(--muted)' }}>还没有任务记录，从当前文件队列创建第一批任务即可。</div>
            ) : (
              <div style={{ display: 'grid', gap: 10 }}>
                {recentTasks.map((task) => (
                  <button
                    key={task.id}
                    type="button"
                    onClick={() => setPage('task-center')}
                    style={{
                      textAlign: 'left',
                      padding: '12px 14px',
                      borderRadius: 'var(--radius-sm)',
                      border: '1px solid var(--border)',
                      background: 'var(--surface)',
                      cursor: 'pointer',
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10 }}>
                      <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--fg)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                        {task.sourceName}
                      </span>
                      <span style={{ fontSize: 11, color: 'var(--muted)' }}>{formatRelativeTime(task.createdAt)}</span>
                    </div>
                    <div style={{ marginTop: 6, display: 'flex', alignItems: 'center', gap: 8 }}>
                      <span
                        style={{
                          padding: '3px 8px',
                          borderRadius: 999,
                          fontSize: 11,
                          fontWeight: 700,
                          background: task.status === 'completed' ? 'var(--success-soft)' : task.status === 'failed' ? 'var(--error-soft)' : 'var(--accent-soft)',
                          color: task.status === 'completed' ? 'var(--success)' : task.status === 'failed' ? 'var(--error)' : 'var(--accent)',
                        }}
                      >
                        {STATUS_LABELS[task.status]}
                      </span>
                      <span style={{ fontSize: 12, color: 'var(--muted)' }}>
                        {task.message || '等待更多状态信息'}
                      </span>
                    </div>
                  </button>
                ))}
              </div>
            )}
          </Section>

          <Section title="预设阶段说明" caption="如果预设提供了阶段描述，优先用它做评审">
            {currentPreset?.stages?.length ? (
              <div style={{ display: 'grid', gap: 10 }}>
                {currentPreset.stages.map((stage) => (
                  <div
                    key={stage}
                    style={{
                      padding: '10px 12px',
                      borderRadius: 'var(--radius-sm)',
                      background: 'var(--panel-muted)',
                      fontSize: 12,
                      color: 'var(--fg)',
                    }}
                  >
                    {stage}
                  </div>
                ))}
              </div>
            ) : (
              <div style={{ fontSize: 13, color: 'var(--muted)' }}>
                当前预设没有额外阶段说明，以上方“流水线预览”为准。
              </div>
            )}
          </Section>
        </aside>
      </div>
    </div>
  )
}
