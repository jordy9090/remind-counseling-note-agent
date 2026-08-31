import { useState } from 'react'

import AuthGate from './components/AuthGate'
import LandingPage from './pages/LandingPage'
import SessionDraftPage from './pages/SessionDraftPage'

function App() {
  const [hasStarted, setHasStarted] = useState(false)
  const isLocalGroundingDemo = import.meta.env.DEV
    && new URLSearchParams(window.location.search).get('grounding-demo') === '1'

  if (isLocalGroundingDemo) {
    return <SessionDraftPage />
  }

  if (!hasStarted) {
    return <AuthGate><LandingPage onStart={() => setHasStarted(true)} /></AuthGate>
  }

  return <AuthGate><SessionDraftPage /></AuthGate>
}

export default App
