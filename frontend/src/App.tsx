import { lazy, Suspense } from 'react'
import AuthGate from './components/AuthGate'
import SessionDraftPage from './pages/SessionDraftPage'
import { isClientPath } from './lib/clientCheckIns'

// Client check-ins (/client) are a separate page for clients, outside the counselor workspace.
const ClientApp = lazy(() => import('./pages/ClientApp'))

const GroundingDemoPage = import.meta.env.DEV
  ? lazy(() => import('./fixtures/dev/GroundingDemoPage'))
  : null

function App() {
  const isLocalGroundingDemo = import.meta.env.DEV
    && new URLSearchParams(window.location.search).get('grounding-demo') === '1'

  if (isLocalGroundingDemo && GroundingDemoPage) {
    return <Suspense fallback={null}><GroundingDemoPage /></Suspense>
  }

  if (isClientPath(window.location.pathname)) {
    return <Suspense fallback={null}><ClientApp /></Suspense>
  }

  return <AuthGate><SessionDraftPage /></AuthGate>
}

export default App
