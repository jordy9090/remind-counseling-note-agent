"""Opt-in grounded generation using existing raw-region retrieval and LLM service."""
from __future__ import annotations

import json
import math
import re
from collections.abc import Callable
from typing import Any

from app.core.config import settings
from app.schemas.evidence import CandidateTranscriptRegion
from app.schemas.grounding import (
    CitationDiagnostic,
    ClaimSupportValidation,
    EvidenceNeed,
    GroundedClaim,
    GroundedGenerationDraft,
    GroundedGenerationResult,
    GroundingContext,
    GroundingContextDiagnostics,
    GroundingMetrics,
    GroundingSource,
)
from app.schemas.note import SanitizedInput, TargetDocumentType
from app.services.claim_support_validation import validate_claim_support
from app.services.llm import get_structured_llm
from app.services.raw_evidence_retrieval import (
    DEFAULT_WINDOW_CANDIDATE_K,
    build_candidate_regions,
    retrieve_transcript_window_candidates,
)
from app.services.supabase_storage import SupabaseStorage


DEFAULT_RAW_REGION_TOP_K = 5
MAX_EVIDENCE_NEEDS = 5
RegionRetriever = Callable[..., list[CandidateTranscriptRegion]]
SupportValidator = Callable[..., ClaimSupportValidation]


def formulate_evidence_needs(
    sanitized: SanitizedInput,
    target_document_type: TargetDocumentType,
    *,
    max_needs: int = MAX_EVIDENCE_NEEDS,
) -> list[EvidenceNeed]:
    """Build small retrieval intents without diagnosis, scoring, or prior-summary concatenation."""
    if max_needs <= 0:
        return []
    focus_parts = [sanitized.sources.counseling_goal.strip(), *sanitized.sources.key_issue_tags[:3]]
    focus = ", ".join(part for part in focus_parts if part) or "현재 회기의 핵심 상담 이슈"
    document_label = {
        "session_note": "회기 기록",
        "supervision_report": "수퍼비전 문서",
        "termination_report": "종결 기록",
    }[target_document_type]
    specs = [
        (
            "session_content",
            f"{focus}와 관련해 과거 회기에서 내담자가 보고한 사건, 행동, 회피 또는 자기표현 장면",
            "raw_factual",
        ),
        (
            "counselor_intervention",
            f"{focus}와 관련해 이전 상담에서 실제로 이루어진 상담자 개입과 상호작용",
            "raw_factual",
        ),
        (
            "client_response",
            f"{focus}와 관련한 개입 직후 내담자가 실제로 표현한 반응과 행동 변화",
            "raw_factual",
        ),
        (
            "presenting_problem",
            f"{document_label}에 필요한 과거의 반복 어려움, 후퇴, 예외 또는 변화에 관한 직접 발화",
            "raw_factual",
        ),
        (
            "reflection",
            f"{focus}에 관해 상담사가 이전에 확정한 사례 이해, 상담 목표 또는 전략",
            "counselor_judgment",
        ),
    ]
    return [
        EvidenceNeed(
            need_id=f"N{index}",
            target_field=target_field,
            query_text=query_text,
            source_requirement=source_requirement,
        )
        for index, (target_field, query_text, source_requirement) in enumerate(specs[:max_needs], start=1)
    ]


def retrieve_raw_regions_for_needs(
    *,
    needs: list[EvidenceNeed],
    user_id: str,
    case_id: str,
    current_session_number: int | None = None,
    top_k: int = DEFAULT_RAW_REGION_TOP_K,
    region_retriever: RegionRetriever | None = None,
    storage_client: SupabaseStorage | None = None,
) -> dict[str, list[CandidateTranscriptRegion]]:
    """Reuse PR3 window retrieval and region construction for raw-factual needs."""
    if top_k <= 0 or not user_id.strip() or not case_id.strip():
        return {need.need_id: [] for need in needs if need.source_requirement == "raw_factual"}
    retrieve = region_retriever or _retrieve_regions
    results: dict[str, list[CandidateTranscriptRegion]] = {}
    for need in needs:
        if need.source_requirement != "raw_factual":
            continue
        if region_retriever is None:
            regions = retrieve(
                query_text=need.query_text,
                user_id=user_id,
                case_id=case_id,
                storage_client=storage_client,
            )
        else:
            regions = retrieve(query_text=need.query_text, user_id=user_id, case_id=case_id)
        if current_session_number is not None:
            regions = [
                region
                for region in regions
                if region.session_number is None or region.session_number < current_session_number
            ]
        results[need.need_id] = regions[:top_k]
    return results


