"""Deterministic, metadata-only retention planning. This module never deletes data."""
from __future__ import annotations

import argparse
import calendar
import re
import sys
from datetime import UTC, datetime, timedelta, timezone, tzinfo
from pathlib import Path
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AwareDatetime, BaseModel, BeforeValidator, ConfigDict, Field, ValidationError, field_validator, model_validator


Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9_.:-]{1,128}$")]


def _explicit_timestamp(value: object) -> datetime:
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Timestamps require an explicit UTC offset")
    # ZoneInfo datetimes sharing a zone compare wall times across a DST fold.
    # Normalize first so all policy, hold and observation gates compare instants.
    try:
        return value.astimezone(UTC)
    except OverflowError:
        raise ValueError("Timestamp is outside the supported UTC range") from None


Timestamp = Annotated[AwareDatetime, BeforeValidator(_explicit_timestamp)]


class MetadataModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _timezone(name: str) -> tzinfo:
    if name == "UTC":
        return UTC
    fixed = re.fullmatch(r"UTC([+-])([01]\d|2[0-3]):([0-5]\d)", name)
    if fixed:
        offset = timedelta(hours=int(fixed[2]), minutes=int(fixed[3]))
        return timezone(offset if fixed[1] == "+" else -offset)
    return ZoneInfo(name)


class Period(MetadataModel):
    amount: Annotated[int, Field(strict=True, ge=0, le=10000)]
    unit: Literal["elapsed_days", "calendar_months", "calendar_years"]
    timezone: str | None = None
    overflow: Literal["month_end", "next_month_start"] | None = None

    @model_validator(mode="after")
    def validate_calendar_options(self) -> "Period":
        if self.unit == "elapsed_days":
            if self.timezone is not None or self.overflow is not None:
                raise ValueError("Elapsed days do not accept calendar options")
        else:
            if self.timezone is None or self.overflow is None:
                raise ValueError("Calendar periods require an explicit timezone and overflow rule")
            try:
                _timezone(self.timezone)
            except (ZoneInfoNotFoundError, ValueError):
                raise ValueError("Unsupported calendar timezone") from None
        return self


class DeadlineRule(MetadataModel):
    basis_ref: Identifier
    trigger: Identifier
    period: Period


class PolicyReference(MetadataModel):
    policy_id: Identifier
    version: Identifier


class RetentionPolicy(PolicyReference):
    category: Identifier
    purpose_ref: Identifier
    scope_ref: Identifier
    decision_ref: Identifier
    effective_from: Timestamp
    effective_until: Timestamp | None = None
    preservation_assessment: Literal["none_applicable", "specified", "unresolved"]
    preservation: DeadlineRule | None
    deletion: DeadlineRule | None

    @model_validator(mode="after")
    def validate_policy(self) -> "RetentionPolicy":
        if (self.preservation_assessment == "specified") != (self.preservation is not None):
            raise ValueError("Preservation rule must agree with its assessment")
        if self.effective_until is not None and self.effective_until <= self.effective_from:
            raise ValueError("Policy effective interval must be nonempty")
        return self


class PreservationHold(MetadataModel):
    hold_ref: Identifier
    basis_ref: Identifier
    started_at: Timestamp
    released_at: Timestamp | None = None
    release_evidence_ref: Identifier | None = None

    @model_validator(mode="after")
    def validate_release(self) -> "PreservationHold":
        if (self.released_at is None) != (self.release_evidence_ref is None):
            raise ValueError("A recorded hold release requires time and evidence reference")
        if self.released_at is not None and self.released_at < self.started_at:
            raise ValueError("A hold cannot be released before it starts")
        return self


class CopyMetadata(MetadataModel):
    copy_ref: Identifier
    location: Literal["primary", "derivative", "cache", "export", "provider", "backup"]
    state: Literal["present", "deletion_pending", "deletion_confirmed", "unknown"]
    observed_at: Timestamp
    evidence_ref: Identifier | None = None

    @model_validator(mode="after")
    def validate_evidence(self) -> "CopyMetadata":
        if self.state == "deletion_confirmed" and self.evidence_ref is None:
            raise ValueError("Reported deletion requires an evidence reference")
        return self


class ArtifactMetadata(MetadataModel):
    artifact_ref: Identifier
    category: Identifier
    purpose_ref: Identifier
    scope_ref: Identifier
    policy_refs: list[PolicyReference]
    events: dict[Identifier, Timestamp]
    hold_review: Literal["complete", "unknown"]
    holds: list[PreservationHold]
    copy_inventory_complete: Annotated[bool, Field(strict=True)]
    copies: list[CopyMetadata]

    @model_validator(mode="after")
    def validate_unique_metadata(self) -> "ArtifactMetadata":
        for identifiers in (
            [copy.copy_ref for copy in self.copies],
            [hold.hold_ref for hold in self.holds],
            [(ref.policy_id, ref.version) for ref in self.policy_refs],
        ):
            if len(identifiers) != len(set(identifiers)):
                raise ValueError("Duplicate metadata references are unsupported")
        return self


