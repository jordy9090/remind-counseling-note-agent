import { lazy, Suspense } from 'react'
import AuthGate from './components/AuthGate'
import SessionDraftPage from './pages/SessionDraftPage'

const GroundingDemoPage = import.meta.env.DEV
  ? lazy(() => import('./fixtures/dev/GroundingDemoPage'))
  : null

function App() {
  const isLocalGroundingDemo = import.meta.env.DEV
    && new URLSearchParams(window.location.search).get('grounding-demo') === '1'

  if (isLocalGroundingDemo && GroundingDemoPage) {
    return <Suspense fallback={null}><GroundingDemoPage /></Suspense>
  }

  return <AuthGate><SessionDraftPage /></AuthGate>
}

export default App
