import { useState } from 'react'

import LandingPage from './pages/LandingPage'
import SessionDraftPage from './pages/SessionDraftPage'

function App() {
  const [hasStarted, setHasStarted] = useState(false)

  if (!hasStarted) {
    return <LandingPage onStart={() => setHasStarted(true)} />
  }

  return <SessionDraftPage />
}

export default App
