import { useEffect, useState } from 'react'

import LandingPage from './pages/LandingPage'
import SessionDraftPage from './pages/SessionDraftPage'
import CounselorDemoPage from './pages/CounselorDemoPage'

type ViewMode = 'landing' | 'demo' | 'full_workflow'

function getInitialMode(): ViewMode {
  if (typeof window === 'undefined') return 'landing'
  const path = window.location.pathname
  const search = window.location.search
  if (path.includes('/demo') || search.includes('demo=true') || search.includes('demo=1')) {
    return 'demo'
  }
  return 'landing'
}

function App() {
  const [viewMode, setViewMode] = useState<ViewMode>(getInitialMode)

  useEffect(() => {
    const handlePopState = () => {
      setViewMode(getInitialMode())
    }
    window.addEventListener('popstate', handlePopState)
    return () => window.removeEventListener('popstate', handlePopState)
  }, [])

  if (viewMode === 'demo') {
    return <CounselorDemoPage onBackToMain={() => setViewMode('landing')} />
  }

  if (viewMode === 'full_workflow') {
    return <SessionDraftPage />
  }

  return (
    <LandingPage
      onStartDemo={() => {
        window.history.pushState({}, '', '?demo=true')
        setViewMode('demo')
      }}
      onStartFullWorkflow={() => setViewMode('full_workflow')}
    />
  )
}

export default App
