import { useCallback, useEffect, useRef, useState } from 'react'
import type { CSSProperties, DragEvent, ReactNode } from 'react'

import { pipelineApi } from '@/api/pipeline'
import { capabilitiesApi } from '@/api/engines'
import { resourcesApi } from '@/api/resources'
import { ttsApi } from '@/api/tts'
import { voiceApi } from '@/api/voice'
import type {
  CapabilityDescriptorResponse,
  CapabilityOptionResponse,
  PipelineExecutionProfileRequest,
  PipelineRunRequest,
  TaskReadinessIssueResponse,
  TtsVoiceItemResponse,
  VoiceProfileSummaryResponse,
} from '@/api/types'
import { FILE_FILTERS, useFileSelector } from '@/hooks/useFileSelector'
import { useTaskPolling } from '@/hooks/useTaskPolling'
import {
  PIPELINE_STAGE_IDS,
  PIPELINE_STAGE_LABELS,
  normalizePresetStages,
} from '@/domain/pipelinePreset'
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

const WORKBENCH_LAYOUT_STYLES = `
  .workbench-page {
    display: flex;
    flex-direction: column;
    height: 100%;
    min-height: 0;
    overflow: hidden;
  }

  .workbench-header {
    padding: 22px 28px 18px;
    border-bottom: 1px solid var(--border);
    background: var(--surface);
    display: grid;
    grid-template-columns: minmax(260px, 1fr) minmax(0, 640px);
    grid-template-areas:
      "copy actions"
      "copy stats";
    column-gap: 24px;
    row-gap: 12px;
    align-items: flex-start;
  }

  .workbench-header-copy {
    grid-area: copy;
    min-width: 0;
  }

  .workbench-header-actions {
    grid-area: actions;
    display: flex;
    gap: 10px;
    flex-wrap: wrap;
    align-items: center;
    justify-content: flex-end;
    min-width: 0;
  }

  .workbench-header-preset {
    flex: 0 1 240px;
    min-width: 210px;
  }

  .workbench-stats {
    grid-area: stats;
    width: min(100%, 340px);
    justify-self: end;
    display: grid;
    grid-template-columns: repeat(3, minmax(88px, 1fr));
    gap: 10px;
  }

  .workbench-content {
    display: grid;
    grid-template-columns: minmax(0, 1.45fr) minmax(280px, 360px);
    gap: 20px;
    flex: 1;
    min-height: 0;
    padding: 20px;
  }

  .workbench-main-column,
  .workbench-side-column {
    display: flex;
    flex-direction: column;
    min-width: 0;
    min-height: 0;
    overflow: auto;
    padding-right: 4px;
  }

  .workbench-main-column {
    gap: 18px;
  }

  .workbench-side-column {
    gap: 16px;
  }

  .workbench-main-column > *,
  .workbench-side-column > * {
    flex: 0 0 auto;
  }

  .workbench-section-header {
    flex-wrap: wrap;
    justify-content: space-between;
  }

  .workbench-section-heading {
    flex: 1 1 220px;
    min-width: 0;
  }

  .workbench-section-actions {
    display: flex;
    flex: 0 1 auto;
    min-width: 0;
  }

  .workbench-action-button {
    justify-content: center;
    white-space: nowrap;
  }

  .workbench-break-anywhere {
    overflow-wrap: anywhere;
    word-break: break-word;
  }

  .workbench-pipeline-scroll {
    overflow-x: auto;
    padding-bottom: 4px;
  }

  .workbench-pipeline-track {
    display: grid;
    grid-template-columns: repeat(6, minmax(126px, 1fr));
    gap: 10px;
    min-width: 790px;
  }

  @media (max-width: 1100px) {
    .workbench-page {
      overflow: auto;
    }

    .workbench-header {
      grid-template-columns: minmax(0, 1fr);
      grid-template-areas:
        "copy"
        "actions"
        "stats";
    }

    .workbench-header-actions {
      justify-content: flex-start;
    }

    .workbench-stats {
      width: 100%;
      justify-self: stretch;
      grid-template-columns: repeat(3, minmax(0, 1fr));
    }

    .workbench-content {
      grid-template-columns: minmax(0, 1fr);
      flex: none;
      min-height: auto;
      padding: 16px;
    }

    .workbench-main-column,
    .workbench-side-column {
      overflow: visible;
      padding-right: 0;
    }
  }

  @media (max-width: 680px) {
    .workbench-header {
      padding: 18px 16px 14px;
      gap: 14px;
    }

    .workbench-header-copy {
      flex-basis: 100%;
      min-width: 0;
    }

    .workbench-header-actions {
      width: 100%;
    }

    .workbench-header-actions > button {
      flex: 1 1 140px;
    }

    .workbench-header-preset {
      flex: 1 1 180px;
      min-width: 0;
    }

    .workbench-stats {
      gap: 8px;
    }

    .workbench-stats > div {
      min-width: 0 !important;
      padding: 9px 10px !important;
    }

    .workbench-content {
      gap: 14px;
      padding: 12px;
    }

    .workbench-section-header,
    .workbench-section-body {
      padding: 14px !important;
    }

    .workbench-section-actions {
      flex: 1 1 100%;
    }

    .workbench-section-actions > button {
      width: 100%;
    }
  }
`

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

