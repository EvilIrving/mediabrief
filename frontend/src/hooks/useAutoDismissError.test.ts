import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { act, renderHook } from '@testing-library/react'
import { useAutoDismissError } from './useAutoDismissError'

describe('useAutoDismissError', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  it('starts empty', () => {
    const { result } = renderHook(() => useAutoDismissError())
    expect(result.current.msg).toBe('')
  })

  it('show sets the message and auto-dismisses after the timeout', () => {
    const { result } = renderHook(() => useAutoDismissError(1000))
    act(() => result.current.show('boom'))
    expect(result.current.msg).toBe('boom')
    act(() => vi.advanceTimersByTime(999))
    expect(result.current.msg).toBe('boom')
    act(() => vi.advanceTimersByTime(1))
    expect(result.current.msg).toBe('')
  })

  it('hide clears the message immediately', () => {
    const { result } = renderHook(() => useAutoDismissError(1000))
    act(() => result.current.show('boom'))
    act(() => result.current.hide())
    expect(result.current.msg).toBe('')
  })

  it('a second show resets the timer', () => {
    const { result } = renderHook(() => useAutoDismissError(1000))
    act(() => result.current.show('first'))
    act(() => vi.advanceTimersByTime(800))
    act(() => result.current.show('second'))
    act(() => vi.advanceTimersByTime(800))
    // 第一个计时器应已被取消，消息仍在
    expect(result.current.msg).toBe('second')
    act(() => vi.advanceTimersByTime(200))
    expect(result.current.msg).toBe('')
  })
})