def _retrieve_regions(
    *,
    query_text: str,
    user_id: str,
    case_id: str,
    storage_client: SupabaseStorage | None = None,
) -> list[CandidateTranscriptRegion]:
    windows = retrieve_transcript_window_candidates(
        query_text=query_text,
        user_id=user_id,
        case_id=case_id,
        candidate_k=DEFAULT_WINDOW_CANDIDATE_K,
        storage_client=storage_client,
    )
    return build_candidate_regions(
        windows=windows,
        user_id=user_id,
        case_id=case_id,
        storage_client=storage_client,
    )


def assemble_grounding_context(
    *,
    needs: list[EvidenceNeed],
    raw_regions_by_need: dict[str, list[CandidateTranscriptRegion]],
    counselor_memory_chunks: list[Any] | None = None,
    authoritative_kb_chunks: list[Any] | None = None,
) -> GroundingContext:
    """Assign stable request-local IDs and deduplicate canonical source_refs."""
    sources: list[GroundingSource] = []
    by_ref: dict[str, GroundingSource] = {}
    mapping = {need.need_id: [] for need in needs}
    retrieved_region_count = 0

    for need in needs:
        if need.source_requirement != "raw_factual":
            continue
        for region in raw_regions_by_need.get(need.need_id, []):
            retrieved_region_count += 1
            source = by_ref.get(region.source_ref)
            if source is None:
                source = GroundingSource(
                    evidence_id=f"R{1 + sum(item.source_type == 'raw_transcript' for item in sources)}",
                    source_type="raw_transcript",
                    source_ref=region.source_ref,
                    source_text=region.region_text,
                    session_id=region.session_id,
                    session_number=region.session_number,
                    start_turn_index=region.start_turn_index,
                    end_turn_index=region.end_turn_index,
                    similarity_score=region.retrieval_score,
                    retrieval_method="transcript_window_dense_region",
                    need_ids=[need.need_id],
                )
                by_ref[region.source_ref] = source
                sources.append(source)
            elif need.need_id not in source.need_ids:
                source.need_ids.append(need.need_id)
            mapping[need.need_id].append(source.evidence_id)

    judgment_needs = [need for need in needs if need.source_requirement == "counselor_judgment"]
    for chunk in counselor_memory_chunks or []:
        source_ref = str(getattr(chunk, "source_ref", "") or "")
        source_text = str(getattr(chunk, "chunk_text", "") or "")
        if not source_ref or not source_text:
            continue
        source = by_ref.get(source_ref)
        if source is None:
            source = GroundingSource(
                evidence_id=f"M{1 + sum(item.source_type == 'counselor_confirmed' for item in sources)}",
                source_type="counselor_confirmed",
                source_ref=source_ref,
                source_text=source_text,
                session_id=getattr(chunk, "session_id", None),
                session_number=getattr(chunk, "session_number", None),
                similarity_score=getattr(chunk, "similarity_score", None),
                retrieval_method=str(getattr(chunk, "retrieval_method", "case_memory_dense") or "case_memory_dense"),
                need_ids=[need.need_id for need in judgment_needs],
            )
            by_ref[source_ref] = source
            sources.append(source)
        for need in judgment_needs:
            mapping[need.need_id].append(source.evidence_id)

    for chunk in authoritative_kb_chunks or []:
        source_ref = str(getattr(chunk, "source_ref", "") or "")
        source_text = str(getattr(chunk, "chunk_text", "") or "")
        if not source_ref or not source_text or source_ref in by_ref:
            continue
        source = GroundingSource(
            evidence_id=f"K{1 + sum(item.source_type == 'authoritative_kb' for item in sources)}",
            source_type="authoritative_kb",
            source_ref=source_ref,
            source_text=source_text,
            retrieval_method=str(getattr(chunk, "retrieval_method", "") or ""),
        )
        by_ref[source_ref] = source
        sources.append(source)

    mapping = {need_id: _unique(values) for need_id, values in mapping.items()}
    raw_sources = [source for source in sources if source.source_type == "raw_transcript"]
    raw_turn_count = sum(
        (source.end_turn_index - source.start_turn_index + 1)
        for source in raw_sources
        if source.start_turn_index is not None and source.end_turn_index is not None
    )
    approximate_tokens = math.ceil(sum(len(source.source_text) for source in sources) / 4)
    return GroundingContext(
        needs=needs,
        sources=sources,
        need_to_evidence_ids=mapping,
        diagnostics=GroundingContextDiagnostics(
            evidence_need_count=len(needs),
            retrieved_region_count=retrieved_region_count,
            deduplicated_region_count=len(raw_sources),
            counselor_memory_count=sum(source.source_type == "counselor_confirmed" for source in sources),
            authoritative_kb_count=sum(source.source_type == "authoritative_kb" for source in sources),
            raw_evidence_turn_count=raw_turn_count,
            approximate_token_count=approximate_tokens,
        ),
    )


