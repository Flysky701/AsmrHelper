import { useEffect } from 'react'
import { useWorkbenchStore } from '@/stores/workbenchStore'
import { useTaskStore } from '@/stores/taskStore'
import { useLogStore } from '@/stores/logStore'
import { useFileSelector } from '@/hooks/useFileSelector'
import { useTaskPolling } from '@/hooks/useTaskPolling'
import { pipelineApi } from '@/api/pipeline'
import type { PipelineRunRequest } from '@/api/types'
import {
  NeuButton,
  NeuCard,
  NeuInput,
  NeuSelect,
  NeuToggle,
  NeuSlider,
} from '@/components/ui'
import FileList from '@/components/shared/FileList'

const LANG_OPTIONS = [
  { value: 'ja', label: '日语' },
  { value: 'zh', label: '中文' },
  { value: 'en', label: '英语' },
]

const TTS_ENGINE_OPTIONS = [
  { value: 'edge', label: 'Edge TTS (免费)' },
  { value: 'qwen3', label: 'Qwen3 TTS (GPU)' },
]

const TRANSLATE_PROVIDER_OPTIONS = [
  { value: 'deepseek', label: 'DeepSeek' },
  { value: 'openai', label: 'OpenAI' },
]

const ASR_MODEL_OPTIONS = [
  { value: 'tiny', label: 'Tiny (最快)' },
  { value: 'base', label: 'Base (推荐)' },
  { value: 'small', label: 'Small' },
  { value: 'medium', label: 'Medium' },
  { value: 'large-v3', label: 'Large V3 (最准)' },
]

const VOCAL_MODEL_OPTIONS = [
  { value: 'htdemucs', label: 'HTDemucs' },
  { value: 'htdemucs_ft', label: 'HTDemucs FT' },
]

