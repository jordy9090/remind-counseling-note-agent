"""Review-only changes bypass duplicate model verification without losing risks."""
import unittest

from app.graph.graph import _route_after_revision
from app.graph.nodes import conditional_revision
from app.schemas.note import ReviewableClaim, SessionInfo, SessionSummaryDraft, SummarySection, VerificationReport


class RevisionRoutingTests(unittest.TestCase):
    def test_review_flags_keep_text_and_risks_and_route_to_preview(self):
        fields = ("session_theme", "presenting_problem", "session_content", "counselor_intervention", "client_response", "reflection", "next_plan")
        summary = SessionSummaryDraft(
            session_info=SessionInfo(case_id="SYNTH-REVIEW", session_number=1, session_date="2026-10-02"),
            **{field: SummarySection(text="Synthetic unchanged text", evidence_type="inferred") for field in fields},
        )
        verification = VerificationReport(
            unsupported_or_risky_claims=[ReviewableClaim(claim="Synthetic risk", reason="Unsupported", recommendation="Counselor review")],
            weakly_grounded_items=[ReviewableClaim(claim="Synthetic uncertainty", reason="Missing detail", recommendation="Verify")],
        )
        state = {"session_summary_draft": summary, "verification_report": verification}
        original_report = verification.model_dump()
        state.update(conditional_revision(state))
        self.assertEqual("preview", _route_after_revision(state))
        self.assertEqual(original_report, state["verification_report"].model_dump())
        self.assertEqual(original_report, state["initial_verification_report"].model_dump())
        for field in fields:
            self.assertEqual(getattr(summary, field).text, getattr(state["session_summary_draft"], field).text)
            self.assertTrue(getattr(state["session_summary_draft"], field).requires_review)
            self.assertFalse(getattr(summary, field).requires_review)


if __name__ == "__main__":
    unittest.main()
