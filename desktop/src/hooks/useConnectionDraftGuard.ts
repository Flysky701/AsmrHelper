import { confirmAction } from '@/utils/confirmAction'
import { useEffect, useRef } from 'react'
import { useNavStore } from '@/stores/navStore'

type State = { dirty: boolean; busy: boolean; onBlocked: (message: string) => void }
const owners = new Map<symbol, { current: State }>()
async function canLeave() {
  for (const owner of owners.values()) {
    if (owner.current.busy) { owner.current.onBlocked('正在处理服务配置，请完成后再离开。'); return false }
  }
  return ![...owners.values()].some(owner => owner.current.dirty)
    || await confirmAction('服务配置有未保存的修改。离开将放弃这些修改，继续吗？')
}

export function useConnectionDraftGuard(state: State, enabled = true) {
  const latest = useRef(state), id = useRef(Symbol('connection-draft'))
  latest.current = state
  useEffect(() => {
    if (!enabled) return
    owners.set(id.current, latest)
    useNavStore.getState().setNavigationGuard(canLeave)
    const beforeUnload = (event: BeforeUnloadEvent) => {
      if (latest.current.dirty || latest.current.busy) { event.preventDefault(); event.returnValue = '' }
    }
    window.addEventListener('beforeunload', beforeUnload)
    return () => {
      owners.delete(id.current)
      if (!owners.size && useNavStore.getState().navigationGuard === canLeave) useNavStore.getState().setNavigationGuard(null)
      window.removeEventListener('beforeunload', beforeUnload)
    }
  }, [enabled])
  return async () => {
    if (latest.current.busy) { latest.current.onBlocked('正在处理服务配置，请稍后再操作。'); return false }
    return !latest.current.dirty || await confirmAction('放弃此服务配置尚未保存的修改？')
  }
}