const WORKBENCH_AUDIO_EXTENSIONS = new Set(
  FILE_FILTERS.audio.extensions.map((extension) => extension.toLowerCase()),
)

function partitionAudioPaths(paths: string[]) {
  const accepted: string[] = []
  const rejected: string[] = []

  paths.forEach((path) => {
    const name = fileName(path).toLowerCase()
    const extension = name.includes('.') ? name.slice(name.lastIndexOf('.') + 1) : ''
    if (WORKBENCH_AUDIO_EXTENSIONS.has(extension)) {
      accepted.push(path)
    } else {
      rejected.push(path)
    }
  })

  return { accepted, rejected }
}

function unsupportedAudioMessage(paths: string[]) {
  if (paths.length === 0) return ''
  const examples = paths.slice(0, 3).map(fileName).join('、')
  const remainder = paths.length > 3 ? ` 等 ${paths.length} 个文件` : ''
  const formats = FILE_FILTERS.audio.extensions.map((extension) => extension.toUpperCase()).join('、')
  return `只接受 ${formats} 音频；已忽略 ${examples}${remainder}`
}

function optionLabel(options: Option[], value: string) {
  return options.find((item) => item.value === value)?.label ?? value
}

function capabilityScope(
  category: string,
  provider: string,
  schema: 'common' | 'provider',
) {
  return `${category}/${provider}/${schema}`
}

function optionPayload(
  descriptor: CapabilityDescriptorResponse | undefined,
  schema: 'common' | 'provider',
  values: Record<string, Record<string, unknown>>,
) {
  if (!descriptor) return {}
  const scope = capabilityScope(descriptor.category, descriptor.provider, schema)
  const current = values[scope] ?? {}
  const definitions = schema === 'common'
    ? descriptor.common_option_schema
    : descriptor.provider_option_schema

  return Object.fromEntries(
    definitions.flatMap((option) => {
      const value = current[option.name] ?? option.default
      return value === null || value === undefined || value === ''
        ? []
        : [[option.name, value]]
    }),
  )
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
        className="workbench-section-header"
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
            className="workbench-section-heading"
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
          <div className="workbench-section-heading" style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <div>
              <div style={{ fontSize: 14, fontWeight: 600 }}>{title}</div>
              {caption ? <div style={{ fontSize: 12, color: 'var(--muted)' }}>{caption}</div> : null}
            </div>
          </div>
        )}
        {actions ? <div className="workbench-section-actions">{actions}</div> : null}
      </div>
      {open ? <div className="workbench-section-body" style={{ padding: 18 }}>{children}</div> : null}
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
      className={`workbench-action-button workbench-action-button--${variant}`}
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
    <div style={{ minHeight: 34, marginBottom: 8 }}>
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

interface CapabilityOptionPresentation {
  label: string
  hint: string
  placeholder?: string
}

const CAPABILITY_OPTION_PRESENTATIONS: Record<string, CapabilityOptionPresentation> = {
  proxy: { label: '网络代理', hint: '可选；仅在当前网络需要代理时填写', placeholder: '留空时直接连接' },
  vad_filter: { label: 'VAD 语音过滤', hint: '过滤静音和非语音片段；默认关闭' },
  disable_vad: { label: '禁用 VAD', hint: '关闭语音活动检测' },
  beam_size: { label: '解码搜索宽度', hint: '数值越大识别更稳但更慢；默认 5' },
  initial_prompt: { label: '识别上下文提示', hint: '可选；用于补充人名或专有词', placeholder: '留空时不追加上下文提示' },
  no_speech_threshold: { label: '无语音阈值', hint: '判断片段没有语音的概率阈值；默认 0.9' },
  emotion: { label: '情绪提示', hint: '可选；描述希望合成语音表达的情绪', placeholder: '留空时使用声线默认表达' },
  temperature: { label: '生成随机度', hint: '数值越高变化越丰富；留空时由引擎决定' },
  device_map: { label: '运行设备', hint: '模型加载设备；通常保持默认值' },
  device: { label: '运行设备', hint: '推理设备；auto 会自动选择' },
  dtype: { label: '计算精度', hint: '模型计算精度；通常保持默认值' },
  batch_size: { label: '批处理大小', hint: '单次处理数量；显存不足时请减小' },
  sentence_timestamp: { label: '句级时间戳', hint: '为识别结果生成句子级时间信息' },
  trust_remote_code: { label: '允许模型自定义代码', hint: '允许加载模型随附的运行代码' },
  remote_code_path: { label: '本地模型代码路径', hint: '可选；仅用于指定本地 FunASR 模型代码', placeholder: '留空时使用模型默认实现' },
  vad_model: { label: 'VAD 模型', hint: '可选；指定语音活动检测模型', placeholder: '留空时使用默认 VAD 模型' },
  hub: { label: '模型来源', hint: 'hf 为 Hugging Face，ms 为 ModelScope' },
  attn_implementation: { label: '注意力实现', hint: '可选；仅在已安装对应加速组件时指定', placeholder: '留空时由模型自动选择' },
  max_inference_batch_size: { label: '最大推理批量', hint: '离线推理的批量上限；默认 1' },
  max_new_tokens: { label: '最大生成长度', hint: '长音频解码可生成的最大 Token 数' },
  forced_aligner: { label: '强制对齐模型', hint: '可选；用于生成更精细的时间戳', placeholder: '留空时不启用强制对齐' },
  return_time_stamps: { label: '返回对齐时间戳', hint: '在引擎支持时返回对齐后的时间信息' },
  context: { label: '识别上下文', hint: '可选；给识别模型补充文本上下文', placeholder: '留空时不追加上下文' },
  model_dir: { label: '模型目录', hint: '可选；本地目录或模型仓库标识', placeholder: '留空时使用官方默认模型' },
  cfg_value: { label: '引导强度', hint: '控制合成结果遵循提示的程度；默认 2' },
  inference_timesteps: { label: '推理步数', hint: '步数越高质量越好但速度越慢；10 快速，20 高质量' },
  load_denoiser: { label: '加载降噪器', hint: '提高输出纯净度，但会增加资源占用' },
  reference_wav_path: { label: '参考音频路径', hint: '可选；用于复刻参考声线', placeholder: '留空时不使用参考音频' },
  prompt_wav_path: { label: '提示音频路径', hint: '可选；用于高保真音色复刻', placeholder: '留空时不使用提示音频' },
  prompt_text: { label: '提示音频文本', hint: '可选；填写提示音频对应的准确文本', placeholder: '留空时不提供提示文本' },
}