def build_grounded_generation_prompt(sanitized: SanitizedInput, context: GroundingContext) -> str:
    """Render source types separately and require citations from supplied short IDs only."""
    _ = sanitized  # Deliberately excluded: generation facts must come from R/M/K sources only.
    need_metadata = [
        {
            "need_id": need.need_id,
            "target_field": need.target_field,
            "source_requirement": need.source_requirement,
            "allowed_evidence_ids": context.need_to_evidence_ids.get(need.need_id, []),
        }
        for need in context.needs
    ]
    sections = []
    citation_contract = "\n".join(
        f"- {item['need_id']} ({item['source_requirement']}): "
        f"{', '.join(item['allowed_evidence_ids']) or '(none; return unsupported)'}"
        for item in need_metadata
    )
    for title, source_type in (
        ("RAW TRANSCRIPT EVIDENCE", "raw_transcript"),
        ("COUNSELOR-CONFIRMED MEMORY", "counselor_confirmed"),
        ("AUTHORITATIVE DOCUMENTATION KB", "authoritative_kb"),
    ):
        rendered = []
        for source in context.sources:
            if source.source_type != source_type:
                continue
            session_label = f"\nSession {source.session_number}" if source.session_number is not None else ""
            allowed_needs = ", ".join(source.need_ids) or "(none)"
            rendered.append(
                f"[{source.evidence_id}]{session_label}\nAllowed EvidenceNeeds: {allowed_needs}\n{source.source_text}"
            )
        sections.append(f"=== {title} ===\n" + ("\n\n".join(rendered) if rendered else "(none)"))
    return f"""
You are extending an existing Re:mind counseling document draft with claim-level grounding.
Return only the GroundedGenerationDraft schema. Use only evidence IDs supplied below.

Rules:
- Write claim text in natural Korean. Produce one concise claim for every EvidenceNeed, in need order.
- Before writing each claim, check allowed_evidence_ids. Cite only IDs in that exact list.
- A source shown below is forbidden for a need unless that need appears in its Allowed EvidenceNeeds header.
- For raw_factual needs, only an allowed R# is valid. Never substitute an M# or K# even when its wording is closer.
- For counselor_judgment needs, only an allowed M# is valid. Never substitute an R# or K#.
- EvidenceNeed retrieval queries and current-session inputs are deliberately absent. Metadata below is NOT EVIDENCE.
- Temporal or comparative qualifiers such as "first", "recent", "before", "after", "improved", or "setback"
  require explicit support in the cited source. Otherwise omit the qualifier or return unsupported.
- A statement that the client said something, did something, experienced an event, responded in a prior session,
  or received a prior intervention requires a raw R# citation and support_type=direct_evidence.
- Counselor reflection, goal, strategy, and confirmed case understanding may cite M# with
  support_type=counselor_judgment. Never present it as raw speech.
- Interpretations must use support_type=clinical_inference and review_required=true.
- If support is insufficient, use support_type=unsupported, evidence_ids=[], review_required=true.
- Never invent an evidence ID. K# sources are documentation rules, not factual counseling evidence.
- Do not diagnose, score treatment success, or produce a prognosis.

Evidence-need metadata (NOT EVIDENCE):
{json.dumps(need_metadata, ensure_ascii=False, indent=2)}

Per-need citation contract (NOT EVIDENCE):
{citation_contract}

{chr(10).join(sections)}
""".strip()


