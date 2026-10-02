import { useState } from 'react'
import type { BatchRunItemResponse, BatchRunResponse } from '@/api/types'
import GraphRunBindings from '@/components/GraphRunBindings'
import { groupEditable, groupMaterials, type QueueGroup } from '@/domain/queueGroups'
import { GRAPH_CATALOG, type GraphDefinition } from '@/domain/workflowGraph'
import { fileName, inputPathKey } from '@/domain/workbenchInput'
import { useWorkbenchStore } from '@/stores/workbenchStore'
import QueueGroupArtifacts from './QueueGroupArtifacts'

const STATUS: Record<string, string> = { pending: '排队中', running: '处理中', completed: '已完成', failed: '失败', cancelled: '已取消', skipped: '已跳过', history_deleted: '历史已删除', draft: '待运行', missing: '缺素材 / 待确认', excluded: '已排除', unknown: '状态待核实' }
const LANG: Record<string, string> = { ja: '日语', zh: '中文', en: '英语' }
export const queueOutputLabel = (graph: GraphDefinition | null) => graph?.outputs.map(output => output.label || (output.port === 'audio' ? '音频' : '字幕')).join(' + ') || '输出定义不可用'
export interface QueueRowView { group: QueueGroup; batch?: BatchRunResponse; remote?: BatchRunItemResponse; issues: string[]; state: string }
export default function QueueGroupRow({ row, index, graph, presetLabel, busy, discovering, batchAction, recheck, actOnBatch }: {
  row: QueueRowView; index: number; graph: GraphDefinition | null; presetLabel: string; busy: boolean; discovering: boolean; batchAction: boolean
  recheck: (paths: string[]) => void
  actOnBatch: (batch: BatchRunResponse, action: 'retry' | 'cancel') => void
}) {
  const materials = useWorkbenchStore()
  const [expanded, setExpanded] = useState(false)
  const [showResults, setShowResults] = useState(false)
  const { group, batch, remote, state, issues } = row
  const pending = group.pendingRequestId ? materials.queueSubmission : null
  const frozenGraph = group.run ? group.run.graph : pending ? pending.request.execution_profile.graph : graph
  const bindings = group.run?.bindings ?? pending?.request.groups.find(item => item.group_id === group.id)?.bindings ?? group.bindings
  const items = groupMaterials(group, materials.inputItems)
  const paths = group.run ? [...new Set(Object.values(bindings).flatMap(binding => [binding.path, ...(binding.audio_path ? [binding.audio_path] : [])]))] : group.materialPaths
  const editable = groupEditable(group), progress = Math.round(Math.max(0, Math.min(1, remote?.progress ?? 0)) * 100)
  const removeMaterial = (path: string) => {
    const key = inputPathKey(path)
    materials.patchQueueGroup(group.id, { materialPaths: group.materialPaths.filter(candidate => inputPathKey(candidate) !== key) })
    Object.entries(group.bindings).forEach(([slotId, binding]) => {
      if (inputPathKey(binding.path) === key) materials.bindQueueGroup(group.id, slotId, undefined)
      else if (binding.audio_path && inputPathKey(binding.audio_path) === key) materials.bindQueueGroup(group.id, slotId, { ...binding, audio_path: null, pair_confirmed: false })
    })
  }
  return <>
    <div className={`queue-row queue-grid state-${state}`} data-group-id={group.id}>
      <input type="checkbox" aria-label={`选择 ${group.label}`} checked={editable && group.selected && !group.excluded} disabled={busy || !editable || group.excluded} onChange={event => materials.patchQueueGroup(group.id, { selected: event.target.checked })} />
      <div className="queue-group-cell"><span className="queue-group-number">{String(index + 1).padStart(2, '0')}</span><div><button className="queue-group-title" type="button" title={group.label} aria-expanded={expanded} onClick={() => setExpanded(value => !value)}>{group.label}</button><small>{paths.length} 个文件{group.run ? ' · 参数已冻结' : group.excluded ? ' · 已排除' : ' · 本次草稿'}</small></div></div>
      <div className="queue-input-cell">{paths.slice(0, 3).map(path => {
        const item = items.find(item => inputPathKey(item.path) === inputPathKey(path)), subtitle = /\.(srt|vtt|lrc)$/i.test(path)
        const binding = Object.values(bindings).find(binding => inputPathKey(binding.path) === inputPathKey(path))
        const language = group.run || pending ? binding?.language : item?.subtitleSummary?.language || binding?.language
        return <div key={path} title={path}><span className="queue-file-icon">{subtitle ? '▤' : '♬'}</span><span className="queue-file-name">{fileName(path)}</span><small>{subtitle ? LANG[language ?? ''] || '语言待确认' : path.split('.').pop()?.toUpperCase()}</small>{binding?.audio_path ? <small className={binding.pair_confirmed ? 'queue-paired' : 'queue-warning'}>{binding.pair_confirmed ? '✓ 已确认配对' : '配对待确认'}</small> : null}</div>
      })}{paths.length > 3 ? <small>另有 {paths.length - 3} 个文件</small> : null}
        {editable && issues.length ? <button type="button" className="queue-missing-link" title={issues.join('；')} onClick={() => setExpanded(true)}>△ 检查与补充素材</button> : null}
        {!paths.length ? <button type="button" className="queue-missing-link" onClick={() => setExpanded(true)}>补充素材 +</button> : null}
      </div>
      <div className="queue-status-cell"><span className={`queue-status ${state === 'completed' ? 'queue-success' : ['missing', 'failed', 'unknown'].includes(state) ? 'queue-warning' : ''}`}>{state === 'completed' ? '✓ ' : state === 'running' ? '◌ ' : state === 'missing' ? '△ ' : '• '}{STATUS[state] || state}</span>
        {remote && ['pending', 'running'].includes(state) ? <><div className="queue-progress" role="progressbar" aria-label={`${group.label} 进度`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={progress}><span style={{ width: `${progress}%` }} /></div><small>{progress}% · {remote.message || '等待后端状态'}</small></> : <small>{state === 'history_deleted' ? '运行历史已删除，输入素材仍保留' : group.pendingRequestId ? '提交结果尚未确认' : group.run ? remote?.message || '正在读取任务事实' : group.excluded ? '本组不参与运行' : issues.length ? '检查后可勾选运行' : '素材齐备'}</small>}
        {state !== 'history_deleted' && group.run && remote?.current_task_id ? <button type="button" className="queue-result-toggle" aria-expanded={showResults} onClick={() => setShowResults(value => !value)}>{state === 'completed' ? '查看结果' : '查看本组产物'} {showResults ? '⌃' : '⌄'}</button> : null}
      </div>
      <div className="queue-output-cell"><span>{queueOutputLabel(frozenGraph)}</span><small>{group.run ? group.run.presetLabel : presetLabel || '未选流水线'}</small></div>
      <button type="button" className="queue-row-more" aria-label={`检查 ${group.label} 的输入与参数`} aria-expanded={expanded} onClick={() => setExpanded(value => !value)}>···</button>
    </div>
    {expanded ? <div className="queue-group-detail" aria-label={`${group.label} 输入与配对`}>
      <div className="queue-detail-heading"><strong>{editable ? '检查与配对' : '提交时的输入与参数'}</strong><button type="button" onClick={() => setExpanded(false)}>收起</button></div>
      {editable ? <>
        <div className="queue-detail-actions"><label>组名<input value={group.label} disabled={busy} maxLength={100} onChange={event => materials.patchQueueGroup(group.id, { label: event.target.value })} /></label><button type="button" disabled={busy} onClick={() => materials.patchQueueGroup(group.id, { excluded: !group.excluded })}>{group.excluded ? '恢复此组' : '排除此组'}</button><button type="button" disabled={busy} onClick={() => materials.duplicateQueueGroup(group.id)}>复制为新组</button><button type="button" disabled={busy || discovering} onClick={() => recheck(group.materialPaths)}>重新检查文件</button></div>
        <div className="queue-material-list">{group.materialPaths.map(path => <div key={path}><span title={path}>{path}</span><button type="button" disabled={busy} onClick={() => removeMaterial(path)}>从组排除</button></div>)}</div>
        {graph ? <GraphRunBindings graph={graph} bindings={group.bindings} items={materials.inputItems} onChange={(slotId, binding) => materials.bindQueueGroup(group.id, slotId, binding)} disabled={busy} /> : <p>先选择流水线，再为该组指定输入。</p>}
        {issues.length ? <ul className="queue-group-issues">{issues.map(issue => <li key={issue}>{issue}</li>)}</ul> : <p className="queue-success">绑定已就绪。运行前后端还会检查文件与执行环境。</p>}
      </> : <>
        {group.pendingRequestId ? <p className="queue-warning">该组已提交，结果尚未确认。核实期间保留原始请求。</p> : null}
        <p>{group.run?.presetLabel} · {group.run?.submittedAt ? new Date(group.run.submittedAt).toLocaleString() : ''} · {group.run?.outputDirectory || '工作区默认输出目录'}</p>
        {Object.entries(bindings).map(([slot, binding]) => <p key={slot}><strong>{frozenGraph?.input_slots.find(item => item.id === slot)?.label || slot}</strong> · {binding.path}{binding.audio_path ? ` ↔ ${binding.audio_path}（${binding.pair_confirmed ? '已确认' : '未确认'}）` : ''}</p>)}
        {frozenGraph ? frozenGraph.nodes.map(node => <details className="queue-frozen-node" key={node.id}><summary>{GRAPH_CATALOG[node.kind].label} · {node.id} · {node.provider}{node.model ? ` / ${node.model}` : ''}</summary><p>{node.source_lang ? `源语言：${LANG[node.source_lang]} ` : ''}{node.target_lang ? `目标语言：${LANG[node.target_lang]}` : ''}</p><pre>{JSON.stringify({ options: node.options, provider_options: node.provider_options }, null, 2)}</pre></details>) : <p className="queue-warning">当前客户端没有此批次的原始参数快照，未用当前草稿替代。能否重试由后端的冻结快照决定。</p>}
        {state !== 'history_deleted' && remote?.error ? <p className="queue-error">{String(remote.error.message || remote.error.detail || JSON.stringify(remote.error))}</p> : null}
        <div className="queue-detail-actions">{batch && ['failed', 'cancelled'].includes(state) ? <button type="button" disabled={batchAction || !!materials.queueBatchActions[batch.batch_id] || !batch.retry_available} title={batch.retry_blocked_reason || ''} onClick={() => actOnBatch(batch, 'retry')}>按原参数重试本批失败组</button> : null}{batch && ['pending', 'running', 'cancelling'].includes(batch.state) ? <button type="button" disabled={batchAction || !!materials.queueBatchActions[batch.batch_id]} onClick={() => actOnBatch(batch, 'cancel')}>取消本批次</button> : null}{group.run ? <button type="button" disabled={busy} onClick={() => materials.duplicateQueueGroup(group.id)}>复制输入为新组</button> : null}</div>
        {batch && materials.queueBatchActions[batch.batch_id] ? <p className="queue-warning">本批次操作结果尚未确认。正在核实任务状态，暂不重复提交操作。</p> : null}
        {batch && ['failed', 'cancelled'].includes(state) && !batch.retry_available ? <p className="queue-warning">{batch.retry_blocked_reason || '后端未确认可重试，不能使用当前参数替代原执行快照。'}</p> : null}
      </>}
    </div> : null}
    {state !== 'history_deleted' && showResults && group.run ? <QueueGroupArtifacts key={`${group.run.batchId}:${group.run.itemId}:${remote?.current_task_id ?? ''}`} taskId={remote?.current_task_id ?? null} /> : null}
  </>
}
