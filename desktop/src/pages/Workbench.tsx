import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { CSSProperties, DragEvent, ReactNode } from 'react'

import { batchesApi } from '@/api/batches'
import { inputsApi } from '@/api/inputs'
import { pipelineApi } from '@/api/pipeline'
import { capabilitiesApi } from '@/api/capabilities'
import { settingsApi } from '@/api/settings'
import type { SettingsView } from '@/api/settings'
import RemoteModelSelect from '@/components/RemoteModelSelect'
import MixPreview from '@/components/MixPreview'
import { resourcesApi } from '@/api/resources'
import WorkbenchSpeech from '@/components/WorkbenchSpeech'
import type { WorkbenchSpeechResolution } from '@/components/WorkbenchSpeech'
import type {
  CapabilityDescriptorResponse,
  CapabilityOptionResponse,
  PipelineRunRequest,
  TaskReadinessIssueResponse,
} from '@/api/types'
import { FILE_FILTERS, useFileSelector } from '@/hooks/useFileSelector'
import { useTaskPolling } from '@/hooks/useTaskPolling'
import {
  PIPELINE_STAGE_IDS,
  PIPELINE_STAGE_LABELS,
  normalizePresetStages,
  type PipelineStageId,
} from '@/domain/pipelinePreset'
import {
  buildPipelineExecutionProfile,
  buildPipelineStageFlags,
  capabilityScope,
} from '@/domain/pipelineExecutionProfile'
import {
  MAX_WORKBENCH_INPUTS,
  discoveredFileToInput,
  fileName,
  inputPathKey,
  mergeInputItems,
  companionDescription,
  pathToInput,
  type WorkbenchInputItem,
} from '@/domain/workbenchInput'
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
    grid-template-columns: repeat(7, minmax(104px, 1fr));
    min-width: 728px;
    padding: 4px 0;
  }

  .workbench-pipeline-step {
    position: relative;
    min-width: 0;
    padding-right: 12px;
  }

  .workbench-pipeline-step:not(:last-child)::before {
    content: '';
    position: absolute;
    top: 12px;
    left: 35px;
    right: 10px;
    height: 1px;
    background: var(--border);
  }

  .workbench-pipeline-detail {
    margin-top: 4px;
    font-size: 12px;
    color: var(--muted);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
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

    .workbench-input-options {
      grid-template-columns: minmax(0, 1fr) !important;
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

function formatInputSize(bytes: number) {
  if (!bytes) return '大小未知'
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(1)} GB`
  if (bytes >= 1024 ** 2) return `${(bytes / 1024 ** 2).toFixed(1)} MB`
  return `${Math.max(1, Math.round(bytes / 1024))} KB`
}

async function mapWithConcurrency<Input, Output>(
  inputs: Input[],
  maxParallel: number,
  worker: (input: Input) => Promise<Output>,
) {
  const results = new Array<Output>(inputs.length)
  let nextIndex = 0
  let firstError: unknown
  let failed = false
  const runners = Array.from(
    { length: Math.min(maxParallel, inputs.length) },
    async () => {
      while (nextIndex < inputs.length && !failed) {
        const index = nextIndex
        nextIndex += 1
        const input = inputs[index]
        if (input === undefined) continue
        try {
          results[index] = await worker(input)
        } catch (error) {
          if (!failed) firstError = error
          failed = true
        }
      }
    },
  )
  await Promise.all(runners)
  if (failed) throw firstError
  return results
}

function uniqueReadinessIssues(issues: TaskReadinessIssueResponse[]) {
  return Array.from(new Map(issues.map((issue) => [
    [issue.stage, issue.code, issue.requirement, issue.provider, issue.model, issue.message].join('\u0000'),
    issue,
  ])).values())
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
  disabled = false,
}: {
  title: string
  hint?: string
  value: string
  options: Option[]
  onChange: (value: string) => void
  disabled?: boolean
}) {
  return (
    <div>
      <FieldLabel title={title} hint={hint} />
      <select
        value={value}
        disabled={disabled}
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
  speaking_style: { label: '说话风格（实验）', hint: 'normal 默认 / soft 轻声 / whisper 耳语；仅支持 Qwen3 预设音色，效果需试听确认' },
  instruct: { label: '补充风格指令', hint: '可选；与音色及说话风格提示叠加，仅支持 Qwen3 预设音色', placeholder: '例如：保持自然的停顿，吐字清晰' },
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
    inputItems,
    selectedInputPaths,
    inputFolder,
    scanRecursive,
    outputDirectory,
    batchName,
    batchMaxParallel,
    preset,
    presets,
    presetsLoading,
    params,
    capabilityOptions,
    commonExpanded,
    modelExpanded,
    advExpanded,
    addInputItems,
    removeInputItem,
    toggleInputSelection,
    selectAllInputs,
    clearInputItems,
    setInputFolder,
    setScanRecursive,
    setOutputDirectory,
    setBatchName,
    setBatchMaxParallel,
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
  const openTaskCenter = useNavStore((state) => state.openTaskCenter)
  const { selectFiles, selectFolder } = useFileSelector()

  const [dragOver, setDragOver] = useState(false)
  const [discoveringInputs, setDiscoveringInputs] = useState(false)
  const [fileSelectionError, setFileSelectionError] = useState('')
  const [capabilities, setCapabilities] = useState<CapabilityDescriptorResponse[]>([])
  const [capabilityError, setCapabilityError] = useState('')
  const [connections, setConnections] = useState<SettingsView['connection_profiles'] | null>(null)
  const selectConnection = (id: string) => {
    if (submitting) return
    const selected = connections?.llm.find(item => item.id === id)
    if (!selected) return
    updateParam('translateConnectionId', id)
    updateParam('translateProvider', selected.provider)
    updateParam('translateModel', selected.model || '')
  }
  const [speechConfig, setSpeechConfig] = useState<WorkbenchSpeechResolution | null>(null)
  const selectedRecipe = speechConfig?.recipe
  const [readinessIssues, setReadinessIssues] = useState<TaskReadinessIssueResponse[]>([])
  const [checkingReadiness, setCheckingReadiness] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [submissionError, setSubmissionError] = useState('')
  const [presetError, setPresetError] = useState('')
  const [presetReloadToken, setPresetReloadToken] = useState(0)
  const submitLockRef = useRef(false)
  const inputOperationRef = useRef(0)
  const inputOwnerActiveRef = useRef(true)
  const currentPreset = presets.find((item) => item.id === preset) ?? null
  const activePresetStages = normalizePresetStages(currentPreset?.stages ?? [])
  const stageFlags = buildPipelineStageFlags(activePresetStages, params)
  const selectedInputKeys = useMemo(
    () => new Set(selectedInputPaths.map(inputPathKey)),
    [selectedInputPaths],
  )
  const selectedInputs = useMemo(
    () => inputItems.filter((item) => selectedInputKeys.has(inputPathKey(item.path))),
    [inputItems, selectedInputKeys],
  )

  useEffect(() => {
    inputOwnerActiveRef.current = true
    return () => {
      inputOwnerActiveRef.current = false
      inputOperationRef.current += 1
    }
  }, [])

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
      Promise.all([capabilitiesApi.list(), settingsApi.get()]).then(([items, { settings }]) => {
        if (cancelled) return
        const store = useWorkbenchStore.getState()
        setConnections(settings.connection_profiles)
        if (settings.connection_profiles && !store.params.translateConnectionId) {
          const selected = settings.connection_profiles.llm.find(item => item.id === settings.connection_profiles.active_llm)
          if (selected) {
            store.updateParam('translateConnectionId', selected.id)
            store.updateParam('translateProvider', selected.provider)
            store.updateParam('translateModel', selected.model || '')
          }
        } else if (!settings.connection_profiles && !store.llmSelectionInitialized) {
          const provider = settings.providers.default_llm
          const model = provider === 'openai' ? settings.providers.openai.model : settings.providers.deepseek.model
          store.updateParam('translateProvider', provider)
          store.updateParam('translateModel', model || items.find(item => item.category === 'llm' && item.provider === provider)?.default_model || '')
        }
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
    setReadinessIssues([])
    setSubmissionError('')
  }, [preset, params, capabilityOptions, selectedInputPaths, speechConfig])

  const runningCount = tasks.filter((task) => task.status === 'running').length
  const pendingCount = tasks.filter((task) => task.status === 'pending').length
  const completedCount = tasks.filter((task) => task.status === 'completed').length
  const recentTasks = tasks.slice(-5).reverse()

  const appendInputItems = useCallback((items: WorkbenchInputItem[]) => {
    if (items.length === 0) return
    const currentItems = useWorkbenchStore.getState().inputItems
    const currentKeys = new Set(currentItems.map((item) => inputPathKey(item.path)))
    const normalizedIncoming = mergeInputItems([], items)
    const existingUpdates = normalizedIncoming.filter((item) => currentKeys.has(inputPathKey(item.path)))
    const newItems = normalizedIncoming.filter((item) => !currentKeys.has(inputPathKey(item.path)))
    const availableSlots = Math.max(0, MAX_WORKBENCH_INPUTS - currentItems.length)
    const acceptedNewItems = newItems.slice(0, availableSlots)
    const omitted = newItems.length - acceptedNewItems.length
    addInputItems([...existingUpdates, ...acceptedNewItems])
    if (omitted > 0) {
      setFileSelectionError((current) => [
        current,
        `工作台最多接收 ${MAX_WORKBENCH_INPUTS} 个输入，已忽略其余 ${omitted} 个文件。`,
      ].filter(Boolean).join(' '))
    }
  }, [addInputItems])

  const appendAudioPaths = useCallback(async (paths: string[]) => {
    if (paths.length === 0 || !inputOwnerActiveRef.current) return
    const currentItems = useWorkbenchStore.getState().inputItems
    const existingKeys = new Set(currentItems.map((item) => inputPathKey(item.path)))
    const uniquePaths = Array.from(new Map(
      paths.map((path) => [inputPathKey(path), path]),
    ).values())
    const availableSlots = Math.max(0, MAX_WORKBENCH_INPUTS - currentItems.length)
    let acceptedNewCount = 0
    let omitted = 0
    const acceptedPaths = uniquePaths.filter((path) => {
      if (existingKeys.has(inputPathKey(path))) return true
      if (acceptedNewCount < availableSlots) {
        acceptedNewCount += 1
        return true
      }
      omitted += 1
      return false
    })
    if (omitted > 0) {
      setFileSelectionError((current) => [
        current,
        `工作台最多接收 ${MAX_WORKBENCH_INPUTS} 个输入，已忽略其余 ${omitted} 个文件。`,
      ].filter(Boolean).join(' '))
    }
    if (acceptedPaths.length === 0) return

    const operationId = inputOperationRef.current + 1
    inputOperationRef.current = operationId
    setDiscoveringInputs(true)
    try {
      const resolved = await inputsApi.resolveItems(acceptedPaths)
      if (!inputOwnerActiveRef.current || inputOperationRef.current !== operationId) return
      appendInputItems(resolved.items)
      if (resolved.warnings.length > 0) {
        setFileSelectionError((current) => [
          current,
          resolved.warnings.join(' '),
        ].filter(Boolean).join(' '))
      }
    } catch (error) {
      if (!inputOwnerActiveRef.current || inputOperationRef.current !== operationId) return
      const existingKeys = new Set(
        useWorkbenchStore.getState().inputItems.map((item) => inputPathKey(item.path)),
      )
      appendInputItems(
        acceptedPaths
          .filter((path) => !existingKeys.has(inputPathKey(path)))
          .map(pathToInput),
      )
      setFileSelectionError((current) => [
        current,
        `读取文件信息或伴随字幕失败，已按路径加入：${error instanceof Error ? error.message : String(error)}`,
      ].filter(Boolean).join(' '))
    } finally {
      if (inputOwnerActiveRef.current && inputOperationRef.current === operationId) {
        setDiscoveringInputs(false)
      }
    }
  }, [appendInputItems])

  const handleSelectFiles = useCallback(async () => {
    setFileSelectionError('')
    const files = await selectFiles({ filters: [FILE_FILTERS.audio] })
    const { accepted, rejected } = partitionAudioPaths(files)
    setFileSelectionError(unsupportedAudioMessage(rejected))
    await appendAudioPaths(accepted)
  }, [appendAudioPaths, selectFiles])

  const scanInputFolder = useCallback(async (directory: string) => {
    if (!directory || !inputOwnerActiveRef.current) return
    const operationId = inputOperationRef.current + 1
    inputOperationRef.current = operationId
    setDiscoveringInputs(true)
    setFileSelectionError('')
    try {
      const response = await batchesApi.discover(directory, scanRecursive, MAX_WORKBENCH_INPUTS + 1)
      if (!inputOwnerActiveRef.current || inputOperationRef.current !== operationId) return
      const discoveredFiles = response.files.slice(0, MAX_WORKBENCH_INPUTS)
      appendInputItems(discoveredFiles.map(discoveredFileToInput))
      if (response.files.length > MAX_WORKBENCH_INPUTS) {
        setFileSelectionError(
          `目录匹配项超过 ${MAX_WORKBENCH_INPUTS} 个，已仅载入排序后的前 ${MAX_WORKBENCH_INPUTS} 个文件。`,
        )
      }
      if (!useWorkbenchStore.getState().batchName.trim()) {
        setBatchName(`批量处理 · ${fileName(directory)}`)
      }
    } catch (error) {
      if (!inputOwnerActiveRef.current || inputOperationRef.current !== operationId) return
      setFileSelectionError(`扫描目录失败：${error instanceof Error ? error.message : String(error)}`)
    } finally {
      if (inputOwnerActiveRef.current && inputOperationRef.current === operationId) {
        setDiscoveringInputs(false)
      }
    }
  }, [appendInputItems, scanRecursive, setBatchName])

  const handleClearInputs = useCallback(() => {
    inputOperationRef.current += 1
    setDiscoveringInputs(false)
    setFileSelectionError('')
    clearInputItems()
  }, [clearInputItems])

  const handleSelectFolder = useCallback(async () => {
    const directory = await selectFolder()
    if (!directory) return
    setInputFolder(directory)
    await scanInputFolder(directory)
  }, [scanInputFolder, selectFolder, setInputFolder])

  const handleSelectOutputDirectory = useCallback(async () => {
    const directory = await selectFolder()
    if (directory) setOutputDirectory(directory)
  }, [selectFolder, setOutputDirectory])

  const handleDrop = useCallback(async (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault()
    setDragOver(false)
    if (discoveringInputs || submitting) return

    const dropped = Array.from(event.dataTransfer.files)
    if (dropped.length === 0) return

    const paths = dropped.map((file) => (file as File & { path?: string }).path || file.name)
    const { accepted, rejected } = partitionAudioPaths(paths)
    setFileSelectionError(unsupportedAudioMessage(rejected))
    if (accepted.length === 0) return

    const missingFullPath = accepted.some((path) => !path.includes('/') && !path.includes('\\'))

    if (!missingFullPath) {
      await appendAudioPaths(accepted)
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
    await appendAudioPaths(fullPaths)
  }, [appendAudioPaths, discoveringInputs, submitting])

  const handleExecute = async () => {
    if (
      selectedInputs.length === 0 ||
      !currentPreset ||
      discoveringInputs ||
      submitLockRef.current
    ) return

    if (stageFlags.translate && connections && !connections.llm.some(item => item.id === params.translateConnectionId)) {
      setSubmissionError('本次翻译连接已不可用，请重新选择')
      return
    }

    if (stageFlags.tts && (!speechConfig?.stage || speechConfig.error)) {
      setSubmissionError(speechConfig?.error || '正在读取配音引擎能力，请稍后重试')
      return
    }

    submitLockRef.current = true
    setSubmitting(true)
    setSubmissionError('')
    try {
      const executionProfile = buildPipelineExecutionProfile({
        params,
        stageFlags,
        capabilities,
        capabilityOptions,
        speechStage: speechConfig?.stage ?? null,
      })

      setCheckingReadiness(true)
      setReadinessIssues([])
      try {
        const readinessResults = await mapWithConcurrency(
          selectedInputs,
          6,
          (item) => resourcesApi.checkTaskReadiness(
            'pipeline',
            executionProfile,
            item.path,
          ),
        )
        const issues = uniqueReadinessIssues(
          readinessResults.flatMap((readiness) => readiness.ready ? [] : readiness.issues),
        )
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

      if (selectedInputs.length > 1) {
        try {
          const created = await batchesApi.create({
            name: batchName.trim() || `批量任务 · ${new Date().toLocaleString()}`,
            inputs: selectedInputs.map((item) => ({
              path: item.path,
              companion_paths: item.companionPaths,
            })),
            output: { directory: outputDirectory || undefined },
            execution_profile: executionProfile,
            max_parallel: batchMaxParallel,
          })
          addLog({
            level: 'info',
            content: `批次已创建：${created.name}（${created.total_count} 个文件，${created.batch_id}）`,
          })
          openTaskCenter('batches')
        } catch (error) {
          setSubmissionError(`创建批次失败：${error instanceof Error ? error.message : String(error)}`)
        }
        return
      }

      const input = selectedInputs[0]
      if (!input) return
      const request: PipelineRunRequest = {
        input: {
          path: input.path,
          companion_paths: input.companionPaths,
        },
        output: { directory: outputDirectory || undefined },
        execution_profile: executionProfile,
      }

      const taskId = addTask({
        jobType: 'pipeline',
        sourceName: input.name,
        sourcePath: input.path,
        params: {
          input_path: input.path,
          companion_paths: input.companionPaths,
          output_directory: outputDirectory,
          preset_id: currentPreset.id,
          source_lang: params.sourceLang,
          target_lang: params.targetLang,
          use_vocal_separator: stageFlags.separate,
          speech_recipe_id: stageFlags.tts ? selectedRecipe?.id ?? null : null,
          speech_recipe_name: stageFlags.tts ? selectedRecipe?.name : null,
          vocal_model: params.vocalModel,
          asr_model: params.asrModel,
          translate_provider: params.translateProvider,
          translate_model: params.translateModel,
          original_volume: params.originalVolume,
          tts_volume_ratio: params.ttsVolumeRatio,
          tts_delay: params.ttsDelay,
          skip_existing: params.skipExisting,
        },
      })

      updateTask(taskId, { message: '正在创建后端任务', progress: 0 })
      addLog({ level: 'info', content: `任务已创建：${input.path}`, taskId })

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

      openTaskCenter('tasks')
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

  const translateProviderOptions = providerOptions('llm', TRANSLATE_PROVIDER_OPTIONS)
  const asrProviderOptions = providerOptions('asr', [{ value: 'faster_whisper', label: 'faster-whisper' }])
  const asrModelOptions = modelsFor('asr', params.asrProvider, ASR_MODEL_OPTIONS)
  const vocalProviderOptions = providerOptions('separator', [{ value: 'demucs', label: 'Demucs' }])
  const vocalModelOptions = modelsFor('separator', params.vocalProvider, VOCAL_MODEL_OPTIONS)

  const selectedDescriptors = [
    stageFlags.asr
      ? capabilities.find((item) => item.category === 'asr' && item.provider === params.asrProvider)
      : undefined,
    stageFlags.translate
      ? capabilities.find((item) => item.category === 'llm' && item.provider === params.translateProvider)
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

  const stageDetails = {
    separate: activePresetStages.has('separate')
      ? (params.useVocalSeparator ? `模型：${params.vocalModel}` : '已由参数关闭')
      : '当前预设不执行',
    asr: stageFlags.asr ? `模型：${params.asrModel}` : '当前预设不执行',
    align: stageFlags.align ? 'Qwen3-ForcedAligner-0.6B' : '未启用',
    translate: activePresetStages.has('translate')
      ? (stageFlags.translate
          ? `${optionLabel(LANG_OPTIONS, params.sourceLang)} → ${optionLabel(LANG_OPTIONS, params.targetLang)}`
          : '源语言与目标语言相同，自动跳过')
      : '当前预设不执行',
    tts: stageFlags.tts ? speechConfig?.summary || '请选择配音引擎' : '当前预设不执行',
    mix: stageFlags.mix
      ? `原声 ${Math.round(params.originalVolume * 100)}% · 配音 ${Math.round(params.ttsVolumeRatio * 100)}%`
      : '当前预设不执行',
    export: stageFlags.export ? '导出 SRT 字幕与文本结果' : '当前预设不执行',
  }
  const compactStageDetails: Record<PipelineStageId, string> = {
    separate: params.vocalModel === 'htdemucs' ? 'Demucs' : params.vocalModel,
    asr: params.asrModel.startsWith('faster-whisper-')
      ? `Whisper ${params.asrModel.slice('faster-whisper-'.length)}` : params.asrModel,
    align: 'Qwen 0.6B',
    translate: `${optionLabel(LANG_OPTIONS, params.sourceLang).replace(/\s*\([^)]*\)/g, '')} → ${optionLabel(LANG_OPTIONS, params.targetLang).replace(/\s*\([^)]*\)/g, '')}`,
    tts: speechConfig?.summary || '待选择引擎',
    mix: `原声 ${Math.round(params.originalVolume * 100)}% · 配音 ${Math.round(params.ttsVolumeRatio * 100)}%`,
    export: 'SRT + 文本',
  }
  const stageSummary = PIPELINE_STAGE_IDS.map((id) => ({
    id,
    title: PIPELINE_STAGE_LABELS[id],
    enabled: stageFlags[id],
    detail: stageDetails[id],
    summary: compactStageDetails[id],
  }))

  const outputSummary = [
    ...(stageFlags.mix ? ['混音成品音频'] : []),
    ...(stageFlags.export ? ['SRT 字幕与识别文本'] : []),
    ...(stageFlags.align ? ['原始时间轴、校准字幕与逐字时间戳'] : []),
    ...(stageFlags.tts ? ['语音合成中间音轨'] : []),
    ...(stageFlags.separate ? ['分离人声中间产物'] : []),
  ]
  const confirmationSummary = [
    { label: '输入文件', value: selectedInputs.length === 0 ? '尚未选择' : `${selectedInputs.length} / ${inputItems.length} 个音频` },
    {
      label: '提交方式',
      value: selectedInputs.length === 0
        ? '等待选择输入'
        : selectedInputs.length > 1
          ? '创建一个可恢复管理的批次'
          : '创建一个普通 Pipeline 任务',
    },
    { label: '输出目录', value: outputDirectory || '使用工作区默认目录' },
    {
      label: '执行阶段',
      value: stageSummary.filter((stage) => stage.enabled).map((stage) => stage.title).join(' → ') || '没有可执行阶段',
    },
    ...(stageFlags.translate
      ? [{ label: '目标语言', value: optionLabel(LANG_OPTIONS, params.targetLang) }]
      : []),
    ...(stageFlags.tts
      ? [{ label: '配音配置', value: speechConfig?.summary || '尚未选择' }]
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
          <h1 style={{ marginTop: 8, fontSize: 26, lineHeight: 1.15, fontWeight: 700, fontFamily: 'var(--font-display)' }}>
            工作台
          </h1>
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
          <ActionButton variant="ghost" disabled={inputItems.length === 0 || submitting || discoveringInputs} onClick={handleClearInputs}>
            清空列表
          </ActionButton>
          <ActionButton
            variant="primary"
            disabled={selectedInputs.length === 0 || submitting || discoveringInputs || !!capabilityError || !currentPreset}
            onClick={handleExecute}
          >
            <PlayIcon />
            {checkingReadiness
              ? '检查运行条件...'
              : submitting
                ? selectedInputs.length > 1 ? '正在创建批次...' : '正在创建任务...'
                : selectedInputs.length > 1 ? `创建批次（${selectedInputs.length}）` : '创建并执行'}
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
            caption={inputItems.length === 0
              ? '选择音频、递归扫描目录，或直接拖入文件'
              : `已选择 ${selectedInputs.length} / ${inputItems.length} 个音频文件`}
            actions={
              inputItems.length > 0 ? (
                <label style={{ display: 'inline-flex', gap: 7, alignItems: 'center', fontSize: 12, color: 'var(--muted)', cursor: 'pointer' }}>
                  <input
                    type="checkbox"
                    checked={selectedInputs.length === inputItems.length}
                    disabled={submitting || discoveringInputs}
                    onChange={() => selectAllInputs(selectedInputs.length !== inputItems.length)}
                  />
                  全选
                </label>
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
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 12 }}>
              <ActionButton variant="ghost" disabled={submitting || discoveringInputs} onClick={handleSelectFiles}>
                <UploadIcon />
                添加音频
              </ActionButton>
              <ActionButton variant="ghost" disabled={submitting || discoveringInputs} onClick={handleSelectFolder}>
                {discoveringInputs ? '正在发现输入...' : '选择目录'}
              </ActionButton>
              {inputFolder ? (
                <ActionButton variant="ghost" disabled={submitting || discoveringInputs} onClick={() => scanInputFolder(inputFolder)}>
                  重新扫描
                </ActionButton>
              ) : null}
              <label style={{ display: 'inline-flex', gap: 7, alignItems: 'center', minHeight: 36, fontSize: 12, color: 'var(--muted)', cursor: 'pointer' }}>
                <input
                  type="checkbox"
                  checked={scanRecursive}
                  disabled={submitting || discoveringInputs}
                  onChange={(event) => setScanRecursive(event.target.checked)}
                />
                扫描子目录
              </label>
            </div>
            {inputFolder ? (
              <div className="workbench-break-anywhere" style={{ margin: '-3px 0 12px', fontSize: 11, color: 'var(--muted)' }}>
                当前目录：{inputFolder}
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
                padding: inputItems.length === 0 ? '30px 24px' : '14px',
              }}
            >
              {inputItems.length === 0 ? (
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
                    文件与目录共用同一份清单；同名 VTT、SRT 或 LRC 会自动成为伴随字幕。
                  </div>
                </div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 10, maxHeight: 380, overflow: 'auto' }}>
                  {inputItems.map((item) => {
                    const selected = selectedInputKeys.has(inputPathKey(item.path))
                    return (
                    <div
                      key={item.path}
                      style={{
                        display: 'grid',
                        gridTemplateColumns: 'auto minmax(0, 1fr) auto',
                        gap: 12,
                        alignItems: 'center',
                        padding: '12px 14px',
                        borderRadius: 'var(--radius-sm)',
                        background: selected ? 'var(--surface)' : 'var(--panel-muted)',
                        border: selected ? '1px solid var(--border)' : '1px solid transparent',
                        opacity: selected ? 1 : 0.68,
                      }}
                    >
                      <input
                        type="checkbox"
                        checked={selected}
                        disabled={submitting || discoveringInputs}
                        onChange={() => toggleInputSelection(item.path)}
                        aria-label={`选择 ${item.name}`}
                      />
                      <div style={{ minWidth: 0 }}>
                        <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--fg)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                          {item.name}
                        </div>
                        <div style={{ marginTop: 4, fontSize: 11, color: 'var(--muted)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                          {item.path}
                        </div>
                        <div style={{ marginTop: 4, fontSize: 10, color: 'var(--muted)' }}>
                          {formatInputSize(item.size)} · {companionDescription(item, params.sourceLang, params.targetLang)}
                        </div>
                      </div>
                      <button
                        type="button"
                        disabled={submitting || discoveringInputs}
                        onClick={() => removeInputItem(item.path)}
                        style={{
                          padding: '6px 10px',
                          borderRadius: 'var(--radius-sm)',
                          border: '1px solid var(--border)',
                          background: 'transparent',
                          color: 'var(--muted)',
                          cursor: submitting || discoveringInputs ? 'default' : 'pointer',
                          opacity: submitting || discoveringInputs ? 0.55 : 1,
                        }}
                      >
                        移除
                      </button>
                    </div>
                    )
                  })}
                </div>
              )}
            </div>

            <div className="workbench-input-options" style={{ marginTop: 14, display: 'grid', gridTemplateColumns: selectedInputs.length > 1 ? 'minmax(0, 1fr) minmax(150px, 0.55fr) 130px' : 'minmax(0, 1fr)', gap: 12 }}>
              <label style={{ minWidth: 0 }}>
                <span style={{ display: 'flex', justifyContent: 'space-between', gap: 10, alignItems: 'baseline', fontSize: 12, fontWeight: 650 }}>
                  输出目录
                  {outputDirectory ? (
                    <button
                      type="button"
                      disabled={submitting}
                      onClick={() => setOutputDirectory('')}
                      style={{ border: 'none', padding: 0, background: 'transparent', color: 'var(--accent)', font: 'inherit', fontSize: 11, cursor: submitting ? 'default' : 'pointer' }}
                    >
                      恢复默认
                    </button>
                  ) : null}
                </span>
                <button
                  type="button"
                  disabled={submitting}
                  onClick={handleSelectOutputDirectory}
                  className="workbench-break-anywhere"
                  style={{ width: '100%', minHeight: 40, marginTop: 6, padding: '8px 11px', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)', background: 'var(--surface)', color: outputDirectory ? 'var(--fg)' : 'var(--muted)', textAlign: 'left', cursor: submitting ? 'default' : 'pointer' }}
                >
                  {outputDirectory || '使用工作区默认目录'}
                </button>
              </label>
              {selectedInputs.length > 1 ? (
                <label style={{ minWidth: 0 }}>
                  <span style={{ fontSize: 12, fontWeight: 650 }}>批次名称</span>
                  <input
                    value={batchName}
                    maxLength={100}
                    onChange={(event) => setBatchName(event.target.value)}
                    placeholder="自动生成"
                    style={{ width: '100%', minHeight: 40, marginTop: 6, padding: '8px 11px', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)', background: 'var(--surface)', color: 'var(--fg)', font: 'inherit' }}
                  />
                </label>
              ) : null}
              {selectedInputs.length > 1 ? (
                <label>
                  <span style={{ fontSize: 12, fontWeight: 650 }}>并行文件数</span>
                  <select
                    value={batchMaxParallel}
                    onChange={(event) => setBatchMaxParallel(Number(event.target.value))}
                    style={{ width: '100%', minHeight: 40, marginTop: 6, padding: '8px 11px', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)', background: 'var(--surface)', color: 'var(--fg)', font: 'inherit' }}
                  >
                    <option value={1}>1（推荐）</option>
                    <option value={2}>2</option>
                    <option value={3}>3</option>
                    <option value={4}>4</option>
                  </select>
                </label>
              ) : null}
            </div>

            {selectedInputs.length > 1 ? (
              <div style={{ marginTop: 12, padding: '10px 12px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--accent)', background: 'var(--accent-soft)', color: 'var(--fg)', fontSize: 12 }}>
                本次将创建一个包含 {selectedInputs.length} 项的 BatchRun；可在任务中心整批取消、查看历史或重提失败项。
              </div>
            ) : null}
          </Section>

          <Section title="处理流程">
            <div className="workbench-pipeline-scroll" tabIndex={0} role="region" aria-label="处理流程，可横向滚动查看全部步骤">
              <ol className="workbench-pipeline-track" style={{ listStyle: 'none', margin: 0 }}>
              {stageSummary.map((stage, index) => (
                <li
                  key={stage.id}
                  className="workbench-pipeline-step"
                  title={stage.detail}
                >
                    <span
                      style={{
                        width: 26,
                        height: 26,
                        borderRadius: 999,
                        background: stage.enabled ? 'var(--accent-soft)' : 'var(--panel-muted)',
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
                    <div style={{ marginTop: 10, fontSize: 13, fontWeight: 600, color: stage.enabled ? 'var(--fg)' : 'var(--muted)' }}>{stage.title}</div>
                    <div className="workbench-pipeline-detail">{stage.enabled ? stage.summary : '跳过'}</div>
                </li>
              ))}
              </ol>
            </div>
          </Section>

          <Section title="基础参数" open={commonExpanded} onToggle={toggleCommon}>
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
              {stageFlags.asr ? <ToggleField
                title="校准字幕时间轴"
                hint="使用 Qwen3-ForcedAligner-0.6B 对齐原音频与文字，需先安装模型"
                checked={params.alignSubtitles}
                onChange={(value) => updateParam('alignSubtitles', value)}
              /> : null}
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
            {stageFlags.mix ? <MixPreview inputPaths={selectedInputPaths}
              originalVolume={params.originalVolume} ttsVolumeRatio={params.ttsVolumeRatio} ttsDelay={params.ttsDelay} /> : null}
          </Section>

          <Section title="模型与引擎" open={modelExpanded} onToggle={toggleModel}>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 220px), 1fr))', gap: 16 }}>
              {stageFlags.tts ? (
                <WorkbenchSpeech disabled={submitting} language={params.targetLang}
                  preferredProvider={params.ttsEngine}
                  onChange={setSpeechConfig} />
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
                  {connections ? <SelectField title="翻译连接配置" hint="仅用于本次任务或批次；全局默认在外部服务中管理" disabled={submitting}
                    value={params.translateConnectionId || ''}
                    options={connections.llm.map(item => ({ value: item.id, label: item.name }))}
                    onChange={selectConnection} /> : <SelectField
                    title="翻译提供方"
                    value={params.translateProvider}
                    options={translateProviderOptions}
                    onChange={(value) => {
                      updateParam('translateProvider', value)
                      const defaultModel = defaultModelFor('llm', value)
                      if (defaultModel) updateParam('translateModel', defaultModel)
                    }}
                  />}
                  <RemoteModelSelect key={params.translateConnectionId} connectionRef={params.translateConnectionId} provider={params.translateProvider} value={params.translateModel}
                    onChange={value => updateParam('translateModel', value)} />
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
            <Section title="高级参数" open={advExpanded} onToggle={toggleAdv}>
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
          <Section title="执行前确认">
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
              {submissionError ? (
                <div role="alert" className="workbench-break-anywhere" style={{ padding: '12px 14px', border: '1px solid var(--error)', borderRadius: 8, background: 'var(--error-soft)', color: 'var(--error)', fontSize: 12 }}>
                  {submissionError}
                </div>
              ) : null}
              {readinessIssues.length > 0 ? (
                <div style={{ padding: '12px 14px', border: '1px solid var(--warning)', borderRadius: 8, background: 'var(--warning-soft)', fontSize: 12 }}>
                  <div style={{ fontWeight: 700, color: 'var(--fg)' }}>当前配置暂不可执行</div>
                  {readinessIssues.map((issue, index) => (
                    <div className="workbench-break-anywhere" key={`${issue.stage}-${issue.code}-${index}`} style={{ marginTop: 6, color: 'var(--muted-strong)' }}>
                      {issue.category === 'input'
                        ? `${issue.requirement}：${issue.message}`
                        : `${issue.stage}：${issue.message}`}
                    </div>
                  ))}
                  {readinessIssues.some((issue) => issue.action !== 'workbench') ? (
                    <button
                      type="button"
                      onClick={() => useNavStore.getState().openEngines(readinessIssues.some((issue) => issue.action === 'settings') ? 'external' : 'local')}
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

          <Section title="预计输出">
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
