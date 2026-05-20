import { useEffect, useRef, useCallback } from 'react'

interface UsePollingOptions {
  interval: number
  enabled?: boolean
}

export function usePolling(
  callback: () => void | Promise<void>,
  { interval, enabled = true }: UsePollingOptions,
) {
  const callbackRef = useRef(callback)
  callbackRef.current = callback

  const savedCallback = useCallback(() => {
    void callbackRef.current()
  }, [])

  useEffect(() => {
    if (!enabled) return

    savedCallback()
    const id = setInterval(savedCallback, interval)
    return () => clearInterval(id)
  }, [interval, enabled, savedCallback])
}
