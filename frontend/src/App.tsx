import AuthGate from './components/AuthGate'
import SessionDraftPage from './pages/SessionDraftPage'

function App() {
  const isLocalGroundingDemo = import.meta.env.DEV
    && new URLSearchParams(window.location.search).get('grounding-demo') === '1'

  if (isLocalGroundingDemo) {
    return <SessionDraftPage />
  }

  return <AuthGate><SessionDraftPage /></AuthGate>
}

export default App
