import type { ModelDownloadRequest, ModelSummaryResponse } from '@/api/types'
import { format, t } from '@/i18n'
import { confirmAction } from '@/utils/confirmAction'

export const DRAMA3_MODEL_ID = 'fish_drama3'
export const DRAMA3_PROVIDER_ID = 'fish_audio_local'

export function modelDownloadWarning(model: ModelSummaryResponse): string {
  return t(model.download_warning || (model.model_id === DRAMA3_MODEL_ID
    ? '完整权重约 41.50 GB。下载只准备模型文件；推理需在 Linux 或 WSL2 单独启动 SGLang Omni。官方文档给出的语言模型权重约占 37 GB 显存，还需为编解码器和推理缓存留出空间。'
    : ''))
}

export async function prepareModelDownload(model: ModelSummaryResponse): Promise<ModelDownloadRequest | undefined> {
  const request: ModelDownloadRequest = { install_mode: model.default_install_mode || 'single' }
  const warning = modelDownloadWarning(model)
  if (!warning) return request
  const message = format('下载 {0} 的权重？\n\n{1}\n\n请预留足够磁盘空间。', [t(model.display_name), warning])
  if (!await confirmAction(message)) return undefined
  return { ...request, confirm_large_download: true }
}
