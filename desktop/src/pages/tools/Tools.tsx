import { useState } from 'react'
import { NeuCard, NeuButton, NeuInput } from '@/components/ui'
import { useTaskStore } from '@/stores/taskStore'
import { useLogStore } from '@/stores/logStore'
import { toolsApi } from '@/api/tools'
import { asrApi } from '@/api/asr'
import { ttsApi } from '@/api/tts'
import { subtitlesApi } from '@/api/subtitles'
import { useFileSelector } from '@/hooks/useFileSelector'

interface ToolDef {
  id: string
  name: string
  description: string
}

const TOOLS: ToolDef[] = [
  { id: 'separate', name: '人声分离', description: 'Demucs 分离人声/伴奏' },
  { id: 'convert', name: '音频转换', description: '格式互转 (WAV/MP3/FLAC/OGG/M4A)' },
  { id: 'split', name: '音频切分', description: '按字幕时间轴切分音频' },
  { id: 'translate-subtitle', name: '字幕翻译', description: '翻译字幕文件' },
  { id: 'asr', name: 'ASR 识别', description: '语音转文字' },
  { id: 'tts', name: 'TTS 合成', description: '文字转语音' },
  { id: 'script-to-vtt', name: '台本转VTT', description: 'PDF/TXT 转时间轴字幕' },
]

export default function Tools() {
  const [activeTool, setActiveTool] = useState<string | null>(null)
  const [filePath, setFilePath] = useState('')
  const [outputPath, setOutputPath] = useState('')
  const [extraParam, setExtraParam] = useState('')
  const addTask = useTaskStore((s) => s.addTask)
  const addLog = useLogStore((s) => s.addLog)
  const { selectFiles } = useFileSelector()

  const handleSelectFile = async () => {
    const files = await selectFiles()
    if (files.length > 0) setFilePath(files[0]!)
  }

  const handleExecute = async () => {
    if (!activeTool || !filePath) return

    const sourceName = filePath.split(/[/\\]/).pop() ?? filePath

    const taskId = addTask({
      jobType: activeTool as 'separate' | 'convert' | 'split' | 'translate-subtitle' | 'asr' | 'tts' | 'script-to-vtt',
      sourceName,
      sourcePath: filePath,
      params: { tool: activeTool, extraParam },
    })

    addLog({ level: 'info', content: `${activeTool} 任务已创建: ${sourceName}`, taskId })

    try {
      switch (activeTool) {
        case 'separate':
          await toolsApi.separate({ input_path: filePath })
          break
        case 'convert':
          await toolsApi.convert({ input_path: filePath, output_path: outputPath || filePath })
          break
        case 'split':
          await toolsApi.split({ audio_path: filePath, subtitle_path: extraParam, output_dir: outputPath || '.' })
          break
        case 'translate-subtitle':
          await toolsApi.translateSubtitle({ input_path: filePath })
          break
        case 'asr':
          await asrApi.transcribe({ input_path: filePath })
          break
        case 'tts':
          await ttsApi.synthesize({ input_path: filePath, output_path: outputPath || filePath })
          break
        case 'script-to-vtt':
          await subtitlesApi.scriptToVtt({ script_path: filePath })
          break
      }
      useTaskStore.getState().updateTask(taskId, { status: 'completed', progress: 1 })
      addLog({ level: 'info', content: `${activeTool} 完成: ${sourceName}`, taskId })
    } catch (err) {
      useTaskStore.getState().updateTask(taskId, { status: 'failed', errorMessage: String(err) })
      addLog({ level: 'error', content: `${activeTool} 失败: ${String(err)}`, taskId })
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))',
          gap: '12px',
        }}
      >
        {TOOLS.map((tool) => (
          <NeuCard
            key={tool.id}
            hoverable
            onClick={() => setActiveTool(activeTool === tool.id ? null : tool.id)}
            style={{
              border: activeTool === tool.id ? '2px solid var(--accent-text)' : '2px solid transparent',
            }}
          >
            <div style={{ fontWeight: 600, fontSize: '0.9375rem', color: 'var(--text-primary)' }}>
              {tool.name}
            </div>
            <div style={{ fontSize: '0.8125rem', color: 'var(--text-secondary)', marginTop: '4px' }}>
              {tool.description}
            </div>
          </NeuCard>
        ))}
      </div>

      {activeTool && (
        <NeuCard>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
            <div style={{ fontWeight: 600, color: 'var(--text-primary)' }}>
              {TOOLS.find((t) => t.id === activeTool)?.name}
            </div>
            <div style={{ display: 'flex', gap: '12px', alignItems: 'flex-end' }}>
              <NeuButton onClick={handleSelectFile}>选择文件</NeuButton>
              <div style={{ flex: 1 }}>
                <NeuInput
                  label="文件路径"
                  value={filePath}
                  onChange={(e) => setFilePath(e.target.value)}
                  placeholder="选择或输入文件路径..."
                />
              </div>
            </div>
            {activeTool === 'convert' && (
              <NeuInput
                label="输出路径"
                value={outputPath}
                onChange={(e) => setOutputPath(e.target.value)}
                placeholder="输出文件路径 (可选)"
              />
            )}
            {activeTool === 'split' && (
              <NeuInput
                label="字幕文件路径"
                value={extraParam}
                onChange={(e) => setExtraParam(e.target.value)}
                placeholder="字幕文件路径"
              />
            )}
            <NeuButton
              variant="primary"
              disabled={!filePath}
              onClick={handleExecute}
            >
              执行
            </NeuButton>
          </div>
        </NeuCard>
      )}
    </div>
  )
}
