import { useState } from 'react'
import { NeuCard, NeuInput, NeuSelect, NeuSlider, NeuButton } from '@/components/ui'

export default function Settings() {
  const [deepseekKey, setDeepseekKey] = useState('')
  const [openaiKey, setOpenaiKey] = useState('')
  const [defaultTranslator, setDefaultTranslator] = useState('deepseek')
  const [defaultTtsEngine, setDefaultTtsEngine] = useState('edge')
  const [defaultVoice, setDefaultVoice] = useState('zh-CN-XiaoxiaoNeural')
  const [defaultAsrModel, setDefaultAsrModel] = useState('base')
  const [defaultVocalModel, setDefaultVocalModel] = useState('htdemucs')
  const [defaultVolume, setDefaultVolume] = useState(0.85)
  const [defaultTtsRatio, setDefaultTtsRatio] = useState(0.5)
  const [outputDir, setOutputDir] = useState('')
  const [modelDir, setModelDir] = useState('')
  const [tempDir, setTempDir] = useState('')

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px', maxWidth: '600px' }}>
      {/* API Config */}
      <div>
        <h2 style={{ fontSize: '1.125rem', fontWeight: 600, marginBottom: '12px', color: 'var(--text-primary)' }}>
          API 配置
        </h2>
        <NeuCard>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
            <NeuInput
              label="DeepSeek API Key"
              type="password"
              value={deepseekKey}
              onChange={(e) => setDeepseekKey(e.target.value)}
              placeholder="sk-..."
            />
            <NeuInput
              label="OpenAI API Key"
              type="password"
              value={openaiKey}
              onChange={(e) => setOpenaiKey(e.target.value)}
              placeholder="sk-..."
            />
            <NeuSelect
              label="默认翻译提供商"
              value={defaultTranslator}
              onChange={(e) => setDefaultTranslator(e.target.value)}
              options={[
                { value: 'deepseek', label: 'DeepSeek' },
                { value: 'openai', label: 'OpenAI' },
              ]}
            />
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
              value={defaultTtsEngine}
              onChange={(e) => setDefaultTtsEngine(e.target.value)}
              options={[
                { value: 'edge', label: 'Edge TTS' },
                { value: 'qwen3', label: 'Qwen3 TTS' },
              ]}
            />
            <NeuInput
              label="默认音色"
              value={defaultVoice}
              onChange={(e) => setDefaultVoice(e.target.value)}
            />
            <NeuSelect
              label="默认 ASR 模型"
              value={defaultAsrModel}
              onChange={(e) => setDefaultAsrModel(e.target.value)}
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
              value={defaultVocalModel}
              onChange={(e) => setDefaultVocalModel(e.target.value)}
              options={[
                { value: 'htdemucs', label: 'HTDemucs' },
                { value: 'htdemucs_ft', label: 'HTDemucs FT' },
              ]}
            />
            <NeuSlider
              label="默认原声音量"
              value={defaultVolume}
              min={0}
              max={1}
              step={0.05}
              onChange={setDefaultVolume}
              showValue
              formatValue={(v) => v.toFixed(2)}
            />
            <NeuSlider
              label="默认 TTS 音量比例"
              value={defaultTtsRatio}
              min={0}
              max={1}
              step={0.05}
              onChange={setDefaultTtsRatio}
              showValue
              formatValue={(v) => v.toFixed(2)}
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
              value={outputDir}
              onChange={(e) => setOutputDir(e.target.value)}
              placeholder="默认: output/"
            />
            <NeuInput
              label="模型目录"
              value={modelDir}
              onChange={(e) => setModelDir(e.target.value)}
              placeholder="默认: models/"
            />
            <NeuInput
              label="临时文件目录"
              value={tempDir}
              onChange={(e) => setTempDir(e.target.value)}
              placeholder="默认: debug/"
            />
          </div>
        </NeuCard>
      </div>

      {/* Save */}
      <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
        <NeuButton variant="primary">保存设置</NeuButton>
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
