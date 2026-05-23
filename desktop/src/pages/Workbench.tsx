import { useEffect, useState, useCallback } from 'react'
import { useWorkbenchStore } from '@/stores/workbenchStore'
import { useTaskStore } from '@/stores/taskStore'
import { useLogStore } from '@/stores/logStore'
import { useFileSelector } from '@/hooks/useFileSelector'
import { useTaskPolling } from '@/hooks/useTaskPolling'
import { pipelineApi } from '@/api/pipeline'
import type { PipelineRunRequest } from '@/api/types'
import type { TaskStatus } from '@/stores/taskStore'

// ── Option constants ────────────────────────────────────

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

// ── SVG Icons ───────────────────────────────────────────

const PlayIcon = () => (
  <svg width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2">
    <path d="M5 3l7 4-7 4V3z" fill="currentColor" stroke="none" />
  </svg>
)

const PreviewIcon = () => (
  <svg width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.8">
    <circle cx="7" cy="7" r="5.5" /><path d="M5 7h4M7 5v4" />
  </svg>
)

const UploadIcon = () => (
  <svg width="28" height="28" fill="none" stroke="currentColor" strokeWidth="1.5">
    <path d="M14 5v12M9 12l5 5 5-5" /><path d="M5 20v3h18v-3" />
  </svg>
)

const MusicIcon = () => (
  <svg width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.5">
    <path d="M5 3v8M5 11a3 3 0 100-2M12 2v8M12 10a3 3 0 100-2" />
  </svg>
)

const ChevronIcon = ({ open }: { open: boolean }) => (
  <svg width="12" height="12" fill="none" stroke="currentColor" strokeWidth="1.5"
    style={{ transform: open ? 'rotate(180deg)' : 'rotate(-90deg)', transition: 'transform 0.15s' }}>
    <path d="M3 5l3 3 3-3" />
  </svg>
)

const InfoIcon = () => (
  <svg width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.5">
    <circle cx="8" cy="8" r="6" /><path d="M8 7v4M8 5.5v.5" />
  </svg>
)

