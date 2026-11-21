import type { ReactNode } from 'react'
import { useI18n } from '@/i18n'
import { setGraphOption } from '@/domain/graphNodeParameters'
import type { GraphNode } from '@/domain/workflowGraph'

interface Props {
  node: GraphNode
  onChange: (node: GraphNode) => void
  pauseControl?: ReactNode
}

function optionRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
}

export default function SpeechProcessingParameters({ node, onChange, pauseControl }: Props) {
  const t = useI18n()
  const acoustic = optionRecord(node.options.acoustic_options)
  const vc = optionRecord(node.options.vc_refinement)
  const change = (key: string, value: unknown) => onChange(setGraphOption(node, 'options', key, value))
  const changeAcoustic = (key: string, value: unknown) => {
    const updated = { ...acoustic, [key]: value }
    if (value === undefined) delete updated[key]
    change('acoustic_options', Object.keys(updated).length ? updated : undefined)
  }
  const select = (label: string, value: unknown, choices: [string, string][], update: (value: string) => void) =>
    <label className="graph-param-field"><span>{t(label)}</span><select value={String(value)} onChange={event => update(event.target.value)}>
      {choices.map(([key, name]) => <option key={key} value={key}>{t(name)}</option>)}
    </select></label>
  const number = (label: string, value: unknown, min: number, max: number | undefined, step: number, update: (value: number | undefined) => void) =>
    <label className="graph-param-field"><span>{t(label)}</span><input type="number" min={min} max={max} step={step} value={String(value ?? '')}
      onChange={event => update(event.target.value === '' ? undefined : Number(event.target.value))} /></label>
  const toggle = (label: string, checked: boolean, update: (value: boolean) => void) =>
    <label className="graph-mix-mute"><input type="checkbox" checked={checked} onChange={event => update(event.target.checked)} />{t(label)}</label>

  return <div className="graph-param-section">
    <details className="graph-speech-group" open>
      <summary>{t("时长与节奏")}</summary>
      <div className="graph-param-section">
        {pauseControl}
        {toggle('借用句尾静音', node.options.borrow_silence_slack === true, value => change('borrow_silence_slack', value))}
        {number('最大加速倍率', node.options.max_atempo, 1, undefined, .05, value => change('max_atempo', value))}
        {select('变速引擎', acoustic.time_stretch_engine ?? 'ffmpeg_atempo', [['ffmpeg_atempo', 'FFmpeg（默认）'], ['pytsmod_wsola', 'WSOLA']], value => changeAcoustic('time_stretch_engine', value))}
      </div>
    </details>
    <details className="graph-speech-group">
      <summary>{t("双耳与响度匹配")}</summary>
      <div className="graph-param-section">
        {select('双耳声像', acoustic.binaural_mode ?? '', [['', '跟随参考（默认）'], ['off', '单声道'], ['static', '逐句静态声像'], ['dynamic_hrtf', '动态双耳声像']],
          value => changeAcoustic('binaural_mode', value || undefined))}
        {toggle('逐句匹配原声响度', acoustic.loudness_match === 'per_cue', value => changeAcoustic('loudness_match', value ? 'per_cue' : 'global'))}
        {toggle('匹配麦克风频响并柔化齿音', acoustic.eq_matching === true, value => changeAcoustic('eq_matching', value))}
        {acoustic.eq_matching === true && number('频响匹配强度', acoustic.eq_strength ?? .5, 0, 1, .05, value => changeAcoustic('eq_strength', value))}
        {toggle('加入近场微混响', acoustic.reverb_match === true, value => changeAcoustic('reverb_match', value))}
      </div>
    </details>
    <details className="graph-speech-group">
      <summary>{t("演绎分析与参考策略")}</summary>
      <div className="graph-param-section">
        {toggle('自动识别耳语与轻柔发声', node.options.auto_detect_delivery === true, value => change('auto_detect_delivery', value))}
        {select('克隆参考', node.options.reference_mode ?? 'single', [
          ['single', node.options.auto_clone ? '使用自动提取的干声' : '使用配方参考（默认）'],
          ['per_style', node.options.auto_clone ? '按发声方式与相对响度选取' : '按发声风格选取'],
          ['per_cue', '逐句选取'],
        ], value => change('reference_mode', value))}
        {node.options.reference_mode === 'per_style' && <small>{t("可开启自动识别发声方式，以便按风格选取原声。")}</small>}
      </div>
    </details>
    <details className="graph-speech-group">
      <summary>{t("验卡与音色转换")}</summary>
      <div className="graph-param-section">
        {toggle('Whisper 验卡与重试', node.options.verify_with_asr === true, value => change('verify_with_asr', value))}
        {node.options.verify_with_asr === true && <>
          {number('最大重试次数', node.options.max_retries ?? 2, 0, 5, 1, value => change('max_retries', value))}
          {number('最低文本相似度', node.options.min_similarity ?? .75, 0, 1, .05, value => change('min_similarity', value))}
        </>}
        <div>
          {toggle('Seed-VC 音色转换', vc.enabled === true, value => change('vc_refinement', { ...vc, enabled: value }))}
          <p className="graph-param-note">{t("让已合成的语音更接近参考录音的音色。需要远端 GPU Worker。")}</p>
        </div>
        {vc.enabled === true && number('变声扩散步数', vc.diffusion_steps ?? 25, 1, 100, 1,
          value => change('vc_refinement', { ...vc, diffusion_steps: value }))}
      </div>
    </details>
  </div>
}
