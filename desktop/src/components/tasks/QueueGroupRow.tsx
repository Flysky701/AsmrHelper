import { t, format as formatMessage, useI18n } from '@/i18n'
import { displayPath } from '@/utils/displayPath'
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
export const queueOutputLabel = (graph: GraphDefinition | null) => graph?.outputs.map(output => output.label || (output.port === 'audio' ? t("音频") : t("字幕"))).join(' + ') || t("未选输出")
export interface QueueRowView { group: QueueGroup; batch?: BatchRunResponse; remote?: BatchRunItemResponse; issues: string[]; state: string }
export default function QueueGroupRow({ row, index, graph, presetLabel, busy, discovering, recheck, removeMaterials }: {
  row: QueueRowView; index: number; graph: GraphDefinition | null; presetLabel: string; busy: boolean; discovering: boolean
  recheck: (paths: string[]) => void
  removeMaterials: (ids: string[]) => void
}) {
  useI18n()
  const materials = useWorkbenchStore()
  const [expanded, setExpanded] = useState(false)
  const { group, remote, state, issues } = row
  const bindings = group.bindings, paths = group.materialPaths, items = groupMaterials(group, materials.inputItems)
  const editable = groupEditable(group), lockReason = t(groupLockReason(group))
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
      <input type="checkbox" aria-label={formatMessage("选择 {0}", [group.label])} checked={editable && group.selected} disabled={busy || !editable} title={lockReason} onChange={event => materials.patchQueueGroup(group.id, { selected: event.target.checked })} />
      <div className="queue-group-cell"><span className="queue-group-number">{String(index + 1).padStart(2, '0')}</span><div><button className="queue-group-title" type="button" title={group.label} aria-expanded={expanded} onClick={() => setExpanded(value => !value)}>{group.label}</button><small>{paths.length} {t("个文件")}{editable ? t(" · 素材目录") : t(" · 暂时锁定")}</small></div></div>
      <div className="queue-input-cell">{paths.slice(0, 3).map(path => {
        const item = items.find(item => inputPathKey(item.path) === inputPathKey(path)), subtitle = /\.(srt|vtt|lrc)$/i.test(path)
        const binding = Object.values(bindings).find(binding => inputPathKey(binding.path) === inputPathKey(path))
        const language = item?.subtitleSummary?.language || binding?.language
        return <div key={path} title={displayPath(path)}><span className="queue-file-icon">{subtitle ? '▤' : '♬'}</span><span className="queue-file-name">{fileName(path)}</span><small>{subtitle ? (LANG[language ?? ''] ? t(LANG[language ?? '']!) : '') || t("语言待确认") : path.split('.').pop()?.toUpperCase()}</small>{binding?.audio_path ? <small className={binding.pair_confirmed ? 'queue-paired' : 'queue-warning'}>{binding.pair_confirmed ? t("✓ 已确认配对") : t("配对待确认")}</small> : null}</div>
      })}{paths.length > 3 ? <small>{t("另有")}{paths.length - 3} {t("个文件")}</small> : null}
        {editable && issues.length ? <button type="button" className="queue-missing-link" title={issues.map(issue => t(issue)).join('; ')} onClick={() => setExpanded(true)}>{t("△ 检查与补充素材")}</button> : null}
        {!paths.length ? <button type="button" className="queue-missing-link" onClick={() => setExpanded(true)}>{t("补充素材 +")}</button> : null}
      </div>
      <div className="queue-status-cell"><span className={`queue-status ${['missing', 'unknown'].includes(state) ? 'queue-warning' : ''}`}>{state === 'running' ? '◌ ' : state === 'missing' ? '△ ' : '• '}{t(STATUS[state] || state)}</span>
        {!editable || group.excluded || issues.length ? <small>{!editable ? lockReason : group.excluded ? t("不参与本次处理") : t("请补全输入")}</small> : null}
        {remote && ['pending', 'running'].includes(state) ? <><div className="queue-progress" role="progressbar" aria-label={formatMessage("{0} 进度", [group.label])} aria-valuemin={0} aria-valuemax={100} aria-valuenow={progress}><span style={{ width: `${progress}%` }} /></div><small>{progress}%</small></> : null}
        {group.run ? <button type="button" className="queue-result-toggle" onClick={() => useNavStore.getState().openTaskCenter('batches')}>{t("最近执行：")}{t(STATUS[group.run.state ?? 'unknown'] || '') || t("状态待核实")} ↗</button> : null}
      </div>
      <div className="queue-output-cell"><span>{queueOutputLabel(graph)}</span><small>{presetLabel || t("未选流水线")}</small></div>
      <button type="button" className="queue-remove-material" aria-label={formatMessage("删除素材 {0}", [group.label])} disabled={busy || !editable} title={lockReason || t("仅从素材目录移除，不删除磁盘文件或任务历史")} onClick={() => removeMaterials([group.id])}>{t("删除素材")}</button>
    </div>
    {expanded ? <div className="queue-group-detail" aria-label={formatMessage("{0} 输入与配对", [group.label])}>
      <div className="queue-detail-heading"><strong>{t("当前素材与配对")}</strong><button type="button" onClick={() => setExpanded(false)}>{t("收起")}</button></div>
      {!editable ? <p className="queue-warning">{lockReason}{t("执行详情与产物请到任务中心查看。")}</p> : null}
      <>
        <div className="queue-detail-actions"><label>{t("组名")}<input value={group.label} disabled={busy || !editable} maxLength={100} onChange={event => materials.patchQueueGroup(group.id, { label: event.target.value })} /></label><button type="button" disabled={busy || !editable} onClick={() => materials.patchQueueGroup(group.id, { excluded: !group.excluded })}>{group.excluded ? t("恢复此组") : t("排除此组")}</button><button type="button" disabled={busy || !editable} onClick={() => materials.duplicateQueueGroup(group.id)}>{t("复制为新组")}</button><button type="button" disabled={busy || !editable || discovering} onClick={() => recheck(group.materialPaths)}>{t("重新检查文件")}</button></div>
        <div className="queue-material-list">{group.materialPaths.map(path => <div key={path}><span title={displayPath(path)}>{displayPath(path)}</span><button type="button" disabled={busy || !editable} onClick={() => removeMaterial(path)}>{t("从组排除")}</button></div>)}</div>
        {graph ? <GraphRunBindings graph={graph} bindings={group.bindings} items={materials.inputItems} onChange={(slotId, binding) => materials.bindQueueGroup(group.id, slotId, binding)} disabled={busy || !editable} /> : <p>{t("先选择流水线，再为该组指定输入。")}</p>}
        {editable && issues.length ? <ul className="queue-group-issues">{issues.map(issue => <li key={issue}>{t(issue)}</li>)}</ul> : null}
      </>
    </div> : null}
  </>
}
