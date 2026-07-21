import { useEffect, useState } from 'react'

import LandingPage from './pages/LandingPage'
import SessionDraftPage from './pages/SessionDraftPage'
import CounselorDemoPage from './pages/CounselorDemoPage'

function isCounselorDemoRoute(): boolean {
  if (typeof window === 'undefined') return false
  const path = window.location.pathname
  const search = window.location.search
  return (
    path.startsWith('/demo') ||
    path === '/demo/counselor-review' ||
    search.includes('demo=counselor-review') ||
    search.includes('demo=true')
  )
}

function App() {
  const [isDemo, setIsDemo] = useState(isCounselorDemoRoute)
  const [hasStarted, setHasStarted] = useState(false)

  useEffect(() => {
    const handlePopState = () => {
      setIsDemo(isCounselorDemoRoute())
    }
    window.addEventListener('popstate', handlePopState)
    return () => window.removeEventListener('popstate', handlePopState)
  }, [])

  if (isDemo) {
    return (
      <CounselorDemoPage
        onBackToMain={() => {
          window.history.pushState({}, '', '/')
          setIsDemo(false)
        }}
      />
    )
  }

  if (!hasStarted) {
    return <LandingPage onStart={() => setHasStarted(true)} />
  }

  return <SessionDraftPage />
}

export default App
