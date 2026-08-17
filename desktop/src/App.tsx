import { useEffect } from 'react'
import { isTauri } from '@tauri-apps/api/core'
import { getCurrentWindow } from '@tauri-apps/api/window'
import AppShell from '@/components/layout/AppShell'
import { useNavStore } from '@/stores/navStore'

function useWindowCloseGuard() {
  useEffect(() => {
    if (!isTauri()) return

    let disposed = false
    let unlisten: (() => void) | undefined

    void getCurrentWindow()
      .onCloseRequested((event) => {
        try {
          if (useNavStore.getState().confirmLeaveCurrentPage()) return
          event.preventDefault()
        } catch (error) {
          // A broken guard must fail closed so unsaved work is never discarded.
          event.preventDefault()
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
