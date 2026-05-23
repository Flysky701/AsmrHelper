import { useCallback } from 'react'

/**
 * File selector hook.
 *
 * In Tauri: uses @tauri-apps/plugin-dialog for native file picker (returns full paths).
 * In browser dev mode: falls back to browser File API (only returns file names — limited).
 */
export function useFileSelector() {
  const selectFiles = useCallback(async (): Promise<string[]> => {
    // Try Tauri native dialog first
    try {
      const { open } = await import('@tauri-apps/plugin-dialog')
      const selected = await open({
        multiple: true,
        filters: [
          {
            name: 'Audio',
            extensions: ['mp3', 'wav', 'flac', 'ogg', 'm4a', 'aac', 'wma'],
          },
        ],
      })
      if (!selected) return []
      // open() returns string | string[] depending on multiple flag
      if (Array.isArray(selected)) return selected
      return [selected]
    } catch {
      // Not in Tauri environment — fall back to browser input
    }

    // Browser fallback (dev mode) — only gets file names, not full paths
    try {
      const input = document.createElement('input')
      input.type = 'file'
      input.multiple = true
      input.accept = 'audio/*,.mp3,.wav,.flac,.ogg,.m4a,.aac,.wma'

      return new Promise((resolve) => {
        input.onchange = () => {
          const files = Array.from(input.files ?? []).map((f) => f.name)
          if (files.length > 0) {
            // In browser mode, prompt user for the actual directory
            const dir = prompt(
              '浏览器模式无法获取完整路径。请输入文件所在目录的完整路径：\n' +
              `（文件名：${files.join(', ')}）`,
              'D:\\Asmr'
            )
            if (dir) {
              const sep = dir.includes('/') ? '/' : '\\'
              resolve(files.map((name) => `${dir}${sep}${name}`))
            } else {
              resolve(files)
            }
          } else {
            resolve([])
          }
        }
        input.oncancel = () => resolve([])
        input.click()
      })
    } catch {
      return []
    }
  }, [])

  const selectFolder = useCallback(async (): Promise<string | null> => {
    // Try Tauri native dialog first
    try {
      const { open } = await import('@tauri-apps/plugin-dialog')
      const selected = await open({
        directory: true,
        multiple: false,
      })
      if (!selected) return null
      return Array.isArray(selected) ? selected[0] ?? null : selected
    } catch {
      // Not in Tauri environment
    }

    // Browser fallback
    try {
      const dir = prompt('请输入文件夹的完整路径：', 'D:\\Asmr')
      return dir || null
    } catch {
      return null
    }
  }, [])

  return { selectFiles, selectFolder }
}
