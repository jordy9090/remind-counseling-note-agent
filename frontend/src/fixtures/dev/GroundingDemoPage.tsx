import SessionDraftPage from '../../pages/SessionDraftPage'
import {
  groundingDemoForm,
  groundingDemoNote,
  groundingDemoSupervisionReport,
} from './groundingDemo'

export default function GroundingDemoPage() {
  return <SessionDraftPage devGroundingDemo={{
    form: groundingDemoForm,
    note: groundingDemoNote,
    supervisionReport: groundingDemoSupervisionReport,
  }} />
}
