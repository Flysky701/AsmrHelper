import { useEffect, useMemo, useState } from 'react'
import type { CSSProperties } from 'react'

import { toolsApi } from '@/api/tools'
import type { ToolDescriptorResponse } from '@/api/types'
import { FILE_FILTERS, useFileSelector } from '@/hooks/useFileSelector'
import { useNavStore } from '@/stores/navStore'
import { useTaskStore } from '@/stores/taskStore'
import type { JobType, TaskStatus } from '@/stores/taskStore'

type ToolType =
  | 'tool.separate'
  | 'tool.convert'
  | 'tool.split'
  | 'tool.translate_subtitle'
  | 'tool.volume_preview'

const TOOLS: Array<{
  id: ToolType
  label: string
  description: string
  input: 'audio' | 'subtitle'
  jobType: JobType
}> = [
  { id: 'tool.separate', label: '人声分离', description: '提取人声并登记可试听产物', input: 'audio', jobType: 'separate' },
  { id: 'tool.convert', label: '格式转换', description: '转换格式、采样率和声道', input: 'audio', jobType: 'convert' },
  { id: 'tool.split', label: '按字幕切分', description: '根据字幕时间轴切分音频', input: 'audio', jobType: 'split' },
  { id: 'tool.translate_subtitle', label: '字幕翻译', description: '翻译字幕并保留时间轴', input: 'subtitle', jobType: 'translate-subtitle' },
  { id: 'tool.volume_preview', label: '音量分析', description: '计算 RMS 并给出混音比例建议', input: 'audio', jobType: 'volume-preview' },
]

const surface: CSSProperties = {
  background: 'var(--surface)',
  border: '1px solid var(--border)',
  borderRadius: 'var(--radius-card)',
  boxShadow: 'var(--shadow-panel)',
}

const inputStyle: CSSProperties = {
  width: '100%',
  minHeight: 38,
  padding: '8px 10px',
  border: '1px solid var(--border)',
  borderRadius: 'var(--radius-sm)',
  background: 'var(--surface)',
  color: 'var(--fg)',
  fontFamily: 'inherit',
}

function fileName(path: string) {
  return path.split(/[/\\]/).pop() || path
}

