import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { CSSProperties } from 'react'

import { batchesApi } from '@/api/batches'
import type { BatchRunResponse, BatchRunState } from '@/api/types'

const ACTIVE_BATCH_STATES = new Set<BatchRunState>(['pending', 'running', 'cancelling'])
const CANCELLABLE_BATCH_STATES = new Set<BatchRunState>(['pending', 'running'])

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
  history_deleted: '历史已删除',
}

const SURFACE_STYLE: CSSProperties = {
  minWidth: 0,
  minHeight: 0,
  background: 'var(--surface)',
  border: '1px solid var(--border)',
  borderRadius: 'var(--radius-card)',
  boxShadow: 'var(--shadow-panel)',
}

const BUTTON_STYLE: CSSProperties = {
  minHeight: 36,
  padding: '0 13px',
  border: '1px solid var(--border)',
  borderRadius: 'var(--radius-button)',
  background: 'var(--surface)',
  color: 'var(--fg)',
  font: 'inherit',
  fontSize: 12,
  fontWeight: 650,
  cursor: 'pointer',
}

const BATCH_RUNS_PANEL_STYLES = `
  .batch-runs-panel {
    flex: 1;
    min-height: 0;
    overflow: hidden;
    display: grid;
    grid-template-columns: minmax(280px, 360px) minmax(0, 1fr);
    gap: 20px;
    padding: 20px;
  }

  .batch-runs-history,
  .batch-runs-detail {
    display: flex;
    flex-direction: column;
    min-width: 0;
    min-height: 0;
    overflow: hidden;
  }

  .batch-runs-history-list,
  .batch-runs-detail-scroll,
  .batch-runs-item-list {
    min-height: 0;
    overflow: auto;
  }

  .batch-runs-history-list {
    flex: 1;
    padding: 12px;
    display: grid;
    gap: 10px;
    align-content: start;
  }

  .batch-runs-detail-scroll {
    flex: 1;
  }

  .batch-runs-item-list {
    max-height: 46vh;
  }

  @media (max-width: 1100px) {
    .batch-runs-panel {
      flex: none;
      overflow: visible;
      grid-template-columns: minmax(0, 1fr);
      padding: 16px;
    }

    .batch-runs-history {
      max-height: 420px;
    }

    .batch-runs-detail,
    .batch-runs-detail-scroll {
      overflow: visible;
    }

    .batch-runs-item-list {
      max-height: 560px;
    }
  }

  @media (max-width: 680px) {
    .batch-runs-panel {
      gap: 14px;
      padding: 12px;
    }

    .batch-runs-detail-header {
      align-items: stretch !important;
      flex-direction: column;
    }

    .batch-runs-detail-actions > button {
      flex: 1 1 140px;
    }

    .batch-runs-item {
      grid-template-columns: minmax(0, 1fr) !important;
    }
  }
`

function isActiveBatch(batch: BatchRunResponse | null | undefined) {
  return Boolean(batch && ACTIVE_BATCH_STATES.has(batch.state))
}

function fileName(path: string) {
  return path.split(/[/\\]/).pop() || path
}

function formatDateTime(value: string | null) {
  if (!value) return '—'
  const timestamp = Date.parse(value)
  return Number.isNaN(timestamp) ? value : new Date(timestamp).toLocaleString()
}

function stateColor(state: string) {
  if (state === 'completed') return 'var(--success)'
  if (state === 'completed_with_errors' || state === 'failed' || state === 'interrupted') return 'var(--error)'
  if (state === 'cancelled' || state === 'skipped' || state === 'history_deleted') return 'var(--muted-strong)'
  return 'var(--accent)'
}

function progressPercent(progress: number) {
  return Math.round(Math.max(0, Math.min(1, progress)) * 100)
}

function itemErrorMessage(error: Record<string, unknown> | null, fallback: string) {
  if (!error) return ''
  if (typeof error.message === 'string' && error.message) return error.message
  if (typeof error.detail === 'string' && error.detail) return error.detail
  return fallback
}

