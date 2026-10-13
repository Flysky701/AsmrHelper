import starterSubtitle from '../../../docs/examples/first-use.zh.srt?raw'
import { useI18n } from '@/i18n'

export default function QuickStartHelp() {
  const t = useI18n()
  return <details className="queue-quick-start">
    <summary>{t('快速上手')}</summary>
    <p>{t('选择“演示预设 · 中文配音”，导入中文字幕并核对语言，然后勾选素材组开始处理。')}</p>
    <p>{t('Edge 晓晓无需模型或 API 密钥；字幕文本会发送到 Edge 语音服务。')}</p>
    <details><summary>{t('字幕示例（保存为 UTF-8 的 first-use.zh.srt）')}</summary><pre>{starterSubtitle}</pre></details>
    <p>{t('失败时检查网络、字幕时间轴/语言和输出目录权限；在任务中心查看错误与结果。')}</p>
    <p>{t('完整指南：')}<code>docs/guides/quick-start.md</code></p>
  </details>
}