export default function AudioTools() {
  const { selectFiles, selectFolder } = useFileSelector()
  const setPage = useNavStore((state) => state.setPage)
  const addTask = useTaskStore((state) => state.addTask)
  const updateTask = useTaskStore((state) => state.updateTask)

  const [catalog, setCatalog] = useState<ToolDescriptorResponse[]>([])
  const [catalogLoading, setCatalogLoading] = useState(true)
  const [catalogAvailable, setCatalogAvailable] = useState(false)
  const [selectedTool, setSelectedTool] = useState<ToolType>('tool.convert')
  const [inputPath, setInputPath] = useState('')
  const [companionPath, setCompanionPath] = useState('')
  const [ttsPath, setTtsPath] = useState('')
  const [outputDir, setOutputDir] = useState('')
  const [outputPath, setOutputPath] = useState('')
  const [format, setFormat] = useState('wav')
  const [sampleRate, setSampleRate] = useState(44100)
  const [channels, setChannels] = useState(2)
  const [padding, setPadding] = useState(0.1)
  const [sourceLang, setSourceLang] = useState('ja')
  const [targetLang, setTargetLang] = useState('zh')
  const [originalVolume, setOriginalVolume] = useState(0.85)
  const [ttsRatio, setTtsRatio] = useState(0.5)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    toolsApi.list()
      .then((response) => {
        setCatalog(response.tools)
        setCatalogAvailable(true)
      })
      .catch((loadError) => {
        setCatalogAvailable(false)
        setError(`读取工具目录失败：${String(loadError)}`)
      })
      .finally(() => setCatalogLoading(false))
  }, [])

  const selected = TOOLS.find((tool) => tool.id === selectedTool) ?? TOOLS[0]!
  const supported = useMemo(() => new Set(catalog.map((tool) => tool.task_type)), [catalog])

  const chooseInput = async () => {
    const filter = selected.input === 'subtitle' ? FILE_FILTERS.subtitle : FILE_FILTERS.audio
    const files = await selectFiles({ multiple: false, filters: [filter] })
    if (files[0]) {
      setInputPath(files[0])
      setError('')
    }
  }

  const chooseCompanion = async () => {
    const files = await selectFiles({ multiple: false, filters: [FILE_FILTERS.subtitle] })
    if (files[0]) setCompanionPath(files[0])
  }

  const chooseTts = async () => {
    const files = await selectFiles({ multiple: false, filters: [FILE_FILTERS.audio] })
    if (files[0]) setTtsPath(files[0])
  }

  const chooseOutputDir = async () => {
    const directory = await selectFolder()
    if (directory) setOutputDir(directory)
  }

  const executionProfile = (): Record<string, unknown> => {
    if (selectedTool === 'tool.separate') return { model: 'htdemucs', output_dir: outputDir || undefined }
    if (selectedTool === 'tool.convert') {
      return {
        output_path: outputPath || undefined,
        output_dir: outputDir || undefined,
        target_format: format,
        sample_rate: sampleRate,
        channels,
      }
    }
    if (selectedTool === 'tool.split') return { output_dir: outputDir || undefined, padding }
    if (selectedTool === 'tool.translate_subtitle') {
      return {
        output_path: outputPath || undefined,
        provider: 'deepseek',
        source_lang: sourceLang,
        target_lang: targetLang,
        bilingual: true,
      }
    }
    return {
      tts_path: ttsPath || undefined,
      original_volume: originalVolume,
      tts_volume_ratio: ttsRatio,
    }
  }

  const submit = async () => {
    if (!inputPath) {
      setError('请先选择输入文件')
      return
    }
    if (selectedTool === 'tool.split' && !companionPath) {
      setError('按字幕切分需要字幕文件')
      return
    }

    setSubmitting(true)
    setError('')
    const profile = executionProfile()
    const localTaskId = addTask({
      jobType: selected.jobType,
      sourceName: fileName(inputPath),
      sourcePath: inputPath,
      params: { task_type: selectedTool, ...profile },
    })
    updateTask(localTaskId, { message: '正在创建工具任务' })

    try {
      const remote = await toolsApi.create({
        task_type: selectedTool,
        input_path: inputPath,
        companion_paths: companionPath ? [companionPath] : [],
        execution_profile: profile,
      })
      updateTask(localTaskId, {
        serverTaskId: remote.task_id,
        status: remote.state as TaskStatus,
        stage: remote.stage ?? undefined,
        progress: Math.round(remote.progress * 100),
        message: remote.message || '后端已接管工具任务',
        detail: remote.detail,
      })
      setPage('task-center')
    } catch (submitError) {
      updateTask(localTaskId, {
        status: 'failed',
        message: '工具任务创建失败',
        errorMessage: String(submitError),
      })
      setError(`提交失败：${String(submitError)}`)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div style={{ height: '100%', overflow: 'auto', padding: 24 }}>
      <header style={{ marginBottom: 20 }}>
        <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--accent)', letterSpacing: '0.08em', textTransform: 'uppercase' }}>
          Task-driven Tools
        </div>
        <h1 style={{ marginTop: 8, fontSize: 26, fontFamily: 'var(--font-display)' }}>音频工具</h1>
        <p style={{ marginTop: 8, color: 'var(--muted)' }}>
          每次操作都会创建独立任务；进度、错误和产物统一在任务中心查看。
        </p>
      </header>

      {error ? (
        <div style={{ marginBottom: 16, padding: '10px 14px', color: 'var(--error)', background: 'var(--error-soft)', borderRadius: 'var(--radius-sm)' }}>
          {error}
        </div>
      ) : null}

      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(280px, 360px) minmax(0, 1fr)', gap: 20 }}>
        <section style={{ ...surface, padding: 16, alignSelf: 'start' }}>
          <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 12 }}>选择工具</div>
          <div style={{ display: 'grid', gap: 8 }}>
            {TOOLS.map((tool) => {
              const available = catalogAvailable && supported.has(tool.id)
              const active = selectedTool === tool.id
              return (
                <button
                  key={tool.id}
                  type="button"
                  disabled={!available}
                  onClick={() => {
                    setSelectedTool(tool.id)
                    setInputPath('')
                    setCompanionPath('')
                    setError('')
                  }}
                  style={{
                    padding: '12px 14px',
                    textAlign: 'left',
                    border: active ? '1px solid var(--accent)' : '1px solid var(--border)',
                    borderRadius: 'var(--radius-button)',
                    background: active ? 'var(--accent-soft)' : 'var(--surface)',
                    color: 'var(--fg)',
                    cursor: available ? 'pointer' : 'not-allowed',
                    opacity: available ? 1 : 0.45,
                  }}
                >
                  <div style={{ fontSize: 13, fontWeight: 700 }}>{tool.label}</div>
                  <div style={{ marginTop: 4, fontSize: 12, color: 'var(--muted)' }}>{tool.description}</div>
                </button>
              )
            })}
          </div>
        </section>

        <section style={{ ...surface, padding: 20 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'center' }}>
            <div>
              <div style={{ fontSize: 18, fontWeight: 700 }}>{selected.label}</div>
              <div style={{ marginTop: 4, fontSize: 12, color: 'var(--muted)' }}>{selected.id}</div>
            </div>
            <button type="button" onClick={chooseInput} style={{ ...inputStyle, width: 'auto', cursor: 'pointer' }}>
              选择{selected.input === 'subtitle' ? '字幕' : '音频'}
            </button>
          </div>

          <div style={{ marginTop: 18, padding: '12px 14px', background: 'var(--panel-muted)', borderRadius: 'var(--radius-sm)', wordBreak: 'break-all' }}>
            <div style={{ fontSize: 11, color: 'var(--muted)' }}>输入文件</div>
            <div style={{ marginTop: 5, fontSize: 13 }}>{inputPath || '尚未选择'}</div>
          </div>

          <div style={{ marginTop: 18, display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: 14 }}>
            {selectedTool === 'tool.convert' ? (
              <>
                <label>目标格式<select style={inputStyle} value={format} onChange={(event) => setFormat(event.target.value)}><option value="wav">WAV</option><option value="mp3">MP3</option><option value="flac">FLAC</option><option value="ogg">OGG</option></select></label>
                <label>采样率<select style={inputStyle} value={sampleRate} onChange={(event) => setSampleRate(Number(event.target.value))}><option value={16000}>16000 Hz</option><option value={24000}>24000 Hz</option><option value={44100}>44100 Hz</option><option value={48000}>48000 Hz</option></select></label>
                <label>声道<select style={inputStyle} value={channels} onChange={(event) => setChannels(Number(event.target.value))}><option value={1}>单声道</option><option value={2}>双声道</option></select></label>
                <label>输出文件（可选）<input style={inputStyle} value={outputPath} onChange={(event) => setOutputPath(event.target.value)} placeholder="留空则自动命名" /></label>
              </>
            ) : null}

            {selectedTool === 'tool.split' ? (
              <>
                <label>字幕文件<button type="button" style={inputStyle} onClick={chooseCompanion}>{companionPath ? fileName(companionPath) : '选择字幕'}</button></label>
                <label>前后留白（秒）<input style={inputStyle} type="number" min={0} max={2} step={0.05} value={padding} onChange={(event) => setPadding(Number(event.target.value))} /></label>
              </>
            ) : null}

            {selectedTool === 'tool.translate_subtitle' ? (
              <>
                <label>源语言<select style={inputStyle} value={sourceLang} onChange={(event) => setSourceLang(event.target.value)}><option value="ja">日语</option><option value="zh">中文</option><option value="en">英语</option></select></label>
                <label>目标语言<select style={inputStyle} value={targetLang} onChange={(event) => setTargetLang(event.target.value)}><option value="zh">中文</option><option value="ja">日语</option><option value="en">英语</option></select></label>
                <label style={{ gridColumn: '1 / -1' }}>输出文件（可选）<input style={inputStyle} value={outputPath} onChange={(event) => setOutputPath(event.target.value)} placeholder="留空则在字幕旁自动命名" /></label>
              </>
            ) : null}

            {selectedTool === 'tool.volume_preview' ? (
              <>
                <label>TTS 音频（可选）<button type="button" style={inputStyle} onClick={chooseTts}>{ttsPath ? fileName(ttsPath) : '选择 TTS 音频'}</button></label>
                <span />
                <label>原声音量<input style={inputStyle} type="number" min={0} max={2} step={0.05} value={originalVolume} onChange={(event) => setOriginalVolume(Number(event.target.value))} /></label>
                <label>TTS 音量比例<input style={inputStyle} type="number" min={0} max={2} step={0.05} value={ttsRatio} onChange={(event) => setTtsRatio(Number(event.target.value))} /></label>
              </>
            ) : null}

            {selectedTool === 'tool.separate' || selectedTool === 'tool.split' || selectedTool === 'tool.convert' ? (
              <label style={{ gridColumn: '1 / -1' }}>输出目录（可选）<button type="button" style={inputStyle} onClick={chooseOutputDir}>{outputDir || '使用工作区默认目录'}</button></label>
            ) : null}
          </div>

          <div style={{ marginTop: 22, display: 'flex', justifyContent: 'flex-end' }}>
            <button
              type="button"
              disabled={submitting || catalogLoading || !inputPath || !supported.has(selectedTool)}
              onClick={submit}
              style={{
                minHeight: 40,
                padding: '0 18px',
                border: '1px solid var(--accent)',
                borderRadius: 'var(--radius-button)',
                background: 'var(--accent)',
                color: 'white',
                fontWeight: 700,
                cursor: submitting ? 'not-allowed' : 'pointer',
                opacity: submitting ? 0.55 : 1,
              }}
            >
              {catalogLoading ? '正在读取工具...' : submitting ? '正在提交...' : '创建任务'}
            </button>
          </div>
        </section>
      </div>
    </div>
  )
}