// ── Component ───────────────────────────────────────────

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

  const addTask = useTaskStore((s) => s.addTask)
  const updateTask = useTaskStore((s) => s.updateTask)
  const tasks = useTaskStore((s) => s.tasks)
  const addLog = useLogStore((s) => s.addLog)
  const { selectFiles } = useFileSelector()

  const [dragOver, setDragOver] = useState(false)

  // Load presets on mount
  useEffect(() => {
    pipelineApi.presets().then((res) => {
      useWorkbenchStore.getState().setPresets(res.presets)
      if (res.presets.length > 0 && !preset) {
        setPreset(res.presets[0]!.id)
      }
    }).catch(() => { })
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // Task stats
  const runningCount = tasks.filter((t) => t.status === 'running').length
  const pendingCount = tasks.filter((t) => t.status === 'pending').length
  const completedCount = tasks.filter((t) => t.status === 'completed').length
  const recentTasks = tasks.slice(-8).reverse()

  // File handling
  const handleSelectFiles = useCallback(async () => {
    const files = await selectFiles()
    if (files.length > 0) {
      setFiles([...selectedFiles, ...files.filter((f) => !selectedFiles.includes(f))])
    }
  }, [selectedFiles, selectFiles, setFiles])

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setDragOver(false)
    const dropped = Array.from(e.dataTransfer.files).map((f) => f.name)
    if (dropped.length > 0) {
      setFiles([...selectedFiles, ...dropped.filter((f) => !selectedFiles.includes(f))])
    }
  }, [selectedFiles, setFiles])

  // Execute
  const handleExecute = async () => {
    if (selectedFiles.length === 0) return

    for (const filePath of selectedFiles) {
      const request: PipelineRunRequest = {
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
      }

      const taskId = addTask({
        jobType: 'pipeline',
        sourceName: filePath.split(/[/\\]/).pop() ?? filePath,
        sourcePath: filePath,
        params: request as unknown as Record<string, unknown>,
      })
      updateTask(taskId, { status: 'running', message: 'request dispatched' })
      addLog({ level: 'info', content: `任务已创建: ${filePath}`, taskId })

      pipelineApi
        .run(request)
        .then((res) => {
          const serverTaskId = res.task_id ?? res.task?.task_id ?? undefined
          const finalStatus: TaskStatus = (res.task?.state ?? (res.success ? 'completed' : 'failed')) as TaskStatus
          useTaskStore.getState().updateTask(taskId, {
            serverTaskId,
            status: finalStatus,
            progress: res.task?.progress ?? (res.success ? 1 : 0),
            message: res.task?.message ?? '',
            detail: res.task?.detail ?? '',
            artifacts: res.artifacts
              ? { files: res.artifacts.files, primaryOutput: res.artifacts.primary_output ?? undefined }
              : undefined,
            errorMessage: res.error_message ?? undefined,
          })
          addLog({
            level: finalStatus === 'completed' || finalStatus === 'skipped' ? 'info' : 'error',
            content: res.success ? `任务完成: ${res.input_path}` : `任务失败: ${res.error_message}`,
            taskId,
          })
        })
        .catch((err) => {
          useTaskStore.getState().updateTask(taskId, { status: 'failed', errorMessage: String(err) })
          addLog({ level: 'error', content: `任务异常: ${String(err)}`, taskId })
        })
    }
  }

  const presetOptions = presets.length > 0
    ? presets.map((p) => ({ value: p.id, label: p.label || p.id }))
    : [{ value: '', label: '加载中...' }]

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

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>

      {/* ── Action Bar ─────────────────────────────── */}
      <header style={{
        padding: '16px 24px 12px',
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        flexShrink: 0,
        borderBottom: '1px solid var(--border)',
      }}>
        <h1 style={{
          fontFamily: 'var(--font-display)',
          fontSize: 15,
          fontWeight: 600,
          letterSpacing: '-0.02em',
          marginRight: 8,
          color: 'var(--fg)',
        }}>
          工作台
        </h1>

        {/* Task pills */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          {runningCount > 0 && (
            <span style={{
              fontSize: 11, fontWeight: 500, padding: '3px 10px', borderRadius: 10,
              background: 'oklch(93% 0.04 255)', color: 'oklch(42% 0.14 255)',
              display: 'inline-flex', alignItems: 'center', gap: 4,
            }}>
              <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'oklch(65% 0.16 255)' }} />
              {runningCount} 运行中
            </span>
          )}
          {pendingCount > 0 && (
            <span style={{ fontSize: 11, fontWeight: 500, padding: '3px 10px', borderRadius: 10, background: 'oklch(95% 0.01 90)', color: 'oklch(50% 0.06 90)' }}>
              {pendingCount} 排队
            </span>
          )}
          {completedCount > 0 && (
            <span style={{ fontSize: 11, fontWeight: 500, padding: '3px 10px', borderRadius: 10, background: 'oklch(94% 0.03 145)', color: 'oklch(38% 0.10 145)' }}>
              {completedCount} 完成
            </span>
          )}
        </div>

        <div style={{ flex: 1 }} />

        <button style={{
          fontFamily: 'var(--font-body)', fontSize: 13, fontWeight: 500,
          padding: '7px 14px', borderRadius: 'var(--radius-sm)',
          border: '1px solid var(--border)', background: 'var(--surface)', color: 'var(--fg)',
          cursor: 'pointer', display: 'inline-flex', alignItems: 'center', gap: 6,
        }}>
          <PreviewIcon />
          预览合成
        </button>
        <button
          onClick={handleExecute}
          disabled={selectedFiles.length === 0}
          style={{
            fontFamily: 'var(--font-body)', fontSize: 13, fontWeight: 500,
            padding: '7px 14px', borderRadius: 'var(--radius-sm)',
            border: '1px solid var(--accent)', background: 'var(--accent)', color: 'white',
            cursor: selectedFiles.length === 0 ? 'not-allowed' : 'pointer',
            opacity: selectedFiles.length === 0 ? 0.5 : 1,
            display: 'inline-flex', alignItems: 'center', gap: 6,
          }}
        >
          <PlayIcon />
          创建并执行
        </button>
      </header>

      {/* ── Main Content ───────────────────────────── */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 280px', flex: 1, overflow: 'hidden' }}>

        {/* ── Work Area ────────────────────────────── */}
        <div style={{ padding: '16px 24px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 16 }}>

          {/* ── Top Row: Files (left) + Selectors (right) ── */}
          <div style={{ display: 'flex', gap: 16, alignItems: 'stretch' }}>

            {/* Input Files */}
            <div style={{
              flex: 1, minWidth: 0,
              background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 'var(--radius)',
              display: 'flex', flexDirection: 'column',
            }}>
              <div style={{
                padding: '12px 16px', fontSize: 13, fontWeight: 600, color: 'var(--fg)',
                borderBottom: '1px solid var(--border)',
                display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              }}>
                <span>传入文件</span>
                <span style={{ fontSize: 11, fontWeight: 500, color: 'var(--muted)', background: 'var(--bg)', padding: '2px 8px', borderRadius: 10 }}>
                  {selectedFiles.length} 个文件
                </span>
              </div>

              {/* Drop Zone */}
              <div
                onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
                onDragLeave={() => setDragOver(false)}
                onDrop={handleDrop}
                onClick={handleSelectFiles}
                style={{
                  border: `2px dashed ${dragOver ? 'var(--accent)' : 'var(--border)'}`,
                  borderRadius: 'var(--radius-sm)',
                  margin: 12,
                  padding: '24px 20px',
                  textAlign: 'center',
                  cursor: 'pointer',
                  transition: 'border-color 0.15s, background 0.15s',
                  background: dragOver ? 'oklch(97% 0.02 255)' : 'transparent',
                }}
              >
                <div style={{ color: 'var(--muted)', marginBottom: 6 }}><UploadIcon /></div>
                <div style={{ fontSize: 13, color: 'var(--muted)' }}>
                  <strong style={{ color: 'var(--fg)', fontWeight: 500 }}>拖入音频文件</strong> 或点击选择
                </div>
                <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 4 }}>
                  WAV / MP3 / FLAC / OGG / M4A
                </div>
              </div>

              {/* File List */}
              {selectedFiles.length > 0 && (
                <div style={{ paddingBottom: 4 }}>
                  {selectedFiles.map((file) => (
                    <div
                      key={file}
                      style={{
                        padding: '8px 16px',
                        display: 'flex',
                        alignItems: 'center',
                        gap: 10,
                        borderBottom: '1px solid var(--border)',
                        fontSize: 13,
                      }}
                    >
                      <span style={{ color: 'var(--muted)', flexShrink: 0 }}><MusicIcon /></span>
                      <span style={{ fontWeight: 500, whiteSpace: 'nowrap' }}>
                        {file.split(/[/\\]/).pop()}
                      </span>
                      <span style={{ color: 'var(--muted)', fontSize: 11, flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {file.replace(/[/\\][^/\\]+$/, '')}
                      </span>
                      <span
                        onClick={(e) => { e.stopPropagation(); removeFile(file) }}
                        style={{ color: 'var(--muted)', cursor: 'pointer', fontSize: 16, lineHeight: 1, padding: 4, borderRadius: 4, flexShrink: 0 }}
                      >
                        ×
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Selector Boxes (right column) */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8, width: 200, flexShrink: 0 }}>
              <SelectorBox label="预设" value={preset} onChange={setPreset} options={presetOptions} />
              <SelectorBox label="ASR 模型" value={params.asrModel} onChange={(v) => updateParam('asrModel', v)} options={ASR_MODEL_OPTIONS} />
              <SelectorBox label="TTS 引擎" value={params.ttsEngine} onChange={(v) => updateParam('ttsEngine', v)} options={TTS_ENGINE_OPTIONS} />
            </div>
          </div>

          {/* ── 通用能力 (collapsible) ─────────────── */}
          <CollapsiblePanel
            title="通用能力"
            hint="所有预设共有"
            open={commonExpanded}
            onToggle={toggleCommon}
          >
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
              <CapGroup label="源语言">
                <select value={params.sourceLang} onChange={(e) => updateParam('sourceLang', e.target.value)} style={selectStyle}>
                  {LANG_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                </select>
              </CapGroup>
              <CapGroup label="目标语言">
                <select value={params.targetLang} onChange={(e) => updateParam('targetLang', e.target.value)} style={selectStyle}>
                  {LANG_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                </select>
              </CapGroup>
              <CapGroup label="翻译服务">
                <select value={params.translateProvider} onChange={(e) => updateParam('translateProvider', e.target.value)} style={selectStyle}>
                  {TRANSLATE_PROVIDER_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                </select>
              </CapGroup>
              <CapGroup label="TTS 音色">
                <select value={params.ttsVoice} onChange={(e) => updateParam('ttsVoice', e.target.value)} style={selectStyle}>
                  {ttsVoiceOptions.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                </select>
              </CapGroup>
              <CapGroup label="原声音量">
                <RangeRow value={params.originalVolume} min={0} max={1} step={0.05}
                  onChange={(v) => updateParam('originalVolume', v)}
                  format={(v) => `${Math.round(v * 100)}%`} />
              </CapGroup>
              <CapGroup label="配音音量比">
                <RangeRow value={params.ttsVolumeRatio} min={0} max={1} step={0.05}
                  onChange={(v) => updateParam('ttsVolumeRatio', v)}
                  format={(v) => `${Math.round(v * 100)}%`} />
              </CapGroup>
              <div style={{ gridColumn: '1 / -1' }}>
                <CapGroup label="配音延迟">
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span style={{ fontSize: 10, color: 'var(--muted)', whiteSpace: 'nowrap' }}>提前 5s</span>
                    <input type="range" min={-5} max={5} step={0.1} value={params.ttsDelay}
                      onChange={(e) => updateParam('ttsDelay', parseFloat(e.target.value))}
                      style={{ flex: 1 }} />
                    <span style={{ fontSize: 10, color: 'var(--muted)', whiteSpace: 'nowrap' }}>延后 5s</span>
                    <span style={{ fontSize: 12, color: 'var(--fg)', minWidth: 40, textAlign: 'right', fontVariantNumeric: 'tabular-nums', fontWeight: 500 }}>
                      {params.ttsDelay === 0 ? '0s' : (params.ttsDelay > 0 ? `+${params.ttsDelay}s` : `${params.ttsDelay}s`)}
                    </span>
                  </div>
                </CapGroup>
              </div>
            </div>
          </CollapsiblePanel>

          {/* ── 模型参数 (collapsible, dynamic) ─────── */}
          <CollapsiblePanel
            title="模型参数"
            hint={params.ttsEngine === 'edge' ? 'Edge-TTS · 云端服务，无需额外配置' : 'Qwen3-TTS · 本地 GPU 模型，支持设计/克隆'}
            open={modelExpanded}
            onToggle={toggleModel}
          >
            {params.ttsEngine === 'edge' ? (
              <div style={{
                display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6,
                padding: 20, textAlign: 'center', color: 'var(--muted)', fontSize: 12,
              }}>
                <InfoIcon />
                <span>Edge-TTS 是云端服务，使用固定音色列表，无需额外配置。</span>
                <span>切换到 Qwen3-TTS 可使用音色设计、克隆等高级功能。</span>
              </div>
            ) : (
              <Qwen3ModelParams params={params} updateParam={updateParam} />
            )}
          </CollapsiblePanel>

          {/* ── 高级参数 (collapsible) ──────────────── */}
          <CollapsiblePanel
            title="高级参数"
            hint="人声分离 / 语速 / 输出"
            open={advExpanded}
            onToggle={toggleAdv}
          >
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
              <CapGroup label="人声分离">
                <select value={params.useVocalSeparator ? 'on' : 'off'}
                  onChange={(e) => updateParam('useVocalSeparator', e.target.value === 'on')}
                  style={selectStyle}>
                  <option value="on">开启</option>
                  <option value="off">关闭</option>
                </select>
              </CapGroup>
              <CapGroup label="分离模型">
                <select value={params.vocalModel}
                  onChange={(e) => updateParam('vocalModel', e.target.value)}
                  style={selectStyle}>
                  {VOCAL_MODEL_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                </select>
              </CapGroup>
              <CapGroup label="语速">
                <RangeRow value={params.ttsSpeed} min={0.5} max={2.0} step={0.1}
                  onChange={(v) => updateParam('ttsSpeed', v)}
                  format={(v) => `${v.toFixed(1)}×`} />
              </CapGroup>
              <CapGroup label="跳过已存在">
                <select value={params.skipExisting ? 'yes' : 'no'}
                  onChange={(e) => updateParam('skipExisting', e.target.value === 'yes')}
                  style={selectStyle}>
                  <option value="yes">是</option>
                  <option value="no">否</option>
                </select>
              </CapGroup>
              <div style={{ gridColumn: '1 / -1' }}>
                <CapGroup label="输出目录">
                  <div style={{ display: 'flex', gap: 6 }}>
                    <input type="text" defaultValue="output/" placeholder="默认: output/" style={{ ...selectStyle, flex: 1 }} />
                    <button style={btnSmStyle}>选择</button>
                  </div>
                </CapGroup>
              </div>
            </div>
          </CollapsiblePanel>
        </div>

        {/* ── Right Sidebar ────────────────────────── */}
        <aside style={{
          background: 'var(--surface)',
          borderLeft: '1px solid var(--border)',
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
        }}>

          {/* Task List */}
          <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', borderBottom: '1px solid var(--border)' }}>
            <div style={{
              padding: '12px 16px', fontSize: 11, fontWeight: 600, color: 'var(--muted)',
              textTransform: 'uppercase', letterSpacing: '0.05em',
              borderBottom: '1px solid var(--border)',
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            }}>
              <span>进行中的任务</span>
              <span style={{ fontSize: 11, fontWeight: 500, color: 'var(--accent)', textTransform: 'none', letterSpacing: 0, cursor: 'pointer' }}>
                查看全部
              </span>
            </div>
            <div style={{ flex: 1, overflowY: 'auto', padding: '8px 0' }}>
              {recentTasks.length === 0 ? (
                <div style={{ padding: '20px 16px', textAlign: 'center', fontSize: 12, color: 'var(--muted)' }}>
                  暂无任务
                </div>
              ) : (
                recentTasks.map((task) => (
                  <div key={task.id} style={{
                    padding: '8px 16px', display: 'flex', alignItems: 'center', gap: 10,
                    fontSize: 12, borderBottom: '1px solid var(--border)',
                  }}>
                    <span style={{
                      width: 7, height: 7, borderRadius: '50%', flexShrink: 0,
                      background: task.status === 'running' ? 'oklch(65% 0.16 255)'
                        : task.status === 'pending' ? 'oklch(70% 0.08 60)'
                          : task.status === 'completed' ? 'oklch(60% 0.16 145)'
                            : 'oklch(55% 0.18 25)',
                    }} />
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontWeight: 500, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                        {task.sourceName}
                      </div>
                      <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 1 }}>
                        {task.status === 'running' ? `${task.message || '运行中'} · ${Math.round((task.progress ?? 0) * 100)}%`
                          : task.status === 'pending' ? '排队中'
                            : task.status === 'completed' ? '已完成'
                              : '失败'}
                      </div>
                    </div>
                  </div>
                ))
              )}
            </div>
            <div style={{ display: 'flex', gap: 8, padding: '8px 16px', borderTop: '1px solid var(--border)' }}>
              {runningCount > 0 && <MiniPill type="running">{runningCount} 运行</MiniPill>}
              {pendingCount > 0 && <MiniPill type="pending">{pendingCount} 排队</MiniPill>}
              {completedCount > 0 && <MiniPill type="done">{completedCount} 完成</MiniPill>}
            </div>
          </div>

          {/* Params Summary */}
          <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
            <div style={{
              padding: '12px 16px', fontSize: 11, fontWeight: 600, color: 'var(--muted)',
              textTransform: 'uppercase', letterSpacing: '0.05em',
              borderBottom: '1px solid var(--border)',
            }}>
              当前选择的参数
            </div>
            <div style={{ flex: 1, overflowY: 'auto', padding: '12px 16px' }}>
              <ParamRow label="预设" value={presets.find(p => p.id === preset)?.label ?? preset} />
              <ParamRow label="ASR" value={params.asrModel} />
              <ParamRow label="TTS" value={params.ttsEngine === 'edge' ? 'Edge-TTS' : 'Qwen3-TTS'} />
              <ParamRow label="音色" value={params.ttsVoice.split('-').pop() ?? params.ttsVoice} />
              <ParamRow label="源 → 目标" value={`${langLabel(params.sourceLang)} → ${langLabel(params.targetLang)}`} />
              <ParamRow label="翻译" value={params.translateProvider === 'deepseek' ? 'DeepSeek' : 'OpenAI'} />
              <ParamRow label="人声分离" value={params.useVocalSeparator ? '开启' : '关闭'} />
            </div>
          </div>
        </aside>
      </div>
    </div>
  )
}

// ── Qwen3 Model Params ─────────────────────────────────

function Qwen3ModelParams({ params, updateParam }: {
  params: { ttsVoice: string; ttsSpeed: number }
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  updateParam: (key: any, value: any) => void
}) {
  const [subModel, setSubModel] = useState<'custom' | 'design' | 'clone'>('custom')

  return (
    <>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr', gap: 12 }}>
        <CapGroup label="TTS 子模型">
          <select value={subModel} onChange={(e) => setSubModel(e.target.value as typeof subModel)} style={selectStyle}>
            <option value="custom">CustomVoice — 使用预设 speaker + instruct 控制音色</option>
            <option value="design">VoiceDesign — 自然语言描述生成新音色</option>
            <option value="clone">CustomVoice (克隆) — 从参考音频提取音色</option>
          </select>
        </CapGroup>
      </div>

      {subModel === 'custom' && (
        <div style={{ marginTop: 12, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          <CapGroup label="Speaker (预设角色)">
            <select value={params.ttsVoice} onChange={(e) => updateParam('ttsVoice', e.target.value)} style={selectStyle}>
              <option value="Serena">Serena</option>
              <option value="Vivian">Vivian</option>
              <option value="Chelsie">Chelsie</option>
              <option value="default">default</option>
            </select>
          </CapGroup>
          <CapGroup label="Instruct (语气指令)">
            <input type="text" defaultValue="用温柔的语气说话" placeholder="描述想要的语气风格" style={selectStyle} />
          </CapGroup>
        </div>
      )}

      {subModel === 'design' && (
        <div style={{ marginTop: 12, display: 'grid', gridTemplateColumns: '1fr', gap: 12 }}>
          <CapGroup label="音色描述 (自然语言)">
            <input type="text" placeholder="例如：年轻女性，温柔甜美，语速适中，带有轻微气声" style={selectStyle} />
          </CapGroup>
          <CapGroup label="参考文本">
            <input type="text" defaultValue="大家好，欢迎收听今天的节目。" placeholder="用于试听的文本" style={selectStyle} />
          </CapGroup>
        </div>
      )}

      {subModel === 'clone' && (
        <div style={{ marginTop: 12, display: 'grid', gridTemplateColumns: '1fr', gap: 12 }}>
          <CapGroup label="参考音频文件">
            <div style={{ display: 'flex', gap: 6 }}>
              <input type="text" placeholder="拖入或选择参考音频 (3-10秒最佳)" style={{ ...selectStyle, flex: 1 }} />
              <button style={btnSmStyle}>选择</button>
            </div>
          </CapGroup>
          <CapGroup label="参考文本">
            <input type="text" placeholder="参考音频中说的文字内容" style={selectStyle} />
          </CapGroup>
        </div>
      )}
    </>
  )
}

// ── Sub-components ──────────────────────────────────────

function SelectorBox({ label, value, onChange, options }: {
  label: string; value: string; onChange: (v: string) => void
  options: { value: string; label: string }[]
}) {
  return (
    <div style={{
      background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 'var(--radius)',
      padding: '14px 16px',
    }}>
      <label style={{
        display: 'block', fontSize: 11, fontWeight: 600, color: 'var(--muted)',
        textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: 8,
      }}>
        {label}
      </label>
      <select value={value} onChange={(e) => onChange(e.target.value)} style={selectStyle}>
        {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    </div>
  )
}

function CollapsiblePanel({ title, hint, open, onToggle, children }: {
  title: string; hint: string; open: boolean; onToggle: () => void; children: React.ReactNode
}) {
  return (
    <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 'var(--radius)' }}>
      <div
        onClick={onToggle}
        style={{
          padding: '12px 16px', fontSize: 13, fontWeight: 600, color: 'var(--fg)',
          borderBottom: open ? '1px solid var(--border)' : 'none',
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          cursor: 'pointer', userSelect: 'none',
        }}
      >
        <span>{title}</span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{ fontSize: 11, fontWeight: 400, color: 'var(--muted)' }}>{hint}</span>
          <ChevronIcon open={open} />
        </span>
      </div>
      {open && <div style={{ padding: 16 }}>{children}</div>}
    </div>
  )
}

function CapGroup({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label style={{
        display: 'block', fontSize: 11, fontWeight: 500, color: 'var(--muted)',
        marginBottom: 4, letterSpacing: '0.03em',
      }}>
        {label}
      </label>
      {children}
    </div>
  )
}

function RangeRow({ value, min, max, step, onChange, format }: {
  value: number; min: number; max: number; step: number
  onChange: (v: number) => void; format: (v: number) => string
}) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <input type="range" min={min} max={max} step={step} value={value}
        onChange={(e) => onChange(parseFloat(e.target.value))}
        style={{ flex: 1 }} />
      <span style={{ fontSize: 12, color: 'var(--fg)', minWidth: 40, textAlign: 'right', fontVariantNumeric: 'tabular-nums', fontWeight: 500 }}>
        {format(value)}
      </span>
    </div>
  )
}

function MiniPill({ type, children }: { type: 'running' | 'pending' | 'done'; children: React.ReactNode }) {
  const bg = { running: 'oklch(93% 0.04 255)', pending: 'oklch(95% 0.01 60)', done: 'oklch(93% 0.04 145)' }
  const fg = { running: 'oklch(45% 0.14 255)', pending: 'oklch(45% 0.06 60)', done: 'oklch(40% 0.12 145)' }
  return (
    <span style={{ fontSize: 11, fontWeight: 500, padding: '2px 7px', borderRadius: 10, background: bg[type], color: fg[type] }}>
      {children}
    </span>
  )
}

function ParamRow({ label, value }: { label: string; value: string }) {
  return (
    <div style={{
      display: 'flex', justifyContent: 'space-between', alignItems: 'center',
      fontSize: 12, padding: '5px 0', borderBottom: '1px solid var(--border)',
    }}>
      <span style={{ color: 'var(--muted)' }}>{label}</span>
      <span style={{ fontWeight: 500 }}>{value}</span>
    </div>
  )
}

function langLabel(code: string): string {
  return { ja: '日语', zh: '中文', en: '英语' }[code] ?? code
}

// ── Shared styles ───────────────────────────────────────

const selectStyle: React.CSSProperties = {
  fontFamily: 'var(--font-body)',
  fontSize: 13,
  padding: '7px 10px',
  borderRadius: 'var(--radius-sm)',
  border: '1px solid var(--border)',
  background: 'var(--surface)',
  color: 'var(--fg)',
  width: '100%',
}

const btnSmStyle: React.CSSProperties = {
  fontFamily: 'var(--font-body)',
  fontSize: 11,
  padding: '6px 10px',
  borderRadius: 'var(--radius-sm)',
  border: '1px solid var(--border)',
  background: 'var(--surface)',
  color: 'var(--fg)',
  cursor: 'pointer',
  whiteSpace: 'nowrap',
}
