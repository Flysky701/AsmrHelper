import { useAppearanceStore } from './stores/appearanceStore'
import { audioMessages } from './locales/audio'
import { en } from './locales/en'
import { workflowMessages } from './locales/workflow'
import { voiceMessages } from './locales/voices'
import { operationMessages } from './locales/operations'
import { sharedMessages } from './locales/shared'

export const messages: Record<string, string> = {
  ...en,
  ...audioMessages,
  ...workflowMessages,
  ...voiceMessages,
  ...operationMessages,
  ...sharedMessages,
  '外观与语言': 'Appearance & language',
  '界面偏好': 'Display preferences',
  '即时生效，自动保存到此设备。': 'Applied immediately and saved on this device.',
  '界面语言': 'Interface language',
  '仅切换界面文案，素材、音色与模板名称保持原样。': 'Media, voice and template names keep their original text.',
  '背景图片': 'Background image',
  '选择图片': 'Choose image',
  '替换图片': 'Replace image',
  '恢复默认': 'Restore default',
  '默认背景': 'Default background',
  '本机图片副本 · 不上传': 'Local image copy · never uploaded',
  'PNG、JPG 或 WebP，最大 20 MB。保存优化后的本机副本。': 'PNG, JPG or WebP, up to 20 MB. An optimized copy is saved locally.',
  '背景遮罩': 'Background overlay',
  '更清晰': 'Clearer text',
  '更鲜明': 'More visible image',
  '正在处理图片…': 'Preparing image…',
  '已保存': 'Saved',
  'invalidImage': 'Choose a valid PNG, JPG or WebP (up to 20 MB). Try a smaller image if needed.',
  'storageFailed': 'Could not save on this device. Free some storage and try again. Your previous settings are retained.',
  'backgroundUnavailable': 'The saved background is unavailable. Using the default; choose a new image or restore the default.',
}
const zhErrors: Record<string, string> = {
  invalidImage: '请选择有效的 PNG、JPG 或 WebP（不超过 20 MB）；必要时缩小图片后重试。',
  storageFailed: '无法保存到此设备。请清理存储空间后重试，原设置已保留。',
  backgroundUnavailable: '已保存的背景不可用，已回退默认背景。请重新选择图片或恢复默认。',
}
/** Only call for application-owned copy; never pass names, paths or backend content. */
export function t(source: string): string {
  if (useAppearanceStore.getState().language !== 'en') return zhErrors[source] ?? source
  const translated = messages[source.trim()]
  if (translated) return source.replace(source.trim(), translated)
  for (const [pattern, render] of statusPatterns) {
    const match = source.match(pattern)
    if (match) return render(match)
  }
  if (source.length <= 20_000) {
    for (const template of messageTemplates) {
      const match = source.match(template.pattern)
      if (!match) continue
      return template.translation.replace(/\{(\d+)\}/g, (placeholder, index: string) => {
        const group = template.indices.indexOf(index)
        return group < 0 ? placeholder : (match[group + 1] ?? placeholder)
      })
    }
  }
  return source
}
export function format(source: string, values: (string | number)[]): string {
  return t(source).replace(/\{(\d+)\}/g, (_, index: string) => String(values[Number(index)] ?? ''))
}
const statusPatterns: [RegExp, (match: RegExpMatchArray) => string][] = [
  [/^状态刷新失败：([\s\S]+)。当前显示为上次已知状态。$/, m => `Could not refresh status: ${m[1]}. Showing the last known state.`],
  [/^无法读取路径设置：([\s\S]+)。当前输入已保留。$/, m => `Could not load paths: ${m[1]}. Your input is retained.`],
  [/^保存失败：([\s\S]+)。当前输入已保留。$/, m => `Could not save: ${m[1]}. Your input is retained.`],
  [/^扫描失败：([\s\S]+)$/, m => `Scan failed: ${m[1]}`],
  [/^已保留所选路径，文件检查失败：([\s\S]+)。请检查与配对后再运行。$/, m => `Paths retained; file check failed: ${m[1]}. Check and pair inputs before running.`],
  [/^已保存“([\s\S]+)”$/, m => `Saved “${m[1]}”`],
  [/^预设“([\s\S]+)”已删除。$/, m => `Preset “${m[1]}” deleted.`],
]
// Match only catalogued application messages. Captured names, paths and backend
// details are carried through verbatim; they are never translated recursively.
const escapePattern = (text: string) => text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
const messageTemplates = Object.entries(messages)
  .filter(([source]) => /\{\d+\}/.test(source) && /[\u3400-\u9fff]/.test(source))
  .sort(([a], [b]) => b.replace(/\{\d+\}/g, '').length - a.replace(/\{\d+\}/g, '').length)
  .map(([source, translation]) => {
    const indices: string[] = []
    let offset = 0, pattern = '^'
    for (const match of source.matchAll(/\{(\d+)\}/g)) {
      pattern += escapePattern(source.slice(offset, match.index))
      const index = match[1]!
      const existing = indices.indexOf(index)
      if (existing >= 0) pattern += `\\${existing + 1}`
      else { indices.push(index); pattern += '([\\s\\S]*?)' }
      offset = match.index + match[0].length
    }
    return { pattern: new RegExp(pattern + escapePattern(source.slice(offset)) + '$'), translation, indices }
  })
export function useI18n() {
  useAppearanceStore(state => state.language)
  return t
}
