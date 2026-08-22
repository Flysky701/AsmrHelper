import { useCallback, useEffect, useMemo, useState } from 'react'
import type { CSSProperties } from 'react'

import { batchesApi } from '@/api/batches'
import { capabilitiesApi } from '@/api/engines'
import { pipelineApi } from '@/api/pipeline'
import type {
  BatchDiscoveredFileResponse,
  BatchRunResponse,
  CapabilityDescriptorResponse,
} from '@/api/types'
import {
  buildPipelineExecutionProfile,
  buildPipelineStageFlags,
} from '@/domain/pipelineExecutionProfile'
import { normalizePresetStages } from '@/domain/pipelinePreset'
import { FILE_FILTERS, useFileSelector } from '@/hooks/useFileSelector'
import { useTaskPolling } from '@/hooks/useTaskPolling'
import { useNavStore } from '@/stores/navStore'
import { useWorkbenchStore } from '@/stores/workbenchStore'

const ACTIVE_BATCH_STATES = new Set(['pending', 'running', 'cancelling'])

const STATE_LABELS: Record<string, string> = {
  pending: '等待提交',
  running: '处理中',
  cancelling: '正在取消',
  completed: '已完成',
  completed_with_errors: '部分失败',
  cancelled: '已取消',
  interrupted: '已中断',
  failed: '失败',
  skipped: '已跳过',
}

const panel: CSSProperties = {
  background: 'var(--surface)',
  border: '1px solid var(--border)',
  borderRadius: 'var(--radius-card)',
  boxShadow: 'var(--shadow-panel)',
}

const inputStyle: CSSProperties = {
  width: '100%',
  minHeight: 40,
  padding: '8px 11px',
  border: '1px solid var(--border)',
  borderRadius: 'var(--radius-sm)',
  background: 'var(--surface)',
  color: 'var(--fg)',
  font: 'inherit',
}

function fileName(path: string) {
  return path.split(/[/\\]/).pop() || path
}

