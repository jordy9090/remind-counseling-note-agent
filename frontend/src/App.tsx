import { useState } from 'react'

import AuthGate from './components/AuthGate'
import LandingPage from './pages/LandingPage'
import SessionDraftPage from './pages/SessionDraftPage'

function App() {
  const [hasStarted, setHasStarted] = useState(false)

  if (!hasStarted) {
    return <AuthGate><LandingPage onStart={() => setHasStarted(true)} /></AuthGate>
  }

  return <AuthGate><SessionDraftPage /></AuthGate>
}

export default App
