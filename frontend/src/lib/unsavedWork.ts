import { useEffect, useRef } from 'react'

// Only active component registrations live here; no counseling content is retained.
const activeWork = new Set<symbol>()
const warnBeforeUnload = (event: BeforeUnloadEvent) => {
  if (!activeWork.size) return
  event.preventDefault()
  event.returnValue = ''
}

export function useUnsavedWork(dirty: boolean): void {
  const registration = useRef(Symbol('unsaved-work'))
  useEffect(() => {
    if (!dirty) return
    const key = registration.current
    if (!activeWork.size) window.addEventListener('beforeunload', warnBeforeUnload)
    activeWork.add(key)
    return () => {
      activeWork.delete(key)
      if (!activeWork.size) window.removeEventListener('beforeunload', warnBeforeUnload)
    }
  }, [dirty])
}

export function confirmDiscardWork(): boolean {
  return !activeWork.size || window.confirm('아직 저장하지 않은 내용이나 진행 중인 작업이 있습니다. 작업을 종료하고 나가시겠어요?')
}
