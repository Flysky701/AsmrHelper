import type { ModelStatusResponse, ModelSummaryResponse } from '@/api/types'

/** Model names are capability aliases; a unique registry mapping is required before checking a runtime. */
export function nodeInstallModel(models: ModelSummaryResponse[], category: string, provider: string, model: string | null): ModelSummaryResponse | undefined {
  if (!model) return undefined
  const exact = models.filter(item => item.model_id === model && item.category === category
    && (item.backend === provider || provider === 'qwen3_forced_aligner'))
  if (exact.length === 1) return exact[0]
  if (exact.length > 1) return undefined
  const matches = models.filter(item => item.category === category && item.backend === provider
    && !item.is_auxiliary && item.capability_models?.includes(model))
  return matches.length === 1 ? matches[0] : undefined
}

export function nodeModelStatus(result: ModelStatusResponse): { label: string; detail: string; positive: boolean } {
  if (result.issues.some(issue => /UNVERIFIED|VERIFICATION_FAILED/.test(issue.code))) return { label: '服务未验证', detail: result.detail, positive: false }
  if (result.status === 'ready' || result.status === 'loaded') return { label: result.executable ? '环境检查通过' : '环境尚不可运行', detail: result.detail, positive: result.executable }
  const labels: Record<string, string> = { missing: '缺少模型或环境', not_installed: '尚未安装', invalid: '环境配置异常', installed: '模型已安装，运行待确认', configured: '已配置，运行待确认', unconfigured: '尚未配置', installing: '正在安装', unknown: '状态未知' }
  return { label: labels[result.status] || '状态未知', detail: result.detail, positive: false }
}
