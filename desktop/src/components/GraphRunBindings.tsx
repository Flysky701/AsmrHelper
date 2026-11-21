import { t, format, useI18n } from '@/i18n'
import { displayPath } from '@/utils/displayPath'
import type { GraphBindings, GraphDefinition, GraphLanguage, GraphMaterialBinding } from '@/domain/workflowGraph'
import { isMultitrackMix, GRAPH_CATALOG, topologicalNodeIds, validateGraph } from '@/domain/workflowGraph'
import { inputPathKey, type WorkbenchInputItem } from '@/domain/workbenchInput'

const LANGUAGES = [{ value: 'ja', label: '日语' }, { value: 'zh', label: '中文' }, { value: 'en', label: '英语' }] as const
export const materialType = (item: WorkbenchInputItem) => /\.(srt|vtt|lrc)$/i.test(item.path) ? 'subtitle'
  : /\.(mp3|wav|flac|ogg|m4a|aac|wma)$/i.test(item.path) ? 'audio' : 'unsupported'
const knownLanguage = (value?: string | null): value is GraphLanguage => LANGUAGES.some(language => language.value === value)
export function usedGraphSlots(graph: GraphDefinition) {
  const used = new Set(graph.edges.flatMap(edge => edge.source.kind === 'slot' ? [edge.source.slot_id] : []))
  return graph.input_slots.filter(slot => used.has(slot.id))
}

/** Only declared, explicitly bound materials count. Backend checks files and actual durations. */
export function graphBindingIssues(graph: GraphDefinition, bindings: GraphBindings, items: WorkbenchInputItem[]): string[] {
  const issues: string[] = []
  const languageBySlot: Record<string, GraphLanguage | undefined> = {}
  const timelineBySlot: Record<string, string | undefined> = {}
  const find = (path?: string | null) => items.find(item => path && inputPathKey(item.path) === inputPathKey(path))
  for (const slot of usedGraphSlots(graph)) {
    const binding = bindings[slot.id]
    const item = find(binding?.path)
    if (!binding?.path) { issues.push(`${slot.label}：请选择输入素材`); continue }
    if (!item) { issues.push(`${slot.label}：原素材已移除，请重新添加或选择`); continue }
    if (materialType(item) !== slot.type) { issues.push(`${slot.label}：素材类型不匹配`); continue }
    timelineBySlot[slot.id] = inputPathKey(item.path)
    if (slot.type === 'subtitle') {
      if (item.subtitleSummary && !item.subtitleSummary.valid) issues.push(`${slot.label}：${item.subtitleSummary.reason || '字幕无效，请检查文本和时间轴'}`)
      const detected = item.subtitleSummary?.language
      const language = knownLanguage(detected) ? detected : binding.language_confirmed && knownLanguage(binding.language) ? binding.language : undefined
      languageBySlot[slot.id] = language
      if (!language) issues.push(`${slot.label}：请确认字幕实际语言`)
      if (language && slot.language && language !== slot.language) issues.push(`${slot.label}：需要 ${slot.language} 字幕，所选素材为 ${language}`)
    }
    if (binding.audio_path) {
      const paired = find(binding.audio_path)
      if (!paired || materialType(paired) !== 'audio') issues.push(`${slot.label}：对应音频不可用，请重新选择`)
      else if (!binding.pair_confirmed) issues.push(`${slot.label}：请确认与所选音频属于同一录音和时间轴`)
      else timelineBySlot[slot.id] = inputPathKey(paired.path)
    }
  }
  const withLanguages = { ...graph, input_slots: graph.input_slots.map(slot => ({ ...slot, language: languageBySlot[slot.id] ?? slot.language })) }
  issues.push(...validateGraph(withLanguages).map(issue => `${issue.node_id ? `${issue.node_id}：` : ''}${t(issue.message)}`))
  if (validateGraph(graph).length === 0) {
    const timelines = new Map<string, string | undefined>()
    for (const id of topologicalNodeIds(graph)) {
      const node = graph.nodes.find(candidate => candidate.id === id)!
      const incoming = Object.fromEntries(graph.edges.filter(edge => edge.target.node_id === id).map(edge => [edge.target.port,
        edge.source.kind === 'slot' ? timelineBySlot[edge.source.slot_id] : timelines.get(edge.source.node_id)]))
      if (node.kind === 'align' || node.kind === 'mix' && !isMultitrackMix(node)) {
        const other = incoming[node.kind === 'align' ? 'subtitle' : 'speech']
        if (incoming.audio && other && incoming.audio !== other) issues.push(`${id} · ${t(GRAPH_CATALOG[node.kind].label)}：请在素材槽确认输入属于同一录音和时间轴`)
      }
      timelines.set(id, isMultitrackMix(node) ? `mix:${id}` : node.kind === 'audio_difference' ? incoming.mixed
        : incoming[['asr', 'separate', 'mix', 'audio_export'].includes(node.kind) ? 'audio' : 'subtitle'])
    }
  }
  return [...new Set(issues)].map(t)
}