function sortBatches(batches: BatchRunResponse[]) {
  return batches.filter(batch => batch.state !== 'history_deleted' && batch.items.some(item => item.state !== 'history_deleted' || item.task_ids.length > 0)).sort((left, right) => (
    right.created_at.localeCompare(left.created_at) || right.batch_id.localeCompare(left.batch_id)
  ))
}

function isRetryable(batch: BatchRunResponse | null) {
  return Boolean(batch && batch.retry_available !== false && !ACTIVE_BATCH_STATES.has(batch.state)
    && batch.items.some(item => item.state === 'failed' || item.state === 'cancelled') && (
    batch.failed_count > 0 ||
    batch.cancelled_count > 0
  ))
}

export default function BatchRunsPanel() {
  const [batches, setBatches] = useState<BatchRunResponse[]>([])
  const [selectedBatchId, setSelectedBatchId] = useState<string | null>(null)
  const [loadingHistory, setLoadingHistory] = useState(true)
  const [historyError, setHistoryError] = useState('')
  const [pollError, setPollError] = useState('')
  const [actionError, setActionError] = useState('')
  const [actionBusy, setActionBusy] = useState(false)
  const historyRequestRef = useRef(0)

  const selectedBatch = useMemo(
    () => batches.find((batch) => batch.batch_id === selectedBatchId) ?? null,
    [batches, selectedBatchId],
  )

  const upsertBatch = useCallback((updated: BatchRunResponse) => {
    setBatches((current) => {
      const exists = current.some((batch) => batch.batch_id === updated.batch_id)
      const next = exists
        ? current.map((batch) => batch.batch_id === updated.batch_id ? updated : batch)
        : [updated, ...current]
      return sortBatches(next)
    })
  }, [])

  const loadHistory = useCallback(async () => {
    const requestId = historyRequestRef.current + 1
    historyRequestRef.current = requestId
    setLoadingHistory(true)
    setHistoryError('')
    try {
      const response = await batchesApi.list()
      if (historyRequestRef.current !== requestId) return
      const ordered = sortBatches(response.batches)
      setBatches(ordered)
      setSelectedBatchId((current) => {
        if (current && ordered.some((batch) => batch.batch_id === current)) return current
        return ordered.find(isActiveBatch)?.batch_id ?? ordered[0]?.batch_id ?? null
      })
    } catch (error) {
      if (historyRequestRef.current === requestId) {
        setHistoryError(`读取批次历史失败：${String(error)}`)
      }
    } finally {
      if (historyRequestRef.current === requestId) setLoadingHistory(false)
    }
  }, [])

  useEffect(() => {
    void loadHistory()
    return () => {
      historyRequestRef.current += 1
    }
  }, [loadHistory])

  useEffect(() => {
    if (!selectedBatch || !isActiveBatch(selectedBatch) || actionBusy) return

    let disposed = false
    let timer: number | null = null
    const batchId = selectedBatch.batch_id

    const schedule = (delay: number) => {
      timer = window.setTimeout(() => { void poll() }, delay)
    }

    const poll = async () => {
      try {
        const updated = await batchesApi.get(batchId)
        if (disposed) return
        setPollError('')
        upsertBatch(updated)
        if (isActiveBatch(updated)) schedule(1500)
      } catch (error) {
        if (disposed) return
        setPollError(`批次状态暂时无法刷新：${String(error)}`)
        schedule(3000)
      }
    }

    schedule(0)
    return () => {
      disposed = true
      if (timer !== null) window.clearTimeout(timer)
    }
  }, [actionBusy, selectedBatch?.batch_id, selectedBatch?.state, upsertBatch])

  const runBatchAction = async (action: 'cancel' | 'retry') => {
    if (!selectedBatch) return
    setActionBusy(true)
    setActionError('')
    try {
      const updated = action === 'cancel'
        ? await batchesApi.cancel(selectedBatch.batch_id)
        : await batchesApi.retryFailed(selectedBatch.batch_id)
      upsertBatch(updated)
    } catch (error) {
      setActionError(`${action === 'cancel' ? '取消批次' : '重试失败项'}失败：${String(error)}`)
    } finally {
      setActionBusy(false)
    }
  }

  const retryable = isRetryable(selectedBatch)

  return (
    <div className="batch-runs-panel">
      <style>{BATCH_RUNS_PANEL_STYLES}</style>

      <section className="batch-runs-history" style={SURFACE_STYLE}>
        <div style={{ padding: '16px 18px 14px', borderBottom: '1px solid var(--border)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'baseline' }}>
            <div style={{ fontSize: 14, fontWeight: 700 }}>批次历史</div>
            <div style={{ fontSize: 11, color: 'var(--muted)' }}>{batches.length} 个批次</div>
          </div>
          <div style={{ marginTop: 4, fontSize: 12, color: 'var(--muted)' }}>
            进入此视图时加载一次；活动批次仅在选中后持续刷新。
          </div>
        </div>

        {historyError ? (
          <div style={{ margin: 12, padding: '11px 12px', borderRadius: 'var(--radius-sm)', background: 'var(--error-soft)', color: 'var(--error)', fontSize: 12 }}>
            <div>{historyError}</div>
            <button type="button" style={{ ...BUTTON_STYLE, marginTop: 10 }} onClick={() => { void loadHistory() }}>
              重新加载
            </button>
          </div>
        ) : null}

        <div className="batch-runs-history-list">
          {loadingHistory && batches.length === 0 ? (
            <div style={{ minHeight: 180, display: 'grid', placeItems: 'center', color: 'var(--muted)', fontSize: 13 }}>
              正在读取批次历史…
            </div>
          ) : batches.length === 0 ? (
            <div style={{ minHeight: 180, display: 'grid', placeItems: 'center', color: 'var(--muted)', fontSize: 13, textAlign: 'center' }}>
              还没有批次。多文件任务会在这里形成可恢复查看的批次事实。
            </div>
          ) : batches.map((batch) => {
            const selected = batch.batch_id === selectedBatchId
            return (
              <button
                key={batch.batch_id}
                type="button"
                aria-pressed={selected}
                onClick={() => {
                  setSelectedBatchId(batch.batch_id)
                  setActionError('')
                  setPollError('')
                }}
                style={{
                  width: '100%',
                  minWidth: 0,
                  padding: '12px 13px',
                  border: selected ? '1px solid var(--accent)' : '1px solid var(--border)',
                  borderRadius: 'var(--radius-card)',
                  background: selected ? 'var(--accent-soft)' : 'var(--surface)',
                  color: 'var(--fg)',
                  textAlign: 'left',
                  cursor: 'pointer',
                  boxShadow: selected ? 'var(--shadow-float)' : 'none',
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, alignItems: 'flex-start' }}>
                  <span style={{ minWidth: 0, fontSize: 13, fontWeight: 700, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {batch.name}
                  </span>
                  <span style={{ flexShrink: 0, fontSize: 10, fontWeight: 700, color: stateColor(batch.state) }}>
                    {STATE_LABELS[batch.state] || batch.state}
                  </span>
                </div>
                <div style={{ marginTop: 7, height: 5, borderRadius: 999, background: 'var(--panel-muted)', overflow: 'hidden' }}>
                  <div style={{ width: `${progressPercent(batch.progress)}%`, height: '100%', background: stateColor(batch.state) }} />
                </div>
                <div style={{ marginTop: 7, display: 'flex', justifyContent: 'space-between', gap: 10, color: 'var(--muted)', fontSize: 10 }}>
                  <span>{formatDateTime(batch.created_at)}</span>
                  <span>{batch.completed_count + batch.skipped_count}/{Math.max(0, batch.total_count - (batch.history_deleted_count ?? 0))}{batch.history_deleted_count ? ` · 历史已删除 ${batch.history_deleted_count}` : ''}</span>
                </div>
              </button>
            )
          })}
        </div>
      </section>

      <section className="batch-runs-detail" style={SURFACE_STYLE}>
        {!selectedBatch ? (
          <div style={{ minHeight: 340, display: 'grid', placeItems: 'center', padding: 28, color: 'var(--muted)', textAlign: 'center' }}>
            选择一个批次查看聚合进度、子任务事实与可用操作。
          </div>
        ) : (
          <>
            <div className="batch-runs-detail-header" style={{ padding: '17px 18px', borderBottom: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', gap: 16, alignItems: 'flex-start' }}>
              <div style={{ minWidth: 0 }}>
                <div style={{ fontSize: 18, fontWeight: 750, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{selectedBatch.name}</div>
                <div style={{ marginTop: 5, color: 'var(--muted)', fontSize: 11, overflowWrap: 'anywhere' }}>{selectedBatch.batch_id}</div>
              </div>
              <div className="batch-runs-detail-actions" style={{ display: 'flex', gap: 8, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
                {CANCELLABLE_BATCH_STATES.has(selectedBatch.state) ? (
                  <button type="button" style={{ ...BUTTON_STYLE, color: 'var(--error)' }} disabled={actionBusy} onClick={() => { void runBatchAction('cancel') }}>
                    {actionBusy ? '处理中…' : '整批取消'}
                  </button>
                ) : null}
                {retryable ? (
                  <button type="button" style={{ ...BUTTON_STYLE, color: 'var(--accent)' }} disabled={actionBusy} onClick={() => { void runBatchAction('retry') }}>
                    {actionBusy ? '处理中…' : '重试失败项'}
                  </button>
                ) : null}
              </div>
            </div>

            <div className="batch-runs-detail-scroll">
              {actionError ? <div style={{ margin: '14px 18px 0', padding: '10px 12px', borderRadius: 'var(--radius-sm)', background: 'var(--error-soft)', color: 'var(--error)', fontSize: 12 }}>{actionError}</div> : null}
              {pollError ? <div style={{ margin: '14px 18px 0', padding: '10px 12px', borderRadius: 'var(--radius-sm)', background: 'var(--warning-soft)', color: 'var(--warning)', fontSize: 12 }}>{pollError}</div> : null}

              <div style={{ padding: '16px 18px', borderBottom: '1px solid var(--border)' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, fontSize: 12 }}>
                  <span style={{ color: stateColor(selectedBatch.state), fontWeight: 750 }}>{STATE_LABELS[selectedBatch.state] || selectedBatch.state}</span>
                  <span>{progressPercent(selectedBatch.progress)}%</span>
                </div>
                <div style={{ marginTop: 8, height: 8, borderRadius: 999, background: 'var(--panel-muted)', overflow: 'hidden' }}>
                  <div style={{ height: '100%', width: `${progressPercent(selectedBatch.progress)}%`, background: stateColor(selectedBatch.state), transition: 'width 200ms ease' }} />
                </div>
                <div style={{ marginTop: 13, display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 92px), 1fr))', gap: 8 }}>
                  {[
                    ['总数', selectedBatch.total_count],
                    ['等待', selectedBatch.pending_count],
                    ['运行', selectedBatch.running_count],
                    ['完成', selectedBatch.completed_count + selectedBatch.skipped_count],
                    ['失败', selectedBatch.failed_count],
                    ['取消', selectedBatch.cancelled_count],
                    ['历史已删除', selectedBatch.history_deleted_count ?? 0],
                  ].map(([label, value]) => (
                    <div key={String(label)} style={{ padding: '9px 8px', borderRadius: 'var(--radius-sm)', background: 'var(--panel-muted)', textAlign: 'center' }}>
                      <div style={{ fontSize: 15, fontWeight: 750 }}>{value}</div>
                      <div style={{ marginTop: 2, fontSize: 10, color: 'var(--muted)' }}>{label}</div>
                    </div>
                  ))}
                </div>

                <div style={{ marginTop: 13, display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 190px), 1fr))', gap: 8 }}>
                  {[
                    ['创建时间', formatDateTime(selectedBatch.created_at)],
                    ['更新时间', formatDateTime(selectedBatch.updated_at)],
                    ['并行文件数', String(selectedBatch.max_parallel)],
                    ['输出目录', selectedBatch.output_dir || '工作区默认目录'],
                  ].map(([label, value]) => (
                    <div key={label} style={{ padding: '10px 11px', borderRadius: 'var(--radius-sm)', background: 'var(--panel-muted)', minWidth: 0 }}>
                      <div style={{ fontSize: 10, color: 'var(--muted)' }}>{label}</div>
                      <div style={{ marginTop: 5, fontSize: 11, fontWeight: 600, overflowWrap: 'anywhere' }}>{value}</div>
                    </div>
                  ))}
                </div>
              </div>

              <div style={{ padding: '14px 18px 10px', borderBottom: '1px solid var(--border)' }}>
                <div style={{ fontSize: 14, fontWeight: 700 }}>批次条目</div>
                <div style={{ marginTop: 4, fontSize: 11, color: 'var(--muted)' }}>每个文件保留独立任务、错误、伴随文件和输出事实。</div>
              </div>

              <div className="batch-runs-item-list">
                {selectedBatch.items.map((item) => {
                  const historyDeleted = item.state === 'history_deleted'
                  const errorMessage = historyDeleted ? '' : itemErrorMessage(item.error, item.message)
                  return (
                    <div className="batch-runs-item" key={item.item_id} style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) 150px', gap: 16, padding: '13px 18px', borderBottom: '1px solid var(--border)', alignItems: 'start' }}>
                      <div style={{ minWidth: 0 }}>
                        <div style={{ fontSize: 12, fontWeight: 700, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{historyDeleted ? `历史已删除 · ${item.group_id || item.item_id}` : fileName(item.input_path)}</div>
                        <div style={{ marginTop: 4, fontSize: 10, color: 'var(--muted)', overflowWrap: 'anywhere' }}>{item.input_path}</div>
                        <div style={{ marginTop: 6, fontSize: 10, color: 'var(--muted)', overflowWrap: 'anywhere' }}>
                          当前任务：{historyDeleted ? '历史已删除' : item.current_task_id || '尚未创建'}
                          {historyDeleted && item.task_ids.length ? ` · 仍保留 ${item.task_ids.length} 条历史尝试` : item.task_ids.length > 1 ? ` · ${item.task_ids.length} 次尝试` : ''}
                        </div>
                        {item.companion_paths.length > 0 ? (
                          <div style={{ marginTop: 5, fontSize: 10, color: 'var(--muted)', overflowWrap: 'anywhere' }}>
                            伴随文件：{item.companion_paths.join('、')}
                          </div>
                        ) : null}
                        {item.message ? <div style={{ marginTop: 6, fontSize: 10, color: 'var(--muted-strong)', overflowWrap: 'anywhere' }}>{item.message}</div> : null}
                        {!historyDeleted && item.output_path ? <div style={{ marginTop: 5, fontSize: 10, color: 'var(--success)', overflowWrap: 'anywhere' }}>输出：{item.output_path}</div> : null}
                        {errorMessage ? <div style={{ marginTop: 5, fontSize: 10, color: 'var(--error)', overflowWrap: 'anywhere' }}>{errorMessage}</div> : null}
                      </div>
                      <div>
                        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, fontSize: 10 }}>
                          <span style={{ color: stateColor(item.state), fontWeight: 700 }}>{STATE_LABELS[item.state] || item.state}</span>
                          {!historyDeleted && <span>{progressPercent(item.progress)}%</span>}
                        </div>
                        {!historyDeleted && <div style={{ marginTop: 6, height: 5, borderRadius: 999, background: 'var(--panel-muted)', overflow: 'hidden' }}>
                          <div style={{ height: '100%', width: `${progressPercent(item.progress)}%`, background: stateColor(item.state) }} />
                        </div>}
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          </>
        )}
      </section>
    </div>
  )
}
