import { useEffect, useState } from 'react'
import { NeuCard, NeuInput, NeuSelect, NeuSlider, NeuButton } from '@/components/ui'
import { settingsApi } from '@/api/settings'
import type { SettingsResponse } from '@/api/settings'

export default function Settings() {
  const [settings, setSettings] = useState<SettingsResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState('')
  const [testResult, setTestResult] = useState('')

  // Draft state for editing
  const [draft, setDraft] = useState({
    deepseekKey: '',
    openaiKey: '',
    provider: 'deepseek',
    ttsEngine: 'edge',
    ttsVoice: 'zh-CN-XiaoxiaoNeural',
    ttsSpeed: 1.0,
    asrModel: 'base',
    vocalModel: 'htdemucs',
    originalVolume: 0.85,
    ttsVolume: 0.5,
    ttsDelay: 0,
    outputDir: '',
    modelDir: '',
    tempDir: '',
  })

  useEffect(() => {
    loadSettings()
  }, [])

  const loadSettings = async () => {
    setLoading(true)
    try {
      const data = await settingsApi.get()
      setSettings(data)
      setDraft({
        deepseekKey: data.api.deepseek_api_key || '',
        openaiKey: data.api.openai_api_key || '',
        provider: data.api.provider || 'deepseek',
        ttsEngine: data.tts.engine || 'edge',
        ttsVoice: data.tts.voice || 'zh-CN-XiaoxiaoNeural',
        ttsSpeed: data.tts.speed ?? 1.0,
        asrModel: data.processing.asr_model || 'base',
        vocalModel: data.processing.vocal_model || 'htdemucs',
        originalVolume: data.processing.original_volume ?? 0.85,
        ttsVolume: data.processing.tts_volume ?? 0.5,
        ttsDelay: data.processing.tts_delay ?? 0,
        outputDir: data.paths.output_dir || '',
        modelDir: data.paths.model_cache_dir || '',
        tempDir: data.paths.temp_dir || '',
      })
    } catch (err) {
      setMessage(`加载设置失败: ${err}`)
    } finally {
      setLoading(false)
    }
  }

  const handleSave = async () => {
    setSaving(true)
    setMessage('')
    try {
      const updates: Partial<SettingsResponse> = {
        api: {
          provider: draft.provider,
          deepseek_api_key: draft.deepseekKey,
          openai_api_key: draft.openaiKey,
          deepseek_base_url: settings?.api.deepseek_base_url || 'https://api.deepseek.com',
          openai_base_url: settings?.api.openai_base_url || 'https://api.openai.com/v1',
        },
        tts: {
          engine: draft.ttsEngine,
          voice: draft.ttsVoice,
          speed: draft.ttsSpeed,
        },
        paths: {
          output_dir: draft.outputDir,
          vtt_dir: '',
          model_cache_dir: draft.modelDir,
          temp_dir: draft.tempDir,
        },
        processing: {
          original_volume: draft.originalVolume,
          tts_volume: draft.ttsVolume,
          tts_delay: draft.ttsDelay,
          vocal_model: draft.vocalModel,
          asr_model: draft.asrModel,
        },
      }

      // Validate first
      const validation = await settingsApi.validate(updates)
      if (!validation.valid) {
        setMessage(`验证失败: ${validation.errors.join('; ')}`)
        return
      }

      await settingsApi.update(updates)
      setMessage('设置已保存')
      loadSettings()
    } catch (err) {
      setMessage(`保存失败: ${err}`)
    } finally {
      setSaving(false)
    }
  }

  const handleTestProvider = async () => {
    setTestResult('')
    try {
      const result = await settingsApi.testProvider(draft.provider)
      setTestResult(result.success ? '✓ 连接成功' : `✗ ${result.errors.join('; ')}`)
    } catch (err) {
      setTestResult(`✗ 测试失败: ${err}`)
    }
  }

  if (loading) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '200px', color: 'var(--text-secondary)' }}>
        加载设置中...
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px', maxWidth: '600px' }}>
      {/* Status Message */}
      {message && (
        <div style={{
          padding: '8px 12px',
          borderRadius: '8px',
          background: message.includes('失败') ? 'rgba(239,68,68,0.1)' : 'rgba(34,197,94,0.1)',
          color: message.includes('失败') ? '#ef4444' : '#22c55e',
          fontSize: '0.875rem',
        }}>
          {message}
        </div>
      )}

      {/* API Config */}
      <div>
        <h2 style={{ fontSize: '1.125rem', fontWeight: 600, marginBottom: '12px', color: 'var(--text-primary)' }}>
          API 配置
        </h2>
        <NeuCard>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
            <NeuSelect
              label="默认翻译提供商"
              value={draft.provider}
              onChange={(e) => setDraft({ ...draft, provider: e.target.value })}
              options={[
                { value: 'deepseek', label: 'DeepSeek' },
                { value: 'openai', label: 'OpenAI' },
              ]}
            />
            <NeuInput
              label="DeepSeek API Key"
              type="password"
              value={draft.deepseekKey}
              onChange={(e) => setDraft({ ...draft, deepseekKey: e.target.value })}
              placeholder={settings?.api.deepseek_api_key ? '***configured***' : 'sk-...'}
            />
            <NeuInput
              label="OpenAI API Key"
              type="password"
              value={draft.openaiKey}
              onChange={(e) => setDraft({ ...draft, openaiKey: e.target.value })}
              placeholder={settings?.api.openai_api_key ? '***configured***' : 'sk-...'}
            />
            <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
              <NeuButton size="sm" onClick={handleTestProvider}>
                测试连接
              </NeuButton>
              {testResult && (
                <span style={{
                  fontSize: '0.8125rem',
                  color: testResult.startsWith('✓') ? '#22c55e' : '#ef4444',
                }}>
                  {testResult}
                </span>
              )}
            </div>
          </div>
        </NeuCard>
      </div>

      {/* Default Params */}
      <div>
        <h2 style={{ fontSize: '1.125rem', fontWeight: 600, marginBottom: '12px', color: 'var(--text-primary)' }}>
          默认参数
        </h2>
        <NeuCard>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
            <NeuSelect
              label="默认 TTS 引擎"
              value={draft.ttsEngine}
              onChange={(e) => setDraft({ ...draft, ttsEngine: e.target.value })}
              options={[
                { value: 'edge', label: 'Edge TTS' },
                { value: 'qwen3', label: 'Qwen3 TTS' },
              ]}
            />
            <NeuInput
              label="默认音色"
              value={draft.ttsVoice}
              onChange={(e) => setDraft({ ...draft, ttsVoice: e.target.value })}
            />
            <NeuSelect
              label="默认 ASR 模型"
              value={draft.asrModel}
              onChange={(e) => setDraft({ ...draft, asrModel: e.target.value })}
              options={[
                { value: 'tiny', label: 'Tiny' },
                { value: 'base', label: 'Base' },
                { value: 'small', label: 'Small' },
                { value: 'medium', label: 'Medium' },
                { value: 'large-v3', label: 'Large V3' },
              ]}
            />
            <NeuSelect
              label="默认人声分离模型"
              value={draft.vocalModel}
              onChange={(e) => setDraft({ ...draft, vocalModel: e.target.value })}
              options={[
                { value: 'htdemucs', label: 'HTDemucs' },
                { value: 'htdemucs_ft', label: 'HTDemucs FT' },
              ]}
            />
            <NeuSlider
              label="默认原声音量"
              value={draft.originalVolume}
              min={0} max={1} step={0.05}
              onChange={(v) => setDraft({ ...draft, originalVolume: v })}
              showValue formatValue={(v) => v.toFixed(2)}
            />
            <NeuSlider
              label="默认 TTS 音量比例"
              value={draft.ttsVolume}
              min={0} max={1} step={0.05}
              onChange={(v) => setDraft({ ...draft, ttsVolume: v })}
              showValue formatValue={(v) => v.toFixed(2)}
            />
          </div>
        </NeuCard>
      </div>

      {/* Path Config */}
      <div>
        <h2 style={{ fontSize: '1.125rem', fontWeight: 600, marginBottom: '12px', color: 'var(--text-primary)' }}>
          路径配置
        </h2>
        <NeuCard>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
            <NeuInput
              label="输出目录"
              value={draft.outputDir}
              onChange={(e) => setDraft({ ...draft, outputDir: e.target.value })}
              placeholder="默认: output/"
            />
            <NeuInput
              label="模型目录"
              value={draft.modelDir}
              onChange={(e) => setDraft({ ...draft, modelDir: e.target.value })}
              placeholder="默认: models/"
            />
            <NeuInput
              label="临时文件目录"
              value={draft.tempDir}
              onChange={(e) => setDraft({ ...draft, tempDir: e.target.value })}
              placeholder="默认: debug/"
            />
          </div>
        </NeuCard>
      </div>

      {/* Save */}
      <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
        <NeuButton variant="primary" disabled={saving} onClick={handleSave}>
          {saving ? '保存中...' : '保存设置'}
        </NeuButton>
      </div>

      {/* App Info */}
      <div>
        <h2 style={{ fontSize: '1.125rem', fontWeight: 600, marginBottom: '12px', color: 'var(--text-primary)' }}>
          关于
        </h2>
        <NeuCard>
          <div style={{ fontSize: '0.875rem', color: 'var(--text-secondary)' }}>
            <div>ASMR Helper v0.1.0</div>
            <div style={{ marginTop: '4px' }}>开源许可证: MIT</div>
          </div>
        </NeuCard>
      </div>
    </div>
  )
}