export default function GraphRunBindings({ graph, bindings, items, onChange, disabled = false }: {
  graph: GraphDefinition
  bindings: GraphBindings
  items: WorkbenchInputItem[]
  onChange: (id: string, binding: GraphMaterialBinding | undefined) => void
  disabled?: boolean
}) {
  useI18n()
  return <div className="graph-run-bindings">
    {usedGraphSlots(graph).map(slot => {
      const binding = bindings[slot.id]
      const candidates = items.filter(item => materialType(item) === slot.type)
      const selected = candidates.find(item => binding && inputPathKey(item.path) === inputPathKey(binding.path))
      const detected = selected?.subtitleSummary?.language
      const audioCandidates = items.filter(item => materialType(item) === 'audio' && (!selected || inputPathKey(item.path) !== inputPathKey(selected.path)))
      const patch = (value: Partial<GraphMaterialBinding>) => { if (binding) onChange(slot.id, { ...binding, ...value }) }
      const consumers = graph.edges.filter(edge => edge.source.kind === 'slot' && edge.source.slot_id === slot.id).map(edge => edge.target.node_id)
      return <fieldset className="graph-run-slot" key={slot.id} disabled={disabled}>
        <legend>{slot.label} <span>{slot.type === 'audio' ? t("音频") : t("字幕")}</span></legend>
        <p className="graph-workbench-muted">{t("用于 ")}{consumers.join('、')}{slot.language ? format(" · 需要 {0}", [t(LANGUAGES.find(language => language.value === slot.language)?.label || '')]) : ''}</p>
        <label>{t("输入素材 ")}<select aria-label={format("{0} · 输入素材", [slot.label])} value={selected?.path ?? binding?.path ?? ''} onChange={event => {
            const item = candidates.find(candidate => candidate.path === event.target.value)
            if (!item) { onChange(slot.id, undefined); return }
            const language = item.subtitleSummary?.language
            // Keep inspected metadata separate from the user's explicit language confirmation.
            onChange(slot.id, { path: item.path, ...(knownLanguage(language) ? { language } : {}) })
          }}>
            <option value="">{t("请选择")}{slot.type === 'audio' ? t("音频") : t("字幕")}</option>
            {binding && !selected ? <option value={binding.path}>{t("原素材已移除：")}{displayPath(binding.path)}</option> : null}
            {candidates.map(item => <option key={item.path} value={item.path}>{item.name} — {displayPath(item.path)}</option>)}
          </select>
        </label>
        {selected && slot.type === 'subtitle' ? knownLanguage(detected) ? <p className="graph-workbench-muted">{t("字幕语言：")}{t(LANGUAGES.find(language => language.value === detected)?.label || '')}</p> : <>
          <label>{t("字幕实际语言 ")}<select aria-label={format("{0} · 字幕语言", [slot.label])} value={binding?.language ?? ''} onChange={event => patch({ language: (event.target.value || null) as GraphLanguage | null, language_confirmed: false })}>
              <option value="">{t("请核实实际语言")}</option>{LANGUAGES.map(language => <option key={language.value} value={language.value}>{t(language.label)}</option>)}
            </select>
          </label>
          <label className="graph-workbench-checkbox"><input type="checkbox" disabled={disabled || !binding?.language} checked={!!binding?.language_confirmed} onChange={event => patch({ language_confirmed: event.target.checked })} />{t("确认字幕实际语言")}</label>
        </> : null}
        {selected && (audioCandidates.length > 0 || binding?.audio_path) ? <>
          <label>{t("配对音频（可选） ")}<select aria-label={format("{0} · 对应音频", [slot.label])} value={binding?.audio_path ?? ''} onChange={event => patch({ audio_path: event.target.value || null, pair_confirmed: false })}>
              <option value="">{t("不配对")}</option>
              {binding?.audio_path && !audioCandidates.some(item => item.path === binding.audio_path) ? <option value={binding.audio_path}>{t("原对应音频已移除")}</option> : null}
              {audioCandidates.map(item => <option key={item.path} value={item.path}>{item.name} — {displayPath(item.path)}</option>)}
            </select>
          </label>
          {binding?.audio_path ? <label className="graph-workbench-checkbox"><input type="checkbox" checked={!!binding.pair_confirmed} onChange={event => patch({ pair_confirmed: event.target.checked })} />{t("确认来自同一录音和时间轴")}</label> : null}
        </> : null}
        {candidates.length === 0 ? <p className="graph-workbench-warning">{t("没有可用")}{slot.type === 'audio' ? t("音频") : t("字幕")}{t("，请在素材库添加。")}</p> : null}
      </fieldset>
    })}
  </div>
}
