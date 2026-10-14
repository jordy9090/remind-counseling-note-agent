"""Offline retention planner checks. Durations below are synthetic, not policy."""
from __future__ import annotations

import copy
import io
import json
import struct
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import ValidationError

from app.services.retention_planning import PlanningRequest, main, plan_retention


def request_data():
    return {
        "schema_version": 1,
        "as_of": "2026-10-14T12:00:00+09:00",
        "policies": [{
            "policy_id": "synthetic-cache", "version": "test-v1", "category": "cache",
            "purpose_ref": "synthetic-purpose", "scope_ref": "synthetic-scope",
            "decision_ref": "synthetic-approval", "effective_from": "2020-01-01T00:00:00Z",
            "preservation_assessment": "none_applicable", "preservation": None,
            "deletion": {"basis_ref": "synthetic-operational-basis", "trigger": "purpose_ended",
                         "period": {"amount": 2, "unit": "elapsed_days"}},
        }],
        "artifacts": [{
            "artifact_ref": "synthetic-artifact", "category": "cache",
            "purpose_ref": "synthetic-purpose", "scope_ref": "synthetic-scope",
            "policy_refs": [{"policy_id": "synthetic-cache", "version": "test-v1"}],
            "events": {"purpose_ended": "2026-10-12T03:00:00Z"},
            "hold_review": "complete", "holds": [], "copy_inventory_complete": True,
            "copies": [{"copy_ref": "synthetic-primary", "location": "primary", "state": "present",
                        "observed_at": "2026-10-14T03:00:00Z"}],
        }],
    }


def planned(data):
    return plan_retention(PlanningRequest.model_validate(data)).artifacts[0]


def synthetic_dst_zone():
    """Two synthetic transitions test calendar logic without host timezone data."""
    transitions = [int(datetime(2024, 3, 10, 7, tzinfo=UTC).timestamp()),
                   int(datetime(2024, 11, 3, 6, tzinfo=UTC).timestamp())]
    data = (b"TZif\0" + b"\0" * 15 + struct.pack(">6l", 0, 0, 0, 2, 2, 8)
            + struct.pack(">2l", *transitions) + bytes([1, 0])
            + struct.pack(">lbb", -18000, 0, 0) + struct.pack(">lbb", -14400, 1, 4)
            + b"STD\0DST\0")
    return ZoneInfo.from_file(io.BytesIO(data), key="Synthetic/Eastern")