def generate_grounded_claims(sanitized: SanitizedInput, context: GroundingContext) -> GroundedGenerationDraft:
    """Reuse the existing structured LLM service; use a source-copying stub offline."""
    if settings.stub_mode:
        return _stub_grounded_claims(context)
    prompt = build_grounded_generation_prompt(sanitized, context)
    return get_structured_llm(GroundedGenerationDraft).invoke(prompt)


def validate_evidence_ids(
    draft: GroundedGenerationDraft,
    context: GroundingContext,
    *,
    support_validator: SupportValidator | None = None,
) -> GroundedGenerationResult:
    """Fail closed for invalid IDs, source hierarchy, and semantic non-support."""
    source_by_id = {source.evidence_id: source for source in context.sources}
    need_ids = {need.need_id for need in context.needs}
    claims: list[GroundedClaim] = []
    diagnostics: list[CitationDiagnostic] = []
    total_citations = 0
    valid_citations = 0
    support_validations: dict[str, ClaimSupportValidation] = {}
    validate_support = support_validator or validate_claim_support

    for original in draft.claims:
        claim = original.model_copy(deep=True)
        total_citations += len(claim.evidence_ids)
        invalid_ids = [evidence_id for evidence_id in claim.evidence_ids if evidence_id not in source_by_id]
        valid_citations += len(claim.evidence_ids) - len(invalid_ids)
        allowed = True
        reason = ""
        cited_sources = [source_by_id[evidence_id] for evidence_id in claim.evidence_ids if evidence_id in source_by_id]
        permitted_for_need = set(context.need_to_evidence_ids.get(claim.need_id, [])) if claim.need_id else set()
        if invalid_ids:
            allowed = False
            reason = "Model returned evidence IDs that were not supplied."
        elif claim.need_id and claim.need_id not in need_ids:
            allowed = False
            reason = "Model returned a need_id that was not supplied."
        elif claim.need_id and any(evidence_id not in permitted_for_need for evidence_id in claim.evidence_ids):
            allowed = False
            reason = "Claim cited evidence that was not retrieved for its EvidenceNeed."
        elif claim.support_type == "direct_evidence" and (
            not cited_sources or any(source.source_type != "raw_transcript" for source in cited_sources)
        ):
            allowed = False
            reason = "Direct factual evidence must cite at least one raw transcript region."
        elif claim.support_type == "counselor_judgment" and (
            not cited_sources or any(source.source_type != "counselor_confirmed" for source in cited_sources)
        ):
            allowed = False
            reason = "Counselor judgment must cite counselor-confirmed memory."
        elif claim.support_type == "clinical_inference" and (
            not cited_sources
            or any(source.source_type not in {"raw_transcript", "counselor_confirmed"} for source in cited_sources)
        ):
            allowed = False
            reason = "Clinical inference must retain at least one raw or counselor-confirmed source."
        elif claim.support_type == "unsupported" and claim.evidence_ids:
            allowed = False
            reason = "Unsupported claims cannot retain citations."

        if not allowed:
            diagnostics.append(
                CitationDiagnostic(
                    claim_id=claim.claim_id,
                    invalid_evidence_ids=invalid_ids or list(claim.evidence_ids),
                    reason=reason,
                )
            )
            claim.support_type = "unsupported"
            claim.evidence_ids = []
            claim.review_required = True
        elif claim.support_type in {"direct_evidence", "counselor_judgment"}:
            semantic = validate_support(claim=claim, evidence_by_id=source_by_id)
            support_validations[claim.claim_id] = semantic
            if semantic.verdict != "supported":
                diagnostics.append(
                    CitationDiagnostic(
                        claim_id=claim.claim_id,
                        invalid_evidence_ids=list(claim.evidence_ids),
                        reason=f"Cited source semantic support is {semantic.verdict}"
                        + (f" ({semantic.category})" if semantic.category else ""),
                    )
                )
                claim.support_type = "unsupported"
                claim.evidence_ids = []
                claim.review_required = True
        elif claim.support_type in {"clinical_inference", "unsupported"}:
            claim.review_required = True
            if claim.support_type == "unsupported":
                claim.evidence_ids = []
        if claim.claim_kind == "clinical_inference":
            claim.review_required = True
        claims.append(claim)

    metrics = compute_grounding_metrics(
        claims,
        context,
        total_citations=total_citations,
        valid_citations=valid_citations,
        support_validations=support_validations,
    )
    return GroundedGenerationResult(
        context=context,
        claims=claims,
        citation_diagnostics=diagnostics,
        claim_support_validations=support_validations,
        metrics=metrics,
    )