function formatSize(bytes: number) {
  if (!bytes) return '大小未知'
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(1)} GB`
  if (bytes >= 1024 ** 2) return `${(bytes / 1024 ** 2).toFixed(1)} MB`
  return `${Math.max(1, Math.round(bytes / 1024))} KB`
}

function batchStateColor(state: string) {
  if (state === 'completed') return 'var(--success)'
  if (state === 'completed_with_errors' || state === 'failed' || state === 'interrupted') return 'var(--error)'
  if (state === 'cancelled' || state === 'skipped') return 'var(--muted)'
  return 'var(--accent)'
}

function mergeFiles(
  current: BatchDiscoveredFileResponse[],
  incoming: BatchDiscoveredFileResponse[],
) {
  const byPath = new Map(current.map((item) => [item.path.toLocaleLowerCase(), item]))
  incoming.forEach((item) => byPath.set(item.path.toLocaleLowerCase(), item))
  return Array.from(byPath.values()).sort((a, b) => a.path.localeCompare(b.path))
}

export default function BatchProcessing() {
  useTaskPolling(2500)
  const { selectFiles, selectFolder } = useFileSelector()
  const setPage = useNavStore((state) => state.setPage)
  const {
    preset,
    presets,
    params,
    capabilityOptions,
    setPreset,
    setPresets,
  } = useWorkbenchStore()

  const [capabilities, setCapabilities] = useState<CapabilityDescriptorResponse[]>([])
  const [folder, setFolder] = useState('')
  const [recursive, setRecursive] = useState(true)
  const [files, setFiles] = useState<BatchDiscoveredFileResponse[]>([])
  const [selectedPaths, setSelectedPaths] = useState<Set<string>>(new Set())
  const [outputDir, setOutputDir] = useState('')
  const [batchName, setBatchName] = useState('')
  const [maxParallel, setMaxParallel] = useState(1)
  const [discovering, setDiscovering] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [actionBusy, setActionBusy] = useState(false)
  const [error, setError] = useState('')
  const [batches, setBatches] = useState<BatchRunResponse[]>([])
  const [selectedBatchId, setSelectedBatchId] = useState<string | null>(null)

  const currentPreset = presets.find((item) => item.id === preset) ?? null
  const activePresetStages = normalizePresetStages(currentPreset?.stages ?? [])
  const stageFlags = buildPipelineStageFlags(activePresetStages, params)
  const selectedBatch = batches.find((item) => item.batch_id === selectedBatchId) ?? batches[0] ?? null
  const selectedFiles = useMemo(
    () => files.filter((item) => selectedPaths.has(item.path)),
    [files, selectedPaths],
  )

  useEffect(() => {
    let cancelled = false
    Promise.all([capabilitiesApi.list(), presets.length ? Promise.resolve({ presets }) : pipelineApi.presets()])
      .then(([capabilityItems, presetResponse]) => {
        if (cancelled) return
        setCapabilities(capabilityItems)
        if (presets.length === 0) setPresets(presetResponse.presets)
        const selectedStillExists = presetResponse.presets.some((item) => item.id === preset)
        if (!selectedStillExists) setPreset(presetResponse.presets[0]?.id ?? '')
      })
      .catch((loadError) => {
        if (!cancelled) setError(`读取批量配置失败：${String(loadError)}`)
      })
    return () => { cancelled = true }
  }, [preset, presets, setPreset, setPresets])

  const refreshBatches = useCallback(async () => {
    try {
      const response = await batchesApi.list()
      setBatches(response.batches)
      setSelectedBatchId((current) => (
        current && response.batches.some((item) => item.batch_id === current)
          ? current
          : response.batches[0]?.batch_id ?? null
      ))
    } catch (loadError) {
      setError(`读取批次失败：${String(loadError)}`)
    }
  }, [])

  useEffect(() => {
    void refreshBatches()
    const timer = window.setInterval(() => { void refreshBatches() }, 1500)
    return () => window.clearInterval(timer)
  }, [refreshBatches])

  const discover = useCallback(async (directory: string) => {
    if (!directory) return
    setDiscovering(true)
    setError('')
    try {
      const response = await batchesApi.discover(directory, recursive)
      setFiles(response.files)
      setSelectedPaths(new Set(response.files.map((item) => item.path)))
      if (!batchName.trim()) setBatchName(`批量处理 · ${fileName(directory)}`)
    } catch (discoverError) {
      setFiles([])
      setSelectedPaths(new Set())
      setError(`扫描目录失败：${String(discoverError)}`)
    } finally {
      setDiscovering(false)
    }
  }, [batchName, recursive])

  const chooseInputFolder = async () => {
    const directory = await selectFolder()
    if (!directory) return
    setFolder(directory)
    await discover(directory)
  }

  const addFiles = async () => {
    const paths = await selectFiles({ filters: [FILE_FILTERS.audio] })
    if (paths.length === 0) return
    const incoming = paths.map((path) => ({
      path,
      name: fileName(path),
      size_bytes: 0,
      companion_paths: [],
    }))
    setFiles((current) => mergeFiles(current, incoming))
    setSelectedPaths((current) => new Set([...current, ...paths]))
  }

  const chooseOutputFolder = async () => {
    const directory = await selectFolder()
    if (directory) setOutputDir(directory)
  }

  const toggleFile = (path: string) => {
    setSelectedPaths((current) => {
      const next = new Set(current)
      if (next.has(path)) next.delete(path)
      else next.add(path)
      return next
    })
  }

  const createBatch = async () => {
    if (!currentPreset || selectedFiles.length === 0 || capabilities.length === 0) return
    setSubmitting(true)
    setError('')
    try {
      const executionProfile = buildPipelineExecutionProfile({
        params,
        stageFlags,
        capabilities,
        capabilityOptions,
      })
      const created = await batchesApi.create({
        name: batchName.trim() || `批量任务 · ${new Date().toLocaleString()}`,
        inputs: selectedFiles.map((item) => ({
          path: item.path,
          companion_paths: item.companion_paths,
        })),
        output: { directory: outputDir || undefined },
        execution_profile: executionProfile,
        max_parallel: maxParallel,
      })
      setBatches((current) => [created, ...current.filter((item) => item.batch_id !== created.batch_id)])
      setSelectedBatchId(created.batch_id)
      setFiles([])
      setSelectedPaths(new Set())
      setBatchName('')
    } catch (submitError) {
      setError(`创建批次失败：${String(submitError)}`)
    } finally {
      setSubmitting(false)
    }
  }

  const runBatchAction = async (action: 'cancel' | 'retry') => {
    if (!selectedBatch) return
    setActionBusy(true)
    setError('')
    try {
      const updated = action === 'cancel'
        ? await batchesApi.cancel(selectedBatch.batch_id)
        : await batchesApi.retryFailed(selectedBatch.batch_id)
      setBatches((current) => current.map((item) => item.batch_id === updated.batch_id ? updated : item))
    } catch (actionError) {
      setError(`${action === 'cancel' ? '取消批次' : '重试失败项'}失败：${String(actionError)}`)
    } finally {
      setActionBusy(false)
    }
  }

  const allSelected = files.length > 0 && selectedFiles.length === files.length
  const retryable = Boolean(selectedBatch && (
    selectedBatch.failed_count > 0 ||
    selectedBatch.cancelled_count > 0 ||
    selectedBatch.state === 'interrupted'
  ))

  return (
    <div className="batch-page" style={{ height: '100%', overflow: 'auto', padding: 24 }}>
      <header className="batch-header" style={{ display: 'flex', justifyContent: 'space-between', gap: 20, alignItems: 'flex-start', marginBottom: 20 }}>
        <div>
          <div style={{ fontSize: 12, color: 'var(--accent)', fontWeight: 800, letterSpacing: '0.08em' }}>BATCH RUN</div>
          <h1 style={{ margin: '7px 0 0', fontFamily: 'var(--font-display)', fontSize: 28 }}>批量处理</h1>
          <p style={{ margin: '8px 0 0', color: 'var(--muted)', maxWidth: 720 }}>
            一个批次拥有稳定编号；每个文件仍由独立 Pipeline Task 执行并保留自己的错误与产物。
          </p>
        </div>
        <button type="button" style={{ ...inputStyle, width: 'auto', cursor: 'pointer' }} onClick={() => setPage('workbench')}>
          调整工作台参数
        </button>
      </header>

      {error ? <div style={{ marginBottom: 16, padding: '10px 14px', color: 'var(--error)', background: 'var(--error-soft)', borderRadius: 'var(--radius-sm)' }}>{error}</div> : null}

      <div className="batch-layout" style={{ display: 'grid', gridTemplateColumns: 'minmax(360px, 0.9fr) minmax(0, 1.35fr)', gap: 20 }}>
        <section style={{ ...panel, padding: 18, alignSelf: 'start' }}>
          <div style={{ fontSize: 17, fontWeight: 750 }}>创建批次</div>
          <div style={{ marginTop: 5, color: 'var(--muted)', fontSize: 12 }}>
            使用工作台当前预设：{currentPreset?.label || '尚未加载'}
          </div>

          <div style={{ marginTop: 18, display: 'grid', gap: 12 }}>
            <label>
              <span style={{ fontSize: 12, fontWeight: 650 }}>批次名称</span>
              <input style={{ ...inputStyle, marginTop: 6 }} value={batchName} onChange={(event) => setBatchName(event.target.value)} placeholder="例如：8 月待处理音频" />
            </label>

            <div>
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                <button type="button" style={{ ...inputStyle, width: 'auto', cursor: 'pointer' }} onClick={chooseInputFolder} disabled={discovering}>
                  {discovering ? '扫描中...' : '选择并扫描目录'}
                </button>
                <button type="button" style={{ ...inputStyle, width: 'auto', cursor: 'pointer' }} onClick={addFiles}>添加文件</button>
                {folder ? <button type="button" style={{ ...inputStyle, width: 'auto', cursor: 'pointer' }} onClick={() => discover(folder)} disabled={discovering}>重新扫描</button> : null}
              </div>
              <div style={{ marginTop: 8, color: 'var(--muted)', fontSize: 12, overflowWrap: 'anywhere' }}>{folder || '尚未选择目录'}</div>
              <label style={{ marginTop: 8, display: 'inline-flex', gap: 8, alignItems: 'center', fontSize: 12 }}>
                <input type="checkbox" checked={recursive} onChange={(event) => setRecursive(event.target.checked)} />
                扫描子目录
              </label>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) 130px', gap: 12 }}>
              <label>
                <span style={{ fontSize: 12, fontWeight: 650 }}>输出目录</span>
                <button type="button" style={{ ...inputStyle, marginTop: 6, textAlign: 'left', cursor: 'pointer', overflowWrap: 'anywhere' }} onClick={chooseOutputFolder}>
                  {outputDir || '使用工作区默认目录'}
                </button>
              </label>
              <label>
                <span style={{ fontSize: 12, fontWeight: 650 }}>并行文件数</span>
                <select style={{ ...inputStyle, marginTop: 6 }} value={maxParallel} onChange={(event) => setMaxParallel(Number(event.target.value))}>
                  <option value={1}>1（推荐）</option>
                  <option value={2}>2</option>
                  <option value={3}>3</option>
                  <option value={4}>4</option>
                </select>
              </label>
            </div>
          </div>

          <div style={{ marginTop: 18, border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)', overflow: 'hidden' }}>
            <div style={{ padding: '10px 12px', background: 'var(--panel-muted)', display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'center' }}>
              <label style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 12, fontWeight: 700 }}>
                <input
                  type="checkbox"
                  checked={allSelected}
                  onChange={() => setSelectedPaths(allSelected ? new Set() : new Set(files.map((item) => item.path)))}
                />
                文件 {selectedFiles.length}/{files.length}
              </label>
              <span style={{ fontSize: 11, color: 'var(--muted)' }}>同名字幕会自动作为伴随文件</span>
            </div>
            <div style={{ maxHeight: 300, overflow: 'auto' }}>
              {files.length === 0 ? (
                <div style={{ padding: 24, textAlign: 'center', color: 'var(--muted)', fontSize: 13 }}>选择目录或添加音频后在此确认清单</div>
              ) : files.map((item) => (
                <label key={item.path} style={{ display: 'grid', gridTemplateColumns: 'auto minmax(0, 1fr) auto', gap: 10, padding: '10px 12px', borderTop: '1px solid var(--border)', alignItems: 'center', cursor: 'pointer' }}>
                  <input type="checkbox" checked={selectedPaths.has(item.path)} onChange={() => toggleFile(item.path)} />
                  <span style={{ minWidth: 0 }}>
                    <span style={{ display: 'block', fontSize: 12, fontWeight: 650, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{item.name}</span>
                    <span style={{ display: 'block', marginTop: 3, fontSize: 10, color: 'var(--muted)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{item.path}</span>
                  </span>
                  <span style={{ textAlign: 'right', fontSize: 10, color: 'var(--muted)' }}>
                    {formatSize(item.size_bytes)}{item.companion_paths.length ? ' · 有字幕' : ''}
                  </span>
                </label>
              ))}
            </div>
          </div>

          <button
            type="button"
            onClick={createBatch}
            disabled={submitting || selectedFiles.length === 0 || !currentPreset || capabilities.length === 0}
            style={{ marginTop: 16, width: '100%', minHeight: 44, border: 0, borderRadius: 'var(--radius-button)', background: 'var(--accent)', color: 'white', fontWeight: 750, cursor: submitting ? 'not-allowed' : 'pointer', opacity: submitting ? 0.6 : 1 }}
          >
            {submitting ? '正在创建批次...' : `创建批次并处理 ${selectedFiles.length} 个文件`}
          </button>
        </section>

        <section style={{ ...panel, minWidth: 0, overflow: 'hidden' }}>
          <div className="batch-detail-header" style={{ padding: 18, borderBottom: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', gap: 16, alignItems: 'flex-start' }}>
            <div style={{ minWidth: 0 }}>
              <div style={{ fontSize: 17, fontWeight: 750 }}>{selectedBatch?.name || '批次进度'}</div>
              <div style={{ marginTop: 5, color: 'var(--muted)', fontSize: 11, overflowWrap: 'anywhere' }}>{selectedBatch?.batch_id || '暂无批次'}</div>
            </div>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
              {selectedBatch && ACTIVE_BATCH_STATES.has(selectedBatch.state) ? (
                <button type="button" style={{ ...inputStyle, width: 'auto', cursor: 'pointer', color: 'var(--error)' }} disabled={actionBusy} onClick={() => runBatchAction('cancel')}>整批取消</button>
              ) : null}
              {retryable ? (
                <button type="button" style={{ ...inputStyle, width: 'auto', cursor: 'pointer', color: 'var(--accent)' }} disabled={actionBusy} onClick={() => runBatchAction('retry')}>重试失败项</button>
              ) : null}
              <button type="button" style={{ ...inputStyle, width: 'auto', cursor: 'pointer' }} onClick={() => setPage('task-center')}>查看任务中心</button>
            </div>
          </div>

          {selectedBatch ? (
            <>
              <div style={{ padding: '16px 18px', borderBottom: '1px solid var(--border)' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, fontSize: 12 }}>
                  <span style={{ color: batchStateColor(selectedBatch.state), fontWeight: 750 }}>{STATE_LABELS[selectedBatch.state] || selectedBatch.state}</span>
                  <span>{Math.round(selectedBatch.progress * 100)}%</span>
                </div>
                <div style={{ marginTop: 8, height: 8, borderRadius: 999, background: 'var(--panel-muted)', overflow: 'hidden' }}>
                  <div style={{ height: '100%', width: `${Math.round(selectedBatch.progress * 100)}%`, background: batchStateColor(selectedBatch.state), transition: 'width 200ms ease' }} />
                </div>
                <div className="batch-stats" style={{ marginTop: 13, display: 'grid', gridTemplateColumns: 'repeat(5, minmax(70px, 1fr))', gap: 8 }}>
                  {[
                    ['总数', selectedBatch.total_count],
                    ['运行', selectedBatch.running_count],
                    ['完成', selectedBatch.completed_count + selectedBatch.skipped_count],
                    ['失败', selectedBatch.failed_count],
                    ['取消', selectedBatch.cancelled_count],
                  ].map(([label, value]) => (
                    <div key={String(label)} style={{ padding: 9, borderRadius: 'var(--radius-sm)', background: 'var(--panel-muted)', textAlign: 'center' }}>
                      <div style={{ fontSize: 15, fontWeight: 750 }}>{value}</div>
                      <div style={{ marginTop: 2, fontSize: 10, color: 'var(--muted)' }}>{label}</div>
                    </div>
                  ))}
                </div>
              </div>

              <div style={{ maxHeight: 440, overflow: 'auto' }}>
                {selectedBatch.items.map((item) => (
                  <div key={item.item_id} style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) 130px', gap: 14, padding: '12px 18px', borderBottom: '1px solid var(--border)', alignItems: 'center' }}>
                    <div style={{ minWidth: 0 }}>
                      <div style={{ fontSize: 12, fontWeight: 650, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{fileName(item.input_path)}</div>
                      <div style={{ marginTop: 4, fontSize: 10, color: 'var(--muted)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                        {item.current_task_id || '尚未创建子任务'}
                      </div>
                      {item.error ? <div style={{ marginTop: 5, color: 'var(--error)', fontSize: 10, overflowWrap: 'anywhere' }}>{String(item.error.message || item.message)}</div> : null}
                    </div>
                    <div>
                      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10 }}>
                        <span style={{ color: batchStateColor(item.state), fontWeight: 700 }}>{STATE_LABELS[item.state] || item.state}</span>
                        <span>{Math.round(item.progress * 100)}%</span>
                      </div>
                      <div style={{ marginTop: 5, height: 5, borderRadius: 999, background: 'var(--panel-muted)', overflow: 'hidden' }}>
                        <div style={{ height: '100%', width: `${Math.round(item.progress * 100)}%`, background: batchStateColor(item.state) }} />
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </>
          ) : (
            <div style={{ padding: 50, textAlign: 'center', color: 'var(--muted)' }}>创建首个批次后，这里会持续显示总进度和每个文件的真实状态。</div>
          )}

          {batches.length > 0 ? (
            <div style={{ padding: 14, background: 'var(--panel-muted)', borderTop: '1px solid var(--border)' }}>
              <div style={{ marginBottom: 8, fontSize: 11, color: 'var(--muted)', fontWeight: 700 }}>最近批次</div>
              <div style={{ display: 'flex', gap: 8, overflowX: 'auto' }}>
                {batches.slice(0, 8).map((batch) => (
                  <button key={batch.batch_id} type="button" onClick={() => setSelectedBatchId(batch.batch_id)} style={{ minWidth: 150, padding: '9px 10px', borderRadius: 'var(--radius-sm)', border: batch.batch_id === selectedBatch?.batch_id ? '1px solid var(--accent)' : '1px solid var(--border)', background: 'var(--surface)', color: 'var(--fg)', textAlign: 'left', cursor: 'pointer' }}>
                    <div style={{ fontSize: 11, fontWeight: 700, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{batch.name}</div>
                    <div style={{ marginTop: 4, fontSize: 10, color: batchStateColor(batch.state) }}>{STATE_LABELS[batch.state] || batch.state} · {Math.round(batch.progress * 100)}%</div>
                  </button>
                ))}
              </div>
            </div>
          ) : null}
        </section>
      </div>

      <style>{`
        .batch-page, .batch-layout, .batch-layout > *, .batch-detail-header > * { min-width: 0; }
        @media (max-width: 1120px) {
          .batch-layout { grid-template-columns: minmax(0, 1fr) !important; }
        }
        @media (max-width: 760px) {
          .batch-page { padding: 16px !important; }
          .batch-header, .batch-detail-header { flex-direction: column; }
          .batch-stats { grid-template-columns: repeat(2, minmax(0, 1fr)) !important; }
        }
      `}</style>
    </div>
  )
}