class RetentionPlanningTests(unittest.TestCase):
    def test_equal_instants_and_exact_deadline_are_eligible_without_side_effects(self):
        data = request_data()
        original = copy.deepcopy(data)
        request = PlanningRequest.model_validate(data)
        first = plan_retention(request)
        second = plan_retention(request)
        self.assertEqual(first, second)
        self.assertEqual(data, original)
        self.assertEqual(first.artifacts[0].status, "eligible")
        self.assertEqual(first.artifacts[0].delete_after.isoformat(), "2026-10-14T03:00:00+00:00")
        self.assertEqual(first.artifacts[0].copies[0].next_step, "plan_local_deletion")
        self.assertFalse(first.execution_performed)
        self.assertFalse(first.erasure_verified)

    def test_missing_policy_is_unknown_and_environment_has_no_policy_authority(self):
        data = request_data()
        data["policies"] = []
        result = planned(data)
        self.assertEqual(result.status, "unknown")
        self.assertIn("policy_version_unknown", result.reasons)
        self.assertEqual(result.copies[0].next_step, "blocked")

    def test_unselected_or_mismatched_policy_never_becomes_eligible(self):
        for update, reason in (({"policy_refs": []}, "policy_not_selected"),
                               ({"category": "confirmed_record"}, "policy_applicability_mismatch"),
                               ({"scope_ref": "other-scope"}, "policy_applicability_mismatch")):
            with self.subTest(reason=reason):
                data = request_data()
                data["artifacts"][0].update(update)
                result = planned(data)
                self.assertEqual(result.status, "unknown")
                self.assertIn(reason, result.reasons)

    def test_missing_future_and_naive_trigger_data_are_not_assumed(self):
        for events, reason in (({}, "deletion_trigger_missing"),
                               ({"purpose_ended": "2027-01-01T00:00:00Z"}, "deletion_trigger_not_yet_occurred")):
            data = request_data()
            data["artifacts"][0]["events"] = events
            self.assertEqual(planned(data).status, "unknown")
            self.assertIn(reason, planned(data).reasons)
        data["artifacts"][0]["events"] = {"purpose_ended": "2026-10-12T03:00:00"}
        with self.assertRaises(ValidationError):
            PlanningRequest.model_validate(data)

    def test_missing_preservation_assessment_or_deletion_schedule_blocks(self):
        data = request_data()
        data["policies"][0]["preservation_assessment"] = "unresolved"
        self.assertIn("preservation_basis_unresolved", planned(data).reasons)
        data["policies"][0]["deletion"] = None
        self.assertEqual(planned(data).status, "unknown")
        self.assertIn("deletion_schedule_unknown", planned(data).reasons)

    def test_calendar_years_preserve_leap_days_and_require_explicit_overflow(self):
        for overflow, expected in (("month_end", "2025-02-28T03:00:00+00:00"),
                                   ("next_month_start", "2025-03-01T03:00:00+00:00")):
            data = request_data()
            data["artifacts"][0]["events"]["purpose_ended"] = "2024-02-29T12:00:00+09:00"
            data["policies"][0]["deletion"]["period"] = {
                "amount": 1, "unit": "calendar_years", "timezone": "UTC+09:00", "overflow": overflow,
            }
            self.assertEqual(planned(data).delete_after.isoformat(), expected)
        data["artifacts"][0]["events"]["purpose_ended"] = "2023-03-01T12:00:00+09:00"
        self.assertEqual(planned(data).delete_after.isoformat(), "2024-03-01T03:00:00+00:00")
        del data["policies"][0]["deletion"]["period"]["overflow"]
        with self.assertRaises(ValidationError):
            PlanningRequest.model_validate(data)

    def test_calendar_month_end_rollover_and_dst_change(self):
        zone_patch = patch("app.services.retention_planning.ZoneInfo", return_value=synthetic_dst_zone())
        zone_patch.start()
        self.addCleanup(zone_patch.stop)
        data = request_data()
        data["policies"][0]["deletion"]["period"] = {
            "amount": 1, "unit": "calendar_months", "timezone": "Synthetic/Eastern", "overflow": "month_end",
        }
        data["artifacts"][0]["events"]["purpose_ended"] = "2024-01-31T12:00:00-05:00"
        self.assertEqual(planned(data).delete_after.isoformat(), "2024-02-29T17:00:00+00:00")
        data["artifacts"][0]["events"]["purpose_ended"] = "2024-02-15T12:00:00-05:00"
        self.assertEqual(planned(data).delete_after.isoformat(), "2024-03-15T16:00:00+00:00")

    def test_ambiguous_and_nonexistent_dst_deadlines_require_review(self):
        zone_patch = patch("app.services.retention_planning.ZoneInfo", return_value=synthetic_dst_zone())
        zone_patch.start()
        self.addCleanup(zone_patch.stop)
        for trigger in ("2024-02-10T02:30:00-05:00", "2024-10-03T01:30:00-04:00"):
            data = request_data()
            data["artifacts"][0]["events"]["purpose_ended"] = trigger
            data["policies"][0]["deletion"]["period"] = {
                "amount": 1, "unit": "calendar_months", "timezone": "Synthetic/Eastern", "overflow": "month_end",
            }
            result = planned(data)
            self.assertEqual(result.status, "unknown")
            self.assertIn("deletion_calendar_deadline_ambiguous_or_nonexistent", result.reasons)

    def test_unavailable_named_timezone_is_rejected_without_approximation(self):
        data = request_data()
        data["policies"][0]["deletion"]["period"] = {
            "amount": 1, "unit": "calendar_years", "timezone": "Missing/Zone", "overflow": "month_end",
        }
        with patch("app.services.retention_planning.ZoneInfo", side_effect=ZoneInfoNotFoundError), self.assertRaises(ValidationError):
            PlanningRequest.model_validate(data)

    def test_conflicting_preservation_and_operational_thresholds_do_not_pick_longest(self):
        data = request_data()
        policy = data["policies"][0]
        policy["preservation_assessment"] = "specified"
        policy["preservation"] = {"basis_ref": "synthetic-preservation", "trigger": "purpose_ended",
                                  "period": {"amount": 3, "unit": "elapsed_days"}}
        result = planned(data)
        self.assertEqual(result.status, "conflict")
        self.assertGreater(result.preserve_until, result.delete_after)
        self.assertEqual(result.copies[0].next_step, "blocked")

    def test_multiple_policy_versions_require_resolution(self):
        data = request_data()
        policy = copy.deepcopy(data["policies"][0])
        policy["version"] = "test-v2"
        data["policies"].append(policy)
        data["artifacts"][0]["policy_refs"].append({"policy_id": policy["policy_id"], "version": "test-v2"})
        result = planned(data)
        self.assertEqual(result.status, "conflict")
        self.assertIsNone(result.delete_after)

    def test_active_hold_and_verified_release(self):
        data = request_data()
        hold = {"hold_ref": "synthetic-hold", "basis_ref": "synthetic-hold-basis",
                "started_at": "2026-10-10T00:00:00Z"}
        data["artifacts"][0]["holds"] = [hold]
        self.assertEqual(planned(data).status, "protected")
        hold["released_at"] = "2026-10-13T00:00:00Z"
        with self.assertRaises(ValidationError):
            PlanningRequest.model_validate(data)
        hold["release_evidence_ref"] = "synthetic-release"
        self.assertEqual(planned(data).status, "eligible")
        hold["released_at"] = "2026-10-15T00:00:00Z"
        self.assertEqual(planned(data).status, "unknown")

    def test_python_dst_fold_inputs_compare_instants_in_every_time_gate(self):
        zone = synthetic_dst_zone()
        earlier = datetime(2024, 11, 3, 1, 30, tzinfo=zone, fold=0)
        later = datetime(2024, 11, 3, 1, 15, tzinfo=zone, fold=1)
        self.assertLess(earlier.astimezone(UTC), later.astimezone(UTC))
        for gate, reason in (("hold", "hold_evidence_from_future"),
                             ("policy", "policy_not_effective"),
                             ("trigger", "deletion_trigger_not_yet_occurred"),
                             ("copy", "copy_state_unknown")):
            with self.subTest(gate=gate):
                data = request_data()
                data["as_of"] = earlier
                artifact = data["artifacts"][0]
                artifact["events"]["purpose_ended"] = "2024-10-01T00:00:00Z"
                artifact["copies"][0]["observed_at"] = earlier
                if gate == "hold":
                    artifact["holds"] = [{"hold_ref": "synthetic-hold", "basis_ref": "synthetic-basis",
                        "started_at": "2024-10-01T00:00:00Z", "released_at": later,
                        "release_evidence_ref": "synthetic-release"}]
                elif gate == "policy":
                    data["policies"][0]["effective_from"] = later
                elif gate == "trigger":
                    artifact["events"]["purpose_ended"] = later
                else:
                    artifact["copies"][0]["observed_at"] = later
                result = planned(data)
                self.assertEqual(result.status, "unknown")
                self.assertIn(reason, result.reasons)
                self.assertNotEqual(result.copies[0].next_step, "plan_local_deletion")
        data = request_data()
        data["as_of"] = later
        data["policies"][0].update(effective_from=earlier, effective_until=later)
        request = PlanningRequest.model_validate(data)
        self.assertLess(request.policies[0].effective_from, request.policies[0].effective_until)

    def test_preservation_and_unreached_operational_thresholds_are_protected(self):
        data = request_data()
        data["as_of"] = "2026-10-13T03:00:00Z"
        data["artifacts"][0]["copies"][0]["observed_at"] = data["as_of"]
        self.assertIn("deletion_threshold_not_reached", planned(data).reasons)
        policy = data["policies"][0]
        policy["preservation_assessment"] = "specified"
        policy["preservation"] = copy.deepcopy(policy["deletion"])
        result = planned(data)
        self.assertEqual(result.status, "protected")
        self.assertIn("preservation_active", result.reasons)

    def test_incomplete_inventory_unknown_hold_review_and_future_observations_block(self):
        for field, value, reason in (("copy_inventory_complete", False, "copy_inventory_incomplete"),
                                     ("hold_review", "unknown", "hold_review_unknown")):
            data = request_data()
            data["artifacts"][0][field] = value
            self.assertEqual(planned(data).status, "unknown")
            self.assertIn(reason, planned(data).reasons)
        data = request_data()
        data["artifacts"][0]["copies"][0]["observed_at"] = "2027-01-01T00:00:00Z"
        self.assertEqual(planned(data).local_copies, "unknown")
        self.assertEqual(planned(data).copies[0].next_step, "verify_state")

    def test_local_reported_deletion_does_not_claim_provider_or_backup_erasure(self):
        data = request_data()
        copies = data["artifacts"][0]["copies"]
        copies[0].update(state="deletion_confirmed", evidence_ref="synthetic-local-proof")
        copies.extend([
            {"copy_ref": "synthetic-provider", "location": "provider", "state": "deletion_pending",
             "observed_at": data["as_of"]},
            {"copy_ref": "synthetic-backup", "location": "backup", "state": "present",
             "observed_at": data["as_of"]},
        ])
        plan = plan_retention(PlanningRequest.model_validate(data))
        result = plan.artifacts[0]
        self.assertEqual(result.local_copies, "reported_deleted")
        self.assertEqual(result.provider_copies, "pending")
        self.assertEqual(result.backup_copies, "remaining")
        self.assertEqual([item.next_step for item in result.copies],
                         ["retain_deletion_evidence", "provider_followup", "backup_followup"])
        self.assertFalse(plan.erasure_verified)

    def test_expired_and_future_policies_are_unknown(self):
        for field, value in (("effective_from", "2027-01-01T00:00:00Z"),
                              ("effective_until", "2026-10-14T03:00:00Z")):
            data = request_data()
            data["policies"][0][field] = value
            self.assertIn("policy_not_effective", planned(data).reasons)

    def test_unsupported_configuration_and_payload_fields_are_rejected(self):
        changes = [
            lambda data: data["artifacts"][0].update(transcript_text="SYNTHETIC_PRIVATE_CONTENT"),
            lambda data: data["policies"][0]["deletion"]["period"].update(unit="business_days"),
            lambda data: data["policies"][0]["deletion"]["period"].update(amount=True),
            lambda data: data["policies"][0]["deletion"]["period"].update(amount=-1),
            lambda data: data["policies"].append(copy.deepcopy(data["policies"][0])),
            lambda data: data["artifacts"][0]["copies"][0].update(state="deletion_confirmed"),
            lambda data: data.update(schema_version=2),
            lambda data: data.update(schema_version=True),
            lambda data: data["artifacts"][0]["events"].update(purpose_ended=1791799200),
            lambda data: data["artifacts"][0].update(copy_inventory_complete="true"),
            lambda data: data.update(as_of="0001-01-01T00:00:00+23:59"),
            lambda data: data.update(as_of="9999-12-31T23:59:59-23:59"),
        ]
        for mutate in changes:
            data = request_data()
            mutate(data)
            with self.subTest(mutation=changes.index(mutate)), self.assertRaises(ValidationError):
                PlanningRequest.model_validate(data)

    def test_cli_reads_metadata_without_writing_and_sanitizes_invalid_input(self):
        with tempfile.TemporaryDirectory(prefix="remind-retention-planner-") as directory:
            path = Path(directory) / "synthetic.json"
            data = request_data()
            path.write_text(json.dumps(data), encoding="utf-8")
            original = path.read_bytes()
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(main([str(path)]), 0)
            self.assertFalse(json.loads(output.getvalue())["execution_performed"])
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(list(Path(directory).iterdir()), [path])
            data["artifacts"][0]["transcript_text"] = "SYNTHETIC_PRIVATE_CONTENT"
            path.write_text(json.dumps(data), encoding="utf-8")
            error = io.StringIO()
            with redirect_stderr(error), redirect_stdout(io.StringIO()):
                self.assertEqual(main([str(path)]), 2)
            self.assertNotIn("SYNTHETIC_PRIVATE_CONTENT", error.getvalue())
            self.assertNotIn(str(path), error.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=2)