class PlanningRequest(MetadataModel):
    schema_version: Literal[1]
    as_of: Timestamp
    policies: list[RetentionPolicy]
    artifacts: list[ArtifactMetadata]

    @field_validator("schema_version", mode="before")
    @classmethod
    def validate_schema_version(cls, value: object) -> object:
        if type(value) is not int or value != 1:
            raise ValueError("Unsupported schema version")
        return value

    @model_validator(mode="after")
    def validate_unique_inputs(self) -> "PlanningRequest":
        policy_keys = [(policy.policy_id, policy.version) for policy in self.policies]
        artifact_keys = [artifact.artifact_ref for artifact in self.artifacts]
        if len(policy_keys) != len(set(policy_keys)) or len(artifact_keys) != len(set(artifact_keys)):
            raise ValueError("Duplicate policy versions or artifact references are unsupported")
        return self


class CopyPlan(MetadataModel):
    copy_ref: Identifier
    location: str
    reported_state: str
    observed_at: AwareDatetime
    evidence_ref: Identifier | None
    next_step: Literal["blocked", "verify_state", "plan_local_deletion", "provider_followup",
                       "backup_followup", "retain_deletion_evidence"]


class ArtifactPlan(MetadataModel):
    artifact_ref: Identifier
    category: Identifier
    purpose_ref: Identifier
    scope_ref: Identifier
    policy_refs: list[PolicyReference]
    policy_decision_ref: Identifier | None
    preservation_basis_ref: Identifier | None
    deletion_basis_ref: Identifier | None
    status: Literal["unknown", "conflict", "protected", "eligible"]
    reasons: list[str]
    preserve_until: AwareDatetime | None
    delete_after: AwareDatetime | None
    local_copies: Literal["unknown", "not_in_inventory", "remaining", "pending", "reported_deleted"]
    provider_copies: Literal["unknown", "not_in_inventory", "remaining", "pending", "reported_deleted"]
    backup_copies: Literal["unknown", "not_in_inventory", "remaining", "pending", "reported_deleted"]
    copies: list[CopyPlan]


class RetentionPlan(MetadataModel):
    schema_version: Literal[1] = 1
    as_of: AwareDatetime
    execution_performed: Literal[False] = False
    erasure_verified: Literal[False] = False
    artifacts: list[ArtifactPlan]


class DeadlineUnresolved(ValueError):
    """A supplied calendar rule cannot determine a unique supported instant."""


def _deadline(trigger: datetime, period: Period) -> datetime:
    try:
        if period.amount == 0:
            return trigger.astimezone(UTC)
        if period.unit == "elapsed_days":
            return trigger.astimezone(UTC) + timedelta(days=period.amount)
        zone = _timezone(period.timezone)
        local = trigger.astimezone(zone)
        months = period.amount * (12 if period.unit == "calendar_years" else 1)
        month_index = local.year * 12 + local.month - 1 + months
        year, month = divmod(month_index, 12)
        month += 1
        last_day = calendar.monthrange(year, month)[1]
        day = local.day
        if day > last_day:
            if period.overflow == "month_end":
                day = last_day
            else:
                year, month = divmod(year * 12 + month, 12)
                month += 1
                day = 1
        wall = local.replace(year=year, month=month, day=day, tzinfo=None)
        instants = set()
        for fold in (0, 1):
            candidate = wall.replace(tzinfo=zone, fold=fold).astimezone(UTC)
            if candidate.astimezone(zone).replace(tzinfo=None) == wall:
                instants.add(candidate)
        if len(instants) != 1:
            raise DeadlineUnresolved("calendar_deadline_ambiguous_or_nonexistent")
        return instants.pop()
    except (OverflowError, ValueError) as error:
        if isinstance(error, DeadlineUnresolved):
            raise
        raise DeadlineUnresolved("deadline_out_of_supported_range") from None


def _rule_deadline(rule: DeadlineRule | None, artifact: ArtifactMetadata, as_of: datetime,
                   name: str, reasons: list[str]) -> datetime | None:
    if rule is None:
        return None
    trigger = artifact.events.get(rule.trigger)
    if trigger is None:
        reasons.append(f"{name}_trigger_missing")
        return None
    if trigger > as_of:
        reasons.append(f"{name}_trigger_not_yet_occurred")
        return None
    try:
        return _deadline(trigger, rule.period)
    except DeadlineUnresolved as error:
        reasons.append(f"{name}_{error}")
        return None


def _copy_summary(copies: list[CopyMetadata], complete: bool, as_of: datetime) -> str:
    if not complete or any(copy.state == "unknown" or copy.observed_at > as_of for copy in copies):
        return "unknown"
    if not copies:
        return "not_in_inventory"
    if any(copy.state == "present" for copy in copies):
        return "remaining"
    if any(copy.state == "deletion_pending" for copy in copies):
        return "pending"
    return "reported_deleted"