function CapabilityOptionField({
  option,
  context,
  value,
  onChange,
}: {
  option: CapabilityOptionResponse
  context: string
  value: unknown
  onChange: (value: unknown) => void
}) {
  if (option.secret || option.type === 'array' || option.type === 'object') return null

  const presentation = CAPABILITY_OPTION_PRESENTATIONS[option.name] ?? {
    label: '扩展参数',
    hint: '由当前引擎提供的可选配置',
  }
  const title = `${context} · ${presentation.label}`
  const hint = presentation.hint

  if (option.type === 'boolean') {
    return (
      <ToggleField
        title={title}
        hint={hint}
        checked={Boolean(value)}
        onChange={onChange}
      />
    )
  }

  if (option.enum.length > 0) {
    return (
      <SelectField
        title={title}
        hint={hint}
        value={String(value ?? '')}
        options={option.enum.map((item) => ({ value: String(item), label: String(item) }))}
        onChange={onChange}
      />
    )
  }

  if (option.type === 'number' || option.type === 'integer') {
    return (
      <div>
        <FieldLabel title={title} hint={hint} />
        <input
          type="number"
          value={value === null || value === undefined ? '' : String(value)}
          min={option.min ?? undefined}
          max={option.max ?? undefined}
          step={option.type === 'integer' ? 1 : 'any'}
          placeholder={presentation.placeholder}
          onChange={(event) => {
            const raw = event.target.value
            onChange(raw === '' ? null : Number(raw))
          }}
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
        />
      </div>
    )
  }

  return (
    <div>
      <FieldLabel title={title} hint={hint} />
      <input
        type="text"
        value={String(value ?? '')}
        placeholder={presentation.placeholder}
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
      />
    </div>
  )
}