export default function Workbench() {
  // Enable task polling for real-time progress
  useTaskPolling(3000)

  const {
    selectedFiles,
    preset,
    presets,
    params,
    layer2Expanded,
    layer3Expanded,
    setFiles,
    removeFile,
    setPreset,
    updateParam,
    toggleLayer2,
    toggleLayer3,
  } = useWorkbenchStore()

  const addTask = useTaskStore((s) => s.addTask)
  const addLog = useLogStore((s) => s.addLog)
  const { selectFiles } = useFileSelector()

  // Load presets on mount
  useEffect(() => {
    pipelineApi.presets().then((res) => {
      useWorkbenchStore.getState().setPresets(res.presets)
      if (res.presets.length > 0 && !preset) {
        setPreset(res.presets[0]!)
      }
    }).catch(() => {
      // Silently fail — presets will just be empty
    })
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const handleSelectFiles = async () => {
    const files = await selectFiles()
    if (files.length > 0) {
      setFiles([...selectedFiles, ...files.filter((f) => !selectedFiles.includes(f))])
    }
  }

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

      addLog({ level: 'info', content: `任务已创建: ${filePath}`, taskId })

      // Fire API call (don't await — let it run in background)
      pipelineApi
        .run(request)
        .then((res) => {
          useTaskStore.getState().updateTask(taskId, {
            status: res.success ? 'completed' : 'failed',
            progress: res.success ? 1 : 0,
            artifacts: res.artifacts
              ? { files: res.artifacts.files, primaryOutput: res.artifacts.primary_output ?? undefined }
              : undefined,
            errorMessage: res.error_message ?? undefined,
          })
          addLog({
            level: res.success ? 'info' : 'error',
            content: res.success
              ? `任务完成: ${res.input_path}`
              : `任务失败: ${res.error_message}`,
            taskId,
          })
        })
        .catch((err) => {
          useTaskStore.getState().updateTask(taskId, {
            status: 'failed',
            errorMessage: String(err),
          })
          addLog({ level: 'error', content: `任务异常: ${String(err)}`, taskId })
        })
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px', maxWidth: '900px' }}>
      {/* ── Layer 1: File Selection + Preset ── */}
      <NeuCard>
        <div style={{ display: 'flex', gap: '12px', alignItems: 'flex-end', flexWrap: 'wrap' }}>
          <NeuButton onClick={handleSelectFiles}>选择文件</NeuButton>
          <div style={{ flex: 1, minWidth: '200px' }}>
            <NeuSelect
              label="预设模板"
              value={preset}
              onChange={(e) => setPreset(e.target.value)}
              options={[
                { value: '', label: '选择预设...' },
                ...presets.map((p) => ({ value: p, label: p })),
              ]}
            />
          </div>
        </div>
        {selectedFiles.length > 0 && (
          <div style={{ marginTop: '12px' }}>
            <FileList files={selectedFiles} onRemove={removeFile} />
          </div>
        )}
      </NeuCard>

      {/* ── Layer 2: Parameters ── */}
      <NeuCard>
        <div
          onClick={toggleLayer2}
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            cursor: 'pointer',
            marginBottom: layer2Expanded ? '16px' : 0,
          }}
        >
          <span style={{ fontWeight: 600, color: 'var(--text-primary)' }}>
            参数配置
          </span>
          <span style={{ color: 'var(--text-secondary)', fontSize: '0.875rem' }}>
            {layer2Expanded ? '▲' : '▼'}
          </span>
        </div>
        {layer2Expanded && (
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))',
              gap: '16px',
            }}
          >
            <NeuSelect
              label="源语言"
              value={params.sourceLang}
              onChange={(e) => updateParam('sourceLang', e.target.value)}
              options={LANG_OPTIONS}
            />
            <NeuSelect
              label="目标语言"
              value={params.targetLang}
              onChange={(e) => updateParam('targetLang', e.target.value)}
              options={LANG_OPTIONS}
            />
            <NeuSelect
              label="TTS 引擎"
              value={params.ttsEngine}
              onChange={(e) => updateParam('ttsEngine', e.target.value)}
              options={TTS_ENGINE_OPTIONS}
            />
            <NeuInput
              label="TTS 音色"
              value={params.ttsVoice}
              onChange={(e) => updateParam('ttsVoice', e.target.value)}
              placeholder="zh-CN-XiaoxiaoNeural"
            />
            <NeuSelect
              label="ASR 模型"
              value={params.asrModel}
              onChange={(e) => updateParam('asrModel', e.target.value)}
              options={ASR_MODEL_OPTIONS}
            />
            <NeuSelect
              label="翻译提供商"
              value={params.translateProvider}
              onChange={(e) => updateParam('translateProvider', e.target.value)}
              options={TRANSLATE_PROVIDER_OPTIONS}
            />
            <NeuToggle
              checked={params.useVocalSeparator}
              onChange={(val) => updateParam('useVocalSeparator', val)}
              label="人声分离"
            />
            {params.useVocalSeparator && (
              <NeuSelect
                label="分离模型"
                value={params.vocalModel}
                onChange={(e) => updateParam('vocalModel', e.target.value)}
                options={VOCAL_MODEL_OPTIONS}
              />
            )}
            <div style={{ gridColumn: '1 / -1' }}>
              <NeuSlider
                label="原声音量"
                value={params.originalVolume}
                min={0}
                max={1}
                step={0.05}
                onChange={(v) => updateParam('originalVolume', v)}
                showValue
                formatValue={(v) => v.toFixed(2)}
              />
            </div>
            <div style={{ gridColumn: '1 / -1' }}>
              <NeuSlider
                label="TTS 音量比例"
                value={params.ttsVolumeRatio}
                min={0}
                max={1}
                step={0.05}
                onChange={(v) => updateParam('ttsVolumeRatio', v)}
                showValue
                formatValue={(v) => v.toFixed(2)}
              />
            </div>
            <div style={{ gridColumn: '1 / -1' }}>
              <NeuSlider
                label="TTS 延迟 (秒)"
                value={params.ttsDelay}
                min={0}
                max={2}
                step={0.1}
                onChange={(v) => updateParam('ttsDelay', v)}
                showValue
                formatValue={(v) => v.toFixed(1) + 's'}
              />
            </div>
          </div>
        )}
      </NeuCard>

      {/* ── Layer 3: Advanced Options ── */}
      <NeuCard>
        <div
          onClick={toggleLayer3}
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            cursor: 'pointer',
            marginBottom: layer3Expanded ? '16px' : 0,
          }}
        >
          <span style={{ fontWeight: 600, color: 'var(--text-primary)' }}>
            高级选项
          </span>
          <span style={{ color: 'var(--text-secondary)', fontSize: '0.875rem' }}>
            {layer3Expanded ? '▲' : '▼'}
          </span>
        </div>
        {layer3Expanded && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
            <NeuToggle
              checked={params.skipExisting}
              onChange={(val) => updateParam('skipExisting', val)}
              label="跳过已存在的输出文件"
            />
            <NeuSlider
              label="TTS 语速"
              value={params.ttsSpeed}
              min={0.5}
              max={2.0}
              step={0.1}
              onChange={(v) => updateParam('ttsSpeed', v)}
              showValue
              formatValue={(v) => v.toFixed(1) + 'x'}
            />
          </div>
        )}
      </NeuCard>

      {/* ── Action Button ── */}
      <div style={{ display: 'flex', justifyContent: 'center', padding: '8px 0' }}>
        <NeuButton
          variant="primary"
          size="lg"
          disabled={selectedFiles.length === 0}
          onClick={handleExecute}
        >
          创建任务并执行
        </NeuButton>
      </div>
    </div>
  )
}
