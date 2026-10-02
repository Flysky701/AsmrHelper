import { useState } from 'react'
import type { BatchRunItemResponse, BatchRunResponse } from '@/api/types'
import GraphRunBindings from '@/components/GraphRunBindings'
import { groupEditable, groupLockReason, groupMaterials, type QueueGroup } from '@/domain/queueGroups'
import type { GraphDefinition } from '@/domain/workflowGraph'
import { fileName, inputPathKey } from '@/domain/workbenchInput'
import { useWorkbenchStore } from '@/stores/workbenchStore'
import { useNavStore } from '@/stores/navStore'

const STATUS: Record<string, string> = { pending: '排队中', running: '处理中', completed: '已完成', failed: '失败', cancelled: '已取消', skipped: '已跳过', history_deleted: '历史已删除', draft: '可配置', missing: '缺素材 / 待确认', excluded: '已排除', unknown: '状态待核实' }
const LANG: Record<string, string> = { ja: '日语', zh: '中文', en: '英语' }
export const queueOutputLabel = (graph: GraphDefinition | null) => graph?.outputs.map(output => output.label || (output.port === 'audio' ? '音频' : '字幕')).join(' + ') || '未选输出'
export interface QueueRowView { group: QueueGroup; batch?: BatchRunResponse; remote?: BatchRunItemResponse; issues: string[]; state: string }
export default function QueueGroupRow({ row, index, graph, presetLabel, busy, discovering, recheck, removeMaterials }: {
  row: QueueRowView; index: number; graph: GraphDefinition | null; presetLabel: string; busy: boolean; discovering: boolean
  recheck: (paths: string[]) => void
  removeMaterials: (ids: string[]) => void
}) {
  const materials = useWorkbenchStore()
  const [expanded, setExpanded] = useState(false)
  const { group, remote, state, issues } = row
  const bindings = group.bindings, paths = group.materialPaths, items = groupMaterials(group, materials.inputItems)
  const editable = groupEditable(group), lockReason = groupLockReason(group)
  const progress = Math.round(Math.max(0, Math.min(1, remote?.progress ?? 0)) * 100)
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
      <input type="checkbox" aria-label={`选择 ${group.label}`} checked={editable && group.selected} disabled={busy || !editable} title={lockReason} onChange={event => materials.patchQueueGroup(group.id, { selected: event.target.checked })} />
      <div className="queue-group-cell"><span className="queue-group-number">{String(index + 1).padStart(2, '0')}</span><div><button className="queue-group-title" type="button" title={group.label} aria-expanded={expanded} onClick={() => setExpanded(value => !value)}>{group.label}</button><small>{paths.length} 个文件{editable ? ' · 素材目录' : ' · 暂时锁定'}</small></div></div>
      <div className="queue-input-cell">{paths.slice(0, 3).map(path => {
        const item = items.find(item => inputPathKey(item.path) === inputPathKey(path)), subtitle = /\.(srt|vtt|lrc)$/i.test(path)
        const binding = Object.values(bindings).find(binding => inputPathKey(binding.path) === inputPathKey(path))
        const language = item?.subtitleSummary?.language || binding?.language
        return <div key={path} title={path}><span className="queue-file-icon">{subtitle ? '▤' : '♬'}</span><span className="queue-file-name">{fileName(path)}</span><small>{subtitle ? LANG[language ?? ''] || '语言待确认' : path.split('.').pop()?.toUpperCase()}</small>{binding?.audio_path ? <small className={binding.pair_confirmed ? 'queue-paired' : 'queue-warning'}>{binding.pair_confirmed ? '✓ 已确认配对' : '配对待确认'}</small> : null}</div>
      })}{paths.length > 3 ? <small>另有 {paths.length - 3} 个文件</small> : null}
        {editable && issues.length ? <button type="button" className="queue-missing-link" title={issues.join('；')} onClick={() => setExpanded(true)}>△ 检查与补充素材</button> : null}
        {!paths.length ? <button type="button" className="queue-missing-link" onClick={() => setExpanded(true)}>补充素材 +</button> : null}
      </div>
      <div className="queue-status-cell"><span className={`queue-status ${['missing', 'unknown'].includes(state) ? 'queue-warning' : ''}`}>{state === 'running' ? '◌ ' : state === 'missing' ? '△ ' : '• '}{STATUS[state] || state}</span>
        <small>{!editable ? lockReason : group.excluded ? '不参与本次处理' : issues.length ? '检查后可勾选运行' : '按当前流程明确提交'}</small>
        {remote && ['pending', 'running'].includes(state) ? <><div className="queue-progress" role="progressbar" aria-label={`${group.label} 进度`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={progress}><span style={{ width: `${progress}%` }} /></div><small>{progress}%</small></> : null}
        {group.run ? <button type="button" className="queue-result-toggle" onClick={() => useNavStore.getState().openTaskCenter('batches')}>最近执行：{STATUS[group.run.state ?? 'unknown'] || '状态待核实'} ↗</button> : null}
      </div>
      <div className="queue-output-cell"><span>{queueOutputLabel(graph)}</span><small>{presetLabel || '未选流水线'}</small></div>
      <button type="button" className="queue-remove-material" aria-label={`删除素材 ${group.label}`} disabled={busy || !editable} title={lockReason || '仅从素材目录移除，不删除磁盘文件或任务历史'} onClick={() => removeMaterials([group.id])}>删除素材</button>
    </div>
    {expanded ? <div className="queue-group-detail" aria-label={`${group.label} 输入与配对`}>
      <div className="queue-detail-heading"><strong>当前素材与配对</strong><button type="button" onClick={() => setExpanded(false)}>收起</button></div>
      {!editable ? <p className="queue-warning">{lockReason}执行详情与产物请到任务中心查看。</p> : null}
      <>
        <div className="queue-detail-actions"><label>组名<input value={group.label} disabled={busy || !editable} maxLength={100} onChange={event => materials.patchQueueGroup(group.id, { label: event.target.value })} /></label><button type="button" disabled={busy || !editable} onClick={() => materials.patchQueueGroup(group.id, { excluded: !group.excluded })}>{group.excluded ? '恢复此组' : '排除此组'}</button><button type="button" disabled={busy || !editable} onClick={() => materials.duplicateQueueGroup(group.id)}>复制为新组</button><button type="button" disabled={busy || !editable || discovering} onClick={() => recheck(group.materialPaths)}>重新检查文件</button></div>
        <div className="queue-material-list">{group.materialPaths.map(path => <div key={path}><span title={path}>{path}</span><button type="button" disabled={busy || !editable} onClick={() => removeMaterial(path)}>从组排除</button></div>)}</div>
        {graph ? <GraphRunBindings graph={graph} bindings={group.bindings} items={materials.inputItems} onChange={(slotId, binding) => materials.bindQueueGroup(group.id, slotId, binding)} disabled={busy || !editable} /> : <p>先选择流水线，再为该组指定输入。</p>}
        {editable && issues.length ? <ul className="queue-group-issues">{issues.map(issue => <li key={issue}>{issue}</li>)}</ul> : null}
      </>
    </div> : null}
  </>
}
