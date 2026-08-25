import AuthGate from './components/AuthGate'
import SessionDraftPage from './pages/SessionDraftPage'

function App() {
  return <AuthGate><SessionDraftPage /></AuthGate>
}

export default App
