import { useCallback, useEffect, useRef, useState } from 'react'

/* Mirrors the original _showError/_hideError: shows a message and
   auto-hides it after `timeout` ms. */
export function useAutoDismissError(timeout = 8000) {
  const [msg, setMsg] = useState('')
  const timer = useRef<number | undefined>(undefined)

  const hide = useCallback(() => {
    setMsg('')
    if (timer.current) {
      clearTimeout(timer.current)
      timer.current = undefined
    }
  }, [])

  const show = useCallback(
    (m: string) => {
      setMsg(m)
      if (timer.current) clearTimeout(timer.current)
      timer.current = window.setTimeout(() => setMsg(''), timeout)
    },
    [timeout],
  )

  useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current)
  }, [])

  return { msg, show, hide }
}