def compute_grounding_metrics(
    claims: list[GroundedClaim],
    context: GroundingContext,
    *,
    total_citations: int | None = None,
    valid_citations: int | None = None,
    support_validations: dict[str, ClaimSupportValidation] | None = None,
) -> GroundingMetrics:
    source_by_id = {source.evidence_id: source for source in context.sources}
    if total_citations is None:
        total_citations = sum(len(claim.evidence_ids) for claim in claims)
    if valid_citations is None:
        valid_citations = sum(
            evidence_id in source_by_id for claim in claims for evidence_id in claim.evidence_ids
        )
    factual = [claim for claim in claims if claim.claim_kind == "factual"]
    cited_factual = [
        claim
        for claim in factual
        if claim.support_type in {"direct_evidence", "counselor_judgment"} and claim.evidence_ids
    ]
    unsupported = [claim for claim in factual if claim.support_type == "unsupported"]
    raw_ids = {
        evidence_id
        for claim in claims
        for evidence_id in claim.evidence_ids
        if evidence_id in source_by_id and source_by_id[evidence_id].source_type == "raw_transcript"
    }
    distribution = {name: 0 for name in ("direct_evidence", "counselor_judgment", "clinical_inference", "unsupported")}
    for claim in claims:
        distribution[claim.support_type] = distribution.get(claim.support_type, 0) + 1
    direct_verdicts = [
        validation
        for claim in claims
        if claim.claim_kind == "factual"
        and claim.claim_id in (support_validations or {})
        for validation in [(support_validations or {})[claim.claim_id]]
    ]
    return GroundingMetrics(
        citation_validity=(valid_citations / total_citations) if total_citations else 1.0,
        factual_claim_citation_coverage=(len(cited_factual) / len(factual)) if factual else 1.0,
        unsupported_factual_claim_rate=(len(unsupported) / len(factual)) if factual else 0.0,
        semantic_support_validity=(
            sum(item.verdict == "supported" for item in direct_verdicts) / len(direct_verdicts)
            if direct_verdicts
            else 1.0
        ),
        raw_evidence_usage=len(raw_ids),
        source_type_distribution=distribution,
    )


def _stub_grounded_claims(context: GroundingContext) -> GroundedGenerationDraft:
    source_by_id = {source.evidence_id: source for source in context.sources}
    claims = []
    for index, need in enumerate(context.needs, start=1):
        evidence_ids = context.need_to_evidence_ids.get(need.need_id, [])
        compatible = [
            evidence_id
            for evidence_id in evidence_ids
            if evidence_id in source_by_id
            and (
                (need.source_requirement == "raw_factual" and source_by_id[evidence_id].source_type == "raw_transcript")
                or (
                    need.source_requirement == "counselor_judgment"
                    and source_by_id[evidence_id].source_type == "counselor_confirmed"
                )
            )
        ]
        if not compatible:
            claims.append(
                GroundedClaim(
                    claim_id=f"C{index}",
                    need_id=need.need_id,
                    target_field=need.target_field,
                    text=f"{need.target_field}에 필요한 과거 근거는 현재 제공된 source에서 확인되지 않았다.",
                    support_type="unsupported",
                    evidence_ids=[],
                    review_required=True,
                )
            )
            continue
        evidence_id = compatible[0]
        source = source_by_id[evidence_id]
        text = _first_supported_statement(source.source_text, prefer_client=need.source_requirement == "raw_factual")
        claims.append(
            GroundedClaim(
                claim_id=f"C{index}",
                need_id=need.need_id,
                target_field=need.target_field,
                text=text,
                support_type="direct_evidence" if need.source_requirement == "raw_factual" else "counselor_judgment",
                evidence_ids=[evidence_id],
                review_required=False,
            )
        )
    return GroundedGenerationDraft(claims=claims)


def _first_supported_statement(text: str, *, prefer_client: bool) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if prefer_client:
        client_lines = [line for line in lines if line.startswith("[client]")]
        if client_lines:
            return re.sub(r"^\[client\]\s*", "", client_lines[0])
    first = lines[0] if lines else "제공된 source 내용을 상담사가 확인해야 한다."
    return re.sub(r"^\[[^]]+\]\s*", "", first)


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))
