import { useCallback } from 'react'

// For web dev mode, uses the browser File System Access API.
// In Tauri, this will be replaced with @tauri-apps/plugin-dialog.

export function useFileSelector() {
  const selectFiles = useCallback(async (): Promise<string[]> => {
    try {
      const input = document.createElement('input')
      input.type = 'file'
      input.multiple = true
      input.accept = 'audio/*,.mp3,.wav,.flac,.ogg,.m4a,.aac,.wma'

      return new Promise((resolve) => {
        input.onchange = () => {
          const files = Array.from(input.files ?? []).map((f) => f.name)
          resolve(files)
        }
        input.oncancel = () => resolve([])
        input.click()
      })
    } catch {
      return []
    }
  }, [])

  const selectFolder = useCallback(async (): Promise<string | null> => {
    // Browser doesn't support folder selection in the same way
    // In Tauri this will use the native dialog
    try {
      const input = document.createElement('input')
      input.type = 'file'
      ;(input as HTMLInputElement & { webkitdirectory: boolean }).webkitdirectory = true

      return new Promise((resolve) => {
        input.onchange = () => {
          const files = input.files
          if (files && files.length > 0) {
            // Extract folder path from first file
            const path = files[0]?.webkitRelativePath?.split('/')[0] ?? null
            resolve(path)
          } else {
            resolve(null)
          }
        }
        input.oncancel = () => resolve(null)
        input.click()
      })
    } catch {
      return null
    }
  }, [])

  return { selectFiles, selectFolder }
}