export default function Workbench() {
  useTaskPolling(3000)

  const {
    selectedFiles,
    preset,
    presets,
    presetsLoading,
    params,
    capabilityOptions,
    commonExpanded,
    modelExpanded,
    advExpanded,
    setFiles,
    removeFile,
    setPreset,
    setPresets,
    setPresetsLoading,
    updateParam,
    updateCapabilityOption,
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
  const [fileSelectionError, setFileSelectionError] = useState('')
  const [capabilities, setCapabilities] = useState<CapabilityDescriptorResponse[]>([])
  const [capabilityError, setCapabilityError] = useState('')
  const [ttsVoices, setTtsVoices] = useState<TtsVoiceItemResponse[]>([])
  const [ttsVoiceError, setTtsVoiceError] = useState('')
  const [voiceProfiles, setVoiceProfiles] = useState<VoiceProfileSummaryResponse[]>([])
  const [readinessIssues, setReadinessIssues] = useState<TaskReadinessIssueResponse[]>([])
  const [checkingReadiness, setCheckingReadiness] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [presetError, setPresetError] = useState('')
  const [presetReloadToken, setPresetReloadToken] = useState(0)
  const submitLockRef = useRef(false)
  const currentPreset = presets.find((item) => item.id === preset) ?? null
  const activePresetStages = normalizePresetStages(currentPreset?.stages ?? [])
  const stageFlags = {
    separate: activePresetStages.has('separate') && params.useVocalSeparator,
    asr: activePresetStages.has('asr'),
    translate: activePresetStages.has('translate') && params.sourceLang !== params.targetLang,
    tts: activePresetStages.has('tts'),
    mix: activePresetStages.has('mix'),
    export: activePresetStages.has('export'),
  }

  useEffect(() => {
    let cancelled = false
    let retryTimer: number | undefined

    const loadPresets = () => {
      setPresetsLoading(true)
      pipelineApi.presets().then((response) => {
        if (cancelled) return
        setPresets(response.presets)
        const currentPresetId = useWorkbenchStore.getState().preset
        const presetStillExists = response.presets.some((item) => item.id === currentPresetId)
        if (!presetStillExists) {
          setPreset(response.presets[0]?.id ?? '')
        }
        setPresetError(response.presets.length > 0 ? '' : '没有可用的内置预设')
        setPresetsLoading(false)
      }).catch((error) => {
        if (cancelled) return
        setPresetError(`预设加载失败：${error instanceof Error ? error.message : String(error)}`)
        setPresetsLoading(false)
        retryTimer = window.setTimeout(loadPresets, 2000)
      })
    }

    loadPresets()
    return () => {
      cancelled = true
      if (retryTimer !== undefined) window.clearTimeout(retryTimer)
      setPresetsLoading(false)
    }
  }, [presetReloadToken, setPreset, setPresets, setPresetsLoading])

  useEffect(() => {
    let cancelled = false
    let retryTimer: number | undefined

    const loadCapabilities = () => {
      capabilitiesApi.list().then((items) => {
        if (cancelled) return
        setCapabilities(items)
        setCapabilityError('')
      }).catch((error) => {
        if (cancelled) return
        setCapabilities([])
        setCapabilityError(`能力目录加载失败：${error instanceof Error ? error.message : String(error)}`)
        retryTimer = window.setTimeout(loadCapabilities, 2000)
      })
    }

    loadCapabilities()
    return () => {
      cancelled = true
      if (retryTimer !== undefined) window.clearTimeout(retryTimer)
    }
  }, [])

  useEffect(() => {
    if (!stageFlags.tts) {
      setTtsVoices([])
      setTtsVoiceError('')
      return
    }
    let cancelled = false
    ttsApi
      .listVoices(params.ttsEngine)
      .then((response) => {
        if (cancelled) return
        setTtsVoices(response.voices)
        setTtsVoiceError('')

        const currentVoice = useWorkbenchStore.getState().params.ttsVoice
        if (!response.voices.some((voice) => voice.id === currentVoice)) {
          const descriptor = capabilities.find(
            (item) => item.category === 'tts' && item.provider === params.ttsEngine,
          )
          const declaredDefault = descriptor?.common_option_schema
            .find((option) => option.name === 'voice')?.default
          const nextVoice = response.voices.find(
            (voice) => voice.id === declaredDefault,
          )?.id ?? response.voices[0]?.id
          if (nextVoice) updateParam('ttsVoice', nextVoice)
        }
      })
      .catch((error) => {
        if (cancelled) return
        setTtsVoices([])
        setTtsVoiceError(`音色列表加载失败：${error instanceof Error ? error.message : String(error)}`)
      })
    return () => {
      cancelled = true
    }
  }, [stageFlags.tts, params.ttsEngine, capabilities, updateParam])

  useEffect(() => {
    if (!stageFlags.tts) {
      setVoiceProfiles([])
      return
    }
    let cancelled = false
    voiceApi
      .listProfiles()
      .then((profiles) => {
        if (cancelled) return
        setVoiceProfiles(profiles)
        const availableProfileIds = new Set(
          profiles
            .filter((profile) => profile.available && profile.engine.startsWith('qwen3'))
            .map((profile) => profile.id),
        )
        const currentProfileId = useWorkbenchStore.getState().params.voiceProfileId
        if (currentProfileId && !availableProfileIds.has(currentProfileId)) {
          updateParam('voiceProfileId', null)
        }
      })
      .catch(() => {
        if (!cancelled) setVoiceProfiles([])
      })
    return () => {
      cancelled = true
    }
  }, [stageFlags.tts, updateParam])

  useEffect(() => {
    setReadinessIssues([])
  }, [preset, params, capabilityOptions, selectedFiles])

  const runningCount = tasks.filter((task) => task.status === 'running').length
  const pendingCount = tasks.filter((task) => task.status === 'pending').length
  const completedCount = tasks.filter((task) => task.status === 'completed').length
  const recentTasks = tasks.slice(-5).reverse()

  const appendFiles = useCallback((files: string[]) => {
    if (files.length === 0) return
    const currentFiles = useWorkbenchStore.getState().selectedFiles
    setFiles(mergeUniquePaths(currentFiles, files))
  }, [setFiles])

  const handleSelectFiles = useCallback(async () => {
    setFileSelectionError('')
    const files = await selectFiles({ filters: [FILE_FILTERS.audio] })
    const { accepted, rejected } = partitionAudioPaths(files)
    setFileSelectionError(unsupportedAudioMessage(rejected))
    appendFiles(accepted)
  }, [appendFiles, selectFiles])

  const handleDrop = useCallback((event: DragEvent<HTMLDivElement>) => {
    event.preventDefault()
    setDragOver(false)

    const dropped = Array.from(event.dataTransfer.files)
    if (dropped.length === 0) return

    const paths = dropped.map((file) => (file as File & { path?: string }).path || file.name)
    const { accepted, rejected } = partitionAudioPaths(paths)
    setFileSelectionError(unsupportedAudioMessage(rejected))
    if (accepted.length === 0) return

    const missingFullPath = accepted.some((path) => !path.includes('/') && !path.includes('\\'))

    if (!missingFullPath) {
      appendFiles(accepted)
      return
    }

    const missingNames = accepted.filter((path) => !path.includes('/') && !path.includes('\\'))
    const dir = prompt(
      '浏览器模式无法获取完整路径。请输入文件所在目录：\n' + `（文件：${missingNames.join(', ')}）`,
      'D:\\Asmr',
    )

    if (!dir) return

    const sep = dir.includes('/') ? '/' : '\\'
    const fullPaths = accepted.map((path) => (
      path.includes('/') || path.includes('\\') ? path : `${dir}${sep}${path}`
    ))
    appendFiles(fullPaths)
  }, [appendFiles])

  const handleExecute = async () => {
    if (selectedFiles.length === 0 || !currentPreset || submitLockRef.current) return

    submitLockRef.current = true
    setSubmitting(true)
    try {

    const asrDescriptor = capabilities.find(
      (item) => item.category === 'asr' && item.provider === params.asrProvider,
    )
    const llmDescriptor = capabilities.find(
      (item) => item.category === 'llm' && item.provider === params.translateProvider,
    )
    const ttsDescriptor = capabilities.find(
      (item) => item.category === 'tts' && item.provider === params.ttsEngine,
    )
    const asrProviderOptions = stageFlags.asr
      ? optionPayload(asrDescriptor, 'provider', capabilityOptions)
      : {}
    const llmCommonOptions = stageFlags.translate
      ? optionPayload(llmDescriptor, 'common', capabilityOptions)
      : {}
    const ttsProviderOptions = stageFlags.tts
      ? optionPayload(ttsDescriptor, 'provider', capabilityOptions)
      : {}
    if (params.voiceProfileId) {
      ttsProviderOptions.voice_profile_id = params.voiceProfileId
    } else {
      delete ttsProviderOptions.voice_profile_id
    }

    const executionProfile: PipelineExecutionProfileRequest = {
      version: 1,
      source_lang: params.sourceLang,
      target_lang: params.targetLang,
      skip_existing: params.skipExisting,
      stages: {
        separate: {
          enabled: stageFlags.separate,
          provider: params.vocalProvider,
          model: params.vocalModel,
          options: { mode: 'vocals' },
          provider_options: {},
        },
        asr: {
          enabled: stageFlags.asr,
          provider: params.asrProvider,
          model: params.asrModel,
          options: {
            language: params.sourceLang,
            output_format: 'segments',
            timestamps: true,
          },
          provider_options: asrProviderOptions,
        },
        translate: {
          enabled: stageFlags.translate,
          provider: params.translateProvider,
          model: params.translateModel || llmDescriptor?.default_model || null,
          options: {
            source_lang: params.sourceLang,
            target_lang: params.targetLang,
            preserve_timestamps: true,
            ...llmCommonOptions,
          },
          provider_options: {},
        },
        tts: {
          enabled: stageFlags.tts,
          provider: params.ttsEngine,
          model: ttsDescriptor?.default_model || null,
          options: {
            voice: params.ttsVoice,
            speed: params.ttsSpeed,
            language: params.targetLang,
          },
          provider_options: ttsProviderOptions,
        },
        mix: {
          enabled: stageFlags.mix,
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
          enabled: stageFlags.export,
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
      const issues: TaskReadinessIssueResponse[] = []
      for (const filePath of selectedFiles) {
        const readiness = await resourcesApi.checkTaskReadiness(
          'pipeline',
          executionProfile,
          filePath,
        )
        if (!readiness.ready) {
          issues.push(...readiness.issues)
        }
      }
      if (issues.length > 0) {
        setReadinessIssues(issues)
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
          preset_id: currentPreset.id,
          source_lang: params.sourceLang,
          target_lang: params.targetLang,
          use_vocal_separator: stageFlags.separate,
          tts_engine: params.ttsEngine,
          tts_voice: params.ttsVoice,
          vocal_model: params.vocalModel,
          asr_model: params.asrModel,
          translate_provider: params.translateProvider,
          translate_model: params.translateModel,
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
    } finally {
      submitLockRef.current = false
      setSubmitting(false)
    }
  }

  const presetOptions = presets.length > 0
    ? presets.map((item) => ({ value: item.id, label: item.label || item.id }))
    : [{
        value: '',
        label: presetsLoading ? '加载预设中...' : presetError ? '预设加载失败' : '没有可用预设',
      }]

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
  const translateModelOptions = modelsFor('llm', params.translateProvider, [])
  const asrProviderOptions = providerOptions('asr', [{ value: 'faster_whisper', label: 'faster-whisper' }])
  const asrModelOptions = modelsFor('asr', params.asrProvider, ASR_MODEL_OPTIONS)
  const vocalProviderOptions = providerOptions('separator', [{ value: 'demucs', label: 'Demucs' }])
  const vocalModelOptions = modelsFor('separator', params.vocalProvider, VOCAL_MODEL_OPTIONS)

  const fallbackTtsVoiceOptions = params.ttsEngine === 'qwen3'
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
  const ttsVoiceOptions = ttsVoices.length > 0
    ? ttsVoices.map((voice) => ({
        value: voice.id,
        label: `${voice.name}${voice.language ? ` · ${voice.language}` : ''}`,
      }))
    : fallbackTtsVoiceOptions

  const selectedDescriptors = [
    stageFlags.asr
      ? capabilities.find((item) => item.category === 'asr' && item.provider === params.asrProvider)
      : undefined,
    stageFlags.translate
      ? capabilities.find((item) => item.category === 'llm' && item.provider === params.translateProvider)
      : undefined,
    stageFlags.tts
      ? capabilities.find((item) => item.category === 'tts' && item.provider === params.ttsEngine)
      : undefined,
  ].filter((item): item is CapabilityDescriptorResponse => Boolean(item))

  const dynamicCapabilityOptions = selectedDescriptors.flatMap((descriptor) => {
    const schemas: Array<['common' | 'provider', CapabilityOptionResponse[]]> = [
      ['common', descriptor.common_option_schema],
      ['provider', descriptor.provider_option_schema],
    ]
    return schemas.flatMap(([schema, options]) => options
      .filter((option) => !['language', 'voice', 'speed', 'voice_profile_id'].includes(option.name))
      .map((option) => ({
        descriptor,
        option,
        scope: capabilityScope(descriptor.category, descriptor.provider, schema),
      })))
  })

  const availableVoiceProfiles = voiceProfiles.filter(
    (profile) => profile.available && profile.engine.startsWith('qwen3'),
  )

  const stageDetails = {
    separate: activePresetStages.has('separate')
      ? (params.useVocalSeparator ? `模型：${params.vocalModel}` : '已由参数关闭')
      : '当前预设不执行',
    asr: stageFlags.asr ? `模型：${params.asrModel}` : '当前预设不执行',
    translate: activePresetStages.has('translate')
      ? (stageFlags.translate
          ? `${optionLabel(LANG_OPTIONS, params.sourceLang)} → ${optionLabel(LANG_OPTIONS, params.targetLang)}`
          : '源语言与目标语言相同，自动跳过')
      : '当前预设不执行',
    tts: stageFlags.tts ? `${params.ttsEngine} · ${params.ttsVoice}` : '当前预设不执行',
    mix: stageFlags.mix
      ? `原声 ${Math.round(params.originalVolume * 100)}% · 配音 ${Math.round(params.ttsVolumeRatio * 100)}%`
      : '当前预设不执行',
    export: stageFlags.export ? '导出 SRT 字幕与文本结果' : '当前预设不执行',
  }
  const stageSummary = PIPELINE_STAGE_IDS.map((id) => ({
    id,
    title: PIPELINE_STAGE_LABELS[id],
    enabled: stageFlags[id],
    detail: stageDetails[id],
  }))

  const outputSummary = [
    ...(stageFlags.mix ? ['混音成品音频'] : []),
    ...(stageFlags.export ? ['SRT 字幕与识别文本'] : []),
    ...(stageFlags.tts ? ['语音合成中间音轨'] : []),
    ...(stageFlags.separate ? ['分离人声中间产物'] : []),
  ]
  const confirmationSummary = [
    { label: '输入文件', value: selectedFiles.length === 0 ? '尚未选择' : `${selectedFiles.length} 个音频` },
    {
      label: '执行阶段',
      value: stageSummary.filter((stage) => stage.enabled).map((stage) => stage.title).join(' → ') || '没有可执行阶段',
    },
    ...(stageFlags.translate
      ? [{ label: '目标语言', value: optionLabel(LANG_OPTIONS, params.targetLang) }]
      : []),
    ...(stageFlags.tts
      ? [{ label: '语音合成', value: optionLabel(ttsEngineOptions, params.ttsEngine) }]
      : []),
    ...(stageFlags.translate
      ? [{ label: '翻译提供方', value: optionLabel(translateProviderOptions, params.translateProvider) }]
      : []),
  ]

  return (
    <div className="workbench-page">
      <style>{WORKBENCH_LAYOUT_STYLES}</style>
      <header className="workbench-header">
        <div className="workbench-header-copy">
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

        <div className="workbench-header-actions">
          <div className="workbench-header-preset">
            <select
              value={preset}
              onChange={(event) => setPreset(event.target.value)}
              disabled={presets.length === 0 || submitting}
              aria-label="处理预设"
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
          <ActionButton variant="ghost" disabled={selectedFiles.length === 0 || submitting} onClick={() => setFiles([])}>
            清空列表
          </ActionButton>
          <ActionButton
            variant="primary"
            disabled={selectedFiles.length === 0 || submitting || !!capabilityError || !currentPreset}
            onClick={handleExecute}
          >
            <PlayIcon />
            {checkingReadiness ? '检查运行条件...' : submitting ? '正在创建任务...' : '创建并执行'}
          </ActionButton>
        </div>

        <div className="workbench-stats">
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

      <div className="workbench-content">
        <div className="workbench-main-column" inert={submitting} aria-busy={submitting}>
          <Section
            title="文件队列"
            caption={selectedFiles.length === 0 ? '点击下方区域选择音频，也可以直接拖入' : `本次将处理 ${selectedFiles.length} 个音频文件`}
            actions={
              selectedFiles.length > 0 ? (
                <span style={{ fontSize: 12, color: 'var(--muted)' }}>{selectedFiles.length} items</span>
              ) : null
            }
          >
            {fileSelectionError ? (
              <div
                role="alert"
                style={{
                  marginBottom: 12,
                  padding: '9px 12px',
                  borderRadius: 'var(--radius-sm)',
                  border: '1px solid var(--error)',
                  background: 'var(--error-soft)',
                  color: 'var(--error)',
                  fontSize: 12,
                  lineHeight: 1.5,
                }}
              >
                {fileSelectionError}
              </div>
            ) : null}
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
                padding: selectedFiles.length === 0 ? 0 : '14px',
              }}
            >
              {selectedFiles.length === 0 ? (
                <button
                  type="button"
                  disabled={submitting}
                  onClick={handleSelectFiles}
                  aria-label="选择要处理的音频文件"
                  style={{
                    width: '100%',
                    padding: '36px 24px',
                    border: 0,
                    borderRadius: 'inherit',
                    background: 'transparent',
                    color: 'inherit',
                    font: 'inherit',
                    textAlign: 'center',
                    cursor: submitting ? 'default' : 'pointer',
                  }}
                >
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
                    点击选择文件，或把音频拖到这里。
                  </div>
                </button>
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
                  <button
                    type="button"
                    disabled={submitting}
                    onClick={handleSelectFiles}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      gap: 8,
                      width: '100%',
                      padding: '10px 14px',
                      borderRadius: 'var(--radius-sm)',
                      border: '1px dashed var(--border)',
                      background: 'transparent',
                      color: 'var(--accent)',
                      font: 'inherit',
                      fontSize: 13,
                      fontWeight: 600,
                      cursor: submitting ? 'default' : 'pointer',
                    }}
                  >
                    <UploadIcon />
                    继续添加音频
                  </button>
                </div>
              )}
            </div>
          </Section>

          <Section title="流水线预览" caption="预览、运行条件检查和实际任务使用同一套阶段配置">
            <div className="workbench-pipeline-scroll">
              <div className="workbench-pipeline-track">
              {stageSummary.map((stage, index) => (
                <div
                  key={stage.id}
                  style={{
                    minHeight: 126,
                    padding: '13px 12px 12px',
                    borderRadius: 'var(--radius-sm)',
                    border: '1px solid var(--border)',
                    background: stage.enabled ? 'var(--surface)' : 'var(--panel-muted)',
                    opacity: stage.enabled ? 1 : 0.72,
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
                        {stage.enabled ? '本次执行' : '本次跳过'}
                      </div>
                    </div>
                  </div>
                  <div style={{ marginTop: 12, fontSize: 12, color: 'var(--muted)' }}>{stage.detail}</div>
                </div>
              ))}
              </div>
            </div>
          </Section>

          <Section title="基础参数" caption="直接影响本次处理结果的常用设置" open={commonExpanded} onToggle={toggleCommon}>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 220px), 1fr))', gap: 16 }}>
              <SelectField
                title="源语言"
                value={params.sourceLang}
                options={LANG_OPTIONS}
                onChange={(value) => updateParam('sourceLang', value)}
              />
              {activePresetStages.has('translate') || activePresetStages.has('tts') ? (
                <SelectField
                  title="目标语言"
                  value={params.targetLang}
                  options={LANG_OPTIONS}
                  onChange={(value) => updateParam('targetLang', value)}
                />
              ) : null}
              {activePresetStages.has('separate') ? (
                <ToggleField
                  title="人声分离"
                  hint="关闭后直接使用原始音频进行识别"
                  checked={params.useVocalSeparator}
                  onChange={(value) => updateParam('useVocalSeparator', value)}
                />
              ) : null}
              <ToggleField
                title="跳过已有输出"
                hint="适合重复执行同一批文件"
                checked={params.skipExisting}
                onChange={(value) => updateParam('skipExisting', value)}
              />
              {stageFlags.tts ? (
                <RangeField
                  title="语速"
                  value={params.ttsSpeed}
                  min={0.6}
                  max={1.6}
                  step={0.05}
                  displayValue={`${params.ttsSpeed.toFixed(2)}x`}
                  onChange={(value) => updateParam('ttsSpeed', value)}
                />
              ) : null}
              {stageFlags.mix ? (
                <>
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
                    title="配音音量占比"
                    value={params.ttsVolumeRatio}
                    min={0}
                    max={1}
                    step={0.05}
                    displayValue={`${Math.round(params.ttsVolumeRatio * 100)}%`}
                    onChange={(value) => updateParam('ttsVolumeRatio', value)}
                  />
                  <RangeField
                    title="配音延迟"
                    value={params.ttsDelay}
                    min={-2}
                    max={2}
                    step={0.05}
                    displayValue={`${params.ttsDelay.toFixed(2)}s`}
                    onChange={(value) => updateParam('ttsDelay', value)}
                  />
                </>
              ) : null}
            </div>
          </Section>

          <Section title="模型与引擎" caption="这些设置决定流水线每一阶段由谁来执行" open={modelExpanded} onToggle={toggleModel}>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 220px), 1fr))', gap: 16 }}>
              {stageFlags.tts ? (
                <>
                  <SelectField
                    title="TTS 引擎"
                    value={params.ttsEngine}
                    options={ttsEngineOptions}
                    onChange={(value) => {
                      updateParam('ttsEngine', value)
                      updateParam('voiceProfileId', null)
                    }}
                  />
                  <SelectField
                    title="TTS 声线"
                    hint={ttsVoiceError || '由当前语音合成引擎提供'}
                    value={params.ttsVoice}
                    options={ttsVoiceOptions}
                    onChange={(value) => updateParam('ttsVoice', value)}
                  />
                  {params.ttsEngine === 'qwen3' ? (
                    <SelectField
                      title="音色档案"
                      hint={availableVoiceProfiles.length > 0 ? '仅显示当前可用的 Qwen3 音色档案' : '当前没有可用的 Qwen3 音色档案'}
                      value={params.voiceProfileId ?? ''}
                      options={[
                        { value: '', label: '不使用音色档案' },
                        ...availableVoiceProfiles.map((profile) => ({
                          value: profile.id,
                          label: `${profile.name} · ${profile.category}`,
                        })),
                      ]}
                      onChange={(value) => updateParam('voiceProfileId', value || null)}
                    />
                  ) : null}
                </>
              ) : null}
              {stageFlags.asr ? (
                <>
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
                </>
              ) : null}
              {stageFlags.translate ? (
                <>
                  <SelectField
                    title="翻译提供方"
                    value={params.translateProvider}
                    options={translateProviderOptions}
                    onChange={(value) => {
                      updateParam('translateProvider', value)
                      const defaultModel = defaultModelFor('llm', value)
                      if (defaultModel) updateParam('translateModel', defaultModel)
                    }}
                  />
                  <SelectField
                    title="翻译模型"
                    value={params.translateModel}
                    options={translateModelOptions}
                    onChange={(value) => updateParam('translateModel', value)}
                  />
                </>
              ) : null}
              {stageFlags.separate ? (
                <>
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
                </>
              ) : null}
            </div>
          </Section>

          {dynamicCapabilityOptions.length > 0 ? (
            <Section title="高级参数" caption="保留，但不让它们占住主操作空间" open={advExpanded} onToggle={toggleAdv}>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 240px), 1fr))', gap: 18 }}>
                {dynamicCapabilityOptions.map(({ descriptor, option, scope }) => (
                  <CapabilityOptionField
                    key={`${scope}/${option.name}`}
                    option={option}
                    context={descriptor.display_name}
                    value={capabilityOptions[scope]?.[option.name] ?? option.default}
                    onChange={(value) => updateCapabilityOption(scope, option.name, value)}
                  />
                ))}
              </div>
            </Section>
          ) : null}
        </div>

        <aside className="workbench-side-column">
          <Section title="执行前确认" caption="点击执行前，先确认这次任务会发生什么">
            <div style={{ display: 'grid', gap: 14 }}>
              {presetError ? (
                <div
                  aria-live="polite"
                  className="workbench-break-anywhere"
                  style={{ padding: '12px 14px', border: '1px solid var(--error)', borderRadius: 8, color: 'var(--error)', fontSize: 12 }}
                >
                  <div>{presetError}</div>
                  {!presetsLoading ? (
                    <button
                      type="button"
                      onClick={() => setPresetReloadToken((value) => value + 1)}
                      style={{ marginTop: 8, border: 'none', background: 'transparent', color: 'var(--accent)', padding: 0, cursor: 'pointer', fontWeight: 700 }}
                    >
                      立即重试
                    </button>
                  ) : null}
                </div>
              ) : null}
              {capabilityError ? (
                <div className="workbench-break-anywhere" style={{ padding: '12px 14px', border: '1px solid var(--error)', borderRadius: 8, color: 'var(--error)', fontSize: 12 }}>
                  {capabilityError}
                </div>
              ) : null}
              {readinessIssues.length > 0 ? (
                <div style={{ padding: '12px 14px', border: '1px solid var(--warning)', borderRadius: 8, background: 'var(--warning-soft)', fontSize: 12 }}>
                  <div style={{ fontWeight: 700, color: 'var(--fg)' }}>当前配置暂不可执行</div>
                  {readinessIssues.map((issue, index) => (
                    <div className="workbench-break-anywhere" key={`${issue.stage}-${issue.code}-${index}`} style={{ marginTop: 6, color: 'var(--muted-strong)' }}>
                      {issue.stage}：{issue.message}
                    </div>
                  ))}
                  {readinessIssues.some((issue) => issue.action !== 'workbench') ? (
                    <button
                      type="button"
                      onClick={() => setPage(readinessIssues.some((issue) => issue.action === 'settings') ? 'settings' : 'engines')}
                      style={{ marginTop: 10, border: 'none', background: 'transparent', color: 'var(--accent)', padding: 0, cursor: 'pointer', fontWeight: 700 }}
                    >
                      前往处理
                    </button>
                  ) : null}
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
                  {currentPreset?.description || '请先等待内置预设加载完成。'}
                </div>
              </div>

              <div style={{ display: 'grid', gap: 10 }}>
                {confirmationSummary.map((item) => (
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
                    <span className="workbench-break-anywhere" style={{ minWidth: 0, fontSize: 12, fontWeight: 600, color: 'var(--fg)', textAlign: 'right' }}>{item.value}</span>
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
                      width: '100%',
                      minWidth: 0,
                      textAlign: 'left',
                      padding: '12px 14px',
                      borderRadius: 'var(--radius-sm)',
                      border: '1px solid var(--border)',
                      background: 'var(--surface)',
                      cursor: 'pointer',
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, minWidth: 0 }}>
                      <span style={{ minWidth: 0, flex: 1, fontSize: 13, fontWeight: 600, color: 'var(--fg)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                        {task.sourceName}
                      </span>
                      <span style={{ flexShrink: 0, fontSize: 11, color: 'var(--muted)' }}>{formatRelativeTime(task.createdAt)}</span>
                    </div>
                    <div style={{ marginTop: 6, display: 'flex', alignItems: 'flex-start', gap: 8, minWidth: 0 }}>
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
                      <span className="workbench-break-anywhere" style={{ minWidth: 0, fontSize: 12, color: 'var(--muted)' }}>
                        {task.message || '等待更多状态信息'}
                      </span>
                    </div>
                  </button>
                ))}
              </div>
            )}
          </Section>

        </aside>
      </div>
    </div>
  )
}
