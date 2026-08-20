import { useEffect } from 'react'
import { isTauri } from '@tauri-apps/api/core'
import { getCurrentWindow } from '@tauri-apps/api/window'
import AppShell from '@/components/layout/AppShell'
import { useNavStore } from '@/stores/navStore'

function useWindowCloseGuard() {
  useEffect(() => {
    if (!isTauri()) return

    const currentWindow = getCurrentWindow()
    let disposed = false
    let unlisten: (() => void) | undefined

    void currentWindow
      .onCloseRequested((event) => {
        event.preventDefault()
        try {
          if (!useNavStore.getState().confirmLeaveCurrentPage()) return
          void currentWindow.destroy().catch((error) => {
            console.error('关闭窗口失败', error)
          })
        } catch (error) {
          // A broken guard must fail closed so unsaved work is never discarded.
          console.error('确认窗口关闭失败', error)
        }
      })
      .then((stopListening) => {
        if (disposed) {
          stopListening()
          return
        }
        unlisten = stopListening
      })
      .catch((error) => {
        console.error('注册窗口关闭保护失败', error)
      })

    return () => {
      disposed = true
      unlisten?.()
    }
  }, [])
}

export default function App() {
  useWindowCloseGuard()
  return <AppShell />
}
