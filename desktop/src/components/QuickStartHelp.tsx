import starterSubtitle from '../../../docs/examples/first-use.zh.srt?raw'

export default function QuickStartHelp() {
  return <details className="queue-quick-start">
    <summary>快速上手 · 第一份配音</summary>
    <p>选择“演示预设 · 中文配音”。Edge 在线晓晓音色无需模型或 API 密钥；字幕文本会发送到 Edge 语音服务。</p>
    <ol>
      <li>准备中文字幕 SRT / VTT / LRC。可将下方示例保存为 UTF-8 的 <code>first-use.zh.srt</code>（不要带 .txt 后缀）。</li>
      <li>点击下方“导入文件”，展开素材组核对“中文字幕”槽；语言未知时选中文并勾选“确认字幕实际语言”。无需配对音频。</li>
      <li>勾选该组，点击“开始处理”，在“任务中心”查看批次、错误与音频产物。“输出位置”留空使用工作区默认目录。</li>
    </ol>
    <pre aria-label="中文字幕示例">{starterSubtitle}</pre>
    <p>只有文本：在“声音与音色 → 试听与记录”载入“Edge 中文·晓晓”，输入“试音原文”并点击“生成试音”。</p>
    <p>失败先核对网络、字幕时间轴/语言和目录权限。工作目录见“设置 → 文件与缓存”，更改后重启；可选模型在“引擎与资源”分别准备权重与运行环境。源码完整指南：<code>docs/guides/quick-start.md</code>。</p>
  </details>
}