def _plan_artifact(artifact: ArtifactMetadata, policies: dict[tuple[str, str], RetentionPolicy],
                   as_of: datetime) -> ArtifactPlan:
    reasons: list[str] = []
    preserve_until = delete_after = None
    decision_ref = preservation_basis_ref = deletion_basis_ref = None
    selected = [policies.get((ref.policy_id, ref.version)) for ref in artifact.policy_refs]
    conflict = len(selected) > 1
    if conflict:
        reasons.append("multiple_policies_require_explicit_resolution")
    elif not selected:
        reasons.append("policy_not_selected")
    elif selected[0] is None:
        reasons.append("policy_version_unknown")
    else:
        policy = selected[0]
        if (policy.category, policy.purpose_ref, policy.scope_ref) != (
            artifact.category, artifact.purpose_ref, artifact.scope_ref
        ):
            reasons.append("policy_applicability_mismatch")
        elif as_of < policy.effective_from or (policy.effective_until is not None and as_of >= policy.effective_until):
            reasons.append("policy_not_effective")
        else:
            decision_ref = policy.decision_ref
            preservation_basis_ref = policy.preservation.basis_ref if policy.preservation else None
            deletion_basis_ref = policy.deletion.basis_ref if policy.deletion else None
            if policy.preservation_assessment == "unresolved":
                reasons.append("preservation_basis_unresolved")
            if policy.deletion is None:
                reasons.append("deletion_schedule_unknown")
            preserve_until = _rule_deadline(policy.preservation, artifact, as_of, "preservation", reasons)
            delete_after = _rule_deadline(policy.deletion, artifact, as_of, "deletion", reasons)
            if preserve_until is not None and delete_after is not None and preserve_until > delete_after:
                conflict = True
                reasons.append("preservation_exceeds_deletion_threshold")
    if artifact.hold_review != "complete":
        reasons.append("hold_review_unknown")
    if any(hold.started_at > as_of or (hold.released_at is not None and hold.released_at > as_of)
           for hold in artifact.holds):
        reasons.append("hold_evidence_from_future")
    if not artifact.copy_inventory_complete:
        reasons.append("copy_inventory_incomplete")
    if any(copy.state == "unknown" or copy.observed_at > as_of for copy in artifact.copies):
        reasons.append("copy_state_unknown")

    if conflict:
        status = "conflict"
    elif reasons:
        status = "unknown"
    elif any(hold.released_at is None for hold in artifact.holds):
        status = "protected"
        reasons.append("active_preservation_hold")
    elif preserve_until is not None and as_of < preserve_until:
        status = "protected"
        reasons.append("preservation_active")
    elif delete_after is not None and as_of < delete_after:
        status = "protected"
        reasons.append("deletion_threshold_not_reached")
    else:
        status = "eligible"
        reasons.append("deletion_threshold_reached")

    copy_plans = []
    for copy in artifact.copies:
        if copy.observed_at > as_of or copy.state == "unknown":
            next_step = "verify_state"
        elif copy.state == "deletion_confirmed":
            next_step = "retain_deletion_evidence"
        elif status != "eligible":
            next_step = "blocked"
        elif copy.location == "provider":
            next_step = "provider_followup"
        elif copy.location == "backup":
            next_step = "backup_followup"
        else:
            next_step = "plan_local_deletion"
        copy_plans.append(CopyPlan(copy_ref=copy.copy_ref, location=copy.location,
                                   reported_state=copy.state, observed_at=copy.observed_at, evidence_ref=copy.evidence_ref,
                                   next_step=next_step))
    return ArtifactPlan(
        artifact_ref=artifact.artifact_ref, category=artifact.category, purpose_ref=artifact.purpose_ref,
        scope_ref=artifact.scope_ref, policy_refs=artifact.policy_refs, policy_decision_ref=decision_ref,
        preservation_basis_ref=preservation_basis_ref, deletion_basis_ref=deletion_basis_ref,
        status=status, reasons=reasons, preserve_until=preserve_until, delete_after=delete_after,
        local_copies=_copy_summary([copy for copy in artifact.copies if copy.location not in {"provider", "backup"}],
                                   artifact.copy_inventory_complete, as_of),
        provider_copies=_copy_summary([copy for copy in artifact.copies if copy.location == "provider"],
                                      artifact.copy_inventory_complete, as_of),
        backup_copies=_copy_summary([copy for copy in artifact.copies if copy.location == "backup"],
                                    artifact.copy_inventory_complete, as_of),
        copies=copy_plans,
    )


def plan_retention(request: PlanningRequest) -> RetentionPlan:
    """Evaluate caller-supplied policy decisions and observations, with no side effects."""
    policies = {(policy.policy_id, policy.version): policy for policy in request.policies}
    return RetentionPlan(as_of=request.as_of.astimezone(UTC), artifacts=[
        _plan_artifact(artifact, policies, request.as_of) for artifact in request.artifacts
    ])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Metadata-only JSON planning request")
    args = parser.parse_args(argv)
    try:
        request = PlanningRequest.model_validate_json(args.input.read_text(encoding="utf-8"))
        result = plan_retention(request)
    except (ValidationError, ValueError, OSError, UnicodeError):
        # Validation diagnostics must not echo accidentally supplied content or paths.
        print("Invalid or unreadable metadata-only planning request; no actions performed.", file=sys.stderr)
        return 2
    print(result.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
