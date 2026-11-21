import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import type { GraphPresetItem } from '@/api/types'
import QuickStartHelp from '@/components/QuickStartHelp'
import { graphNodeHasAdvancedParameters } from '@/domain/graphNodeParameters'
import { GRAPH_CATALOG, isMultitrackMix, type GraphDefinition, type GraphNode } from '@/domain/workflowGraph'
import { format, useI18n } from '@/i18n'
import GraphNodeParameters from './GraphNodeParameters'
import './QueueRunParameters.css'

interface Props {
  graph: GraphDefinition
  preset: GraphPresetItem | null
  selectedNodeId: string
  onSelectNode: (id: string) => void
  changedNodes: ReadonlySet<string>
  busy: boolean
  error: string | null
  saveStatus: string
  onNodeChange: (node: GraphNode) => void
  copyName: string
  onCopyNameChange: (name: string) => void
  onSave: (mode: 'update' | 'copy') => Promise<boolean>
  onClose: () => void
}

export default function QueueRunParameters({
  graph, preset, selectedNodeId, onSelectNode, changedNodes, busy, error, saveStatus,
  onNodeChange, copyName, onCopyNameChange, onSave, onClose,
}: Props) {
  const t = useI18n()
  const [preferredSection, setSection] = useState<'common' | 'advanced'>('common')
  const [visited, setVisited] = useState<ReadonlySet<string>>(() => new Set())
  const [saveOpen, setSaveOpen] = useState(false)
  const scroll = useRef<HTMLDivElement>(null)
  const title = useRef<HTMLHeadingElement>(null)
  const saveToggle = useRef<HTMLButtonElement>(null)
  const node = graph.nodes.find(item => item.id === selectedNodeId) ?? graph.nodes[0]
  const hasAdvanced = Boolean(node && graphNodeHasAdvancedParameters(node))
  const section = hasAdvanced ? preferredSection : 'common'

  useEffect(() => { title.current?.focus({ preventScroll: true }) }, [])
  useLayoutEffect(() => { if (scroll.current) scroll.current.scrollTop = 0 }, [node?.id, section])

  function selectNode(id: string) {
    if (node?.id === id) return
    if (node) setVisited(current => new Set([...current, node.id]))
    onSelectNode(id)
  }

  function nodeLabel(item: GraphNode) {
    const label = t(item.kind === 'mix' && !isMultitrackMix(item) ? '配音混音' : GRAPH_CATALOG[item.kind].label)
    return graph.nodes.some(other => other.kind === item.kind && other.id !== item.id) ? `${label} · ${item.id}` : label
  }

  async function save(mode: 'update' | 'copy') {
    if (await onSave(mode)) {
      setSaveOpen(false)
      saveToggle.current?.focus()
    }
  }

  return <aside className="queue-parameter-panel" aria-label={t("本次运行参数")}>
    <header className="queue-panel-heading">
      <div>
        <div className="page-title-row">
          <h2 ref={title} tabIndex={-1}>{t("本次运行参数")}</h2>
          <QuickStartHelp topic={section === 'advanced' ? 'workbench-advanced' : 'workbench-common'} />
        </div>
        {preset?.label && <small>{preset.label}</small>}
      </div>
      <button type="button" className="queue-link" onClick={onClose}>{t("‹ 返回素材队列")}</button>
    </header>

    <div className="queue-parameter-workspace">
      <nav className="queue-parameter-nav" aria-label={t("流程节点")}>
        {graph.nodes.map(item => <button type="button" key={item.id} aria-current={item.id === node?.id ? 'true' : undefined}
          onClick={() => selectNode(item.id)}>
          <span>{nodeLabel(item)}</span>
          {changedNodes.has(item.id) && <small>{t("已调整")}</small>}
        </button>)}
      </nav>

      <div className="queue-parameter-detail">
        {node && <div className="queue-parameter-context">
          <label className="queue-parameter-picker">
            <span>{t("流程节点")}</span>
            <select value={node.id} onChange={event => selectNode(event.target.value)}>
              {graph.nodes.map(item => <option key={item.id} value={item.id}>{nodeLabel(item)}{changedNodes.has(item.id) ? ` · ${t("已调整")}` : ''}</option>)}
            </select>
          </label>
          <h3>{nodeLabel(node)}</h3>
          {hasAdvanced && <div className="queue-parameter-tabs" role="group" aria-label={t("参数分类")}>
            <button type="button" aria-pressed={section === 'common'} onClick={() => setSection('common')}>{t("常用")}</button>
            <button type="button" aria-pressed={section === 'advanced'} onClick={() => setSection('advanced')}>{t("高级")}</button>
          </div>}
        </div>}

        <div className="queue-panel-scroll" ref={scroll}>
          {node ? graph.nodes.filter(item => item.id === node.id || visited.has(item.id)).map(item => (
            <div key={item.id} className="queue-node-parameters" hidden={item.id !== node.id}>
              <GraphNodeParameters node={item} onChange={onNodeChange} disabled={busy}
                section={item.id === node.id ? section : 'common'} />
            </div>
          )) : <p className="queue-muted">{t("这条流水线还没有节点。")}</p>}
          {!!graph.outputs.length && <details className="queue-panel-outputs">
            <summary>{t("流水线产出")}</summary>
            {graph.outputs.map(output => <div key={`${output.node_id}:${output.port}`}>
              <span>{output.label || (output.port === 'audio' ? t("音频") : t("字幕"))}</span>
              <small>{output.port === 'audio' ? t("音频") : String(graph.nodes.find(item => item.id === output.node_id)?.options.subtitle_format || t("字幕")).toUpperCase()}</small>
            </div>)}
          </details>}
        </div>
      </div>
    </div>

    {saveOpen && <form className="queue-save-form" onSubmit={event => { event.preventDefault(); void save('copy') }}>
      <label>{t("新流水线名称")}<input autoFocus value={copyName} disabled={busy} maxLength={100} onChange={event => onCopyNameChange(event.target.value)} /></label>
      <div className="queue-save-actions">
        <button type="submit" disabled={busy || !copyName.trim()}>{t("保存为新流水线")}</button>
        {preset && !preset.builtin && <button type="button" disabled={busy || !changedNodes.size} onClick={() => void save('update')}>{t("保存参数到原预设")}</button>}
      </div>
    </form>}
    {error && <p className="queue-parameter-error queue-error" role="alert">{t(error)}</p>}
    <footer className="queue-panel-footer">
      {(changedNodes.size > 0 || saveStatus) && <span role="status">{changedNodes.size ? format("{0} 个节点已调整", [changedNodes.size]) : t(saveStatus)}</span>}
      <div>
        <button ref={saveToggle} type="button" aria-expanded={saveOpen} disabled={busy} onClick={() => setSaveOpen(open => !open)}>{saveOpen ? t("收起保存选项") : t("另存为流水线")}</button>
        <button type="button" className="queue-primary" onClick={onClose}>{t("完成调整")}</button>
      </div>
    </footer>
  </aside>
}
