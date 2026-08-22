"""Idempotently seed the public MusPsy 1416 evaluation corpus.

Dry-run is the default. Applying is allowed only when the repository and
runtime both identify the target as a synthetic/demo development environment.
No row outside CASE-MUSPSY-1416 is queried for mutation or changed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import uuid
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import settings  # noqa: E402
from app.services.embeddings import content_hash, get_embedding_provider  # noqa: E402
from app.services.supabase_storage import storage  # noqa: E402

CASE_ID = "CASE-MUSPSY-1416"
COUNSELOR_ID = settings.remind_preview_actor
MEMORIES = ROOT / "sample_data/muspsy_demo/original_source/memories_1416.txt"
REMOTE_VERIFICATION = ROOT / "docs/supabase_remote_verification.md"
LINKED_PROJECT = ROOT / "supabase/.temp/project-ref"
NAMESPACE = uuid.UUID("8d1cb1be-f9b9-47ce-a046-27e429618c7a")
FIELD_PATTERNS = {
    "emotion_cognitive_state": r"\[Emotion and Cognitive State:\]\s*(.+)",
    "counselor_observations": r"\[Counselor Observations:\]\s*(.+)",
    "counseling_assignments": r"\[Counseling Assignments:\]\s*(.+)",
    "session_goal": r"\[Session Goal:\]\s*(.+)",
    "counseling_summary": r"Counseling Summary:\s*\n(.+)",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Print the scoped seed plan without writing (default).")
    mode.add_argument("--apply", action="store_true", help="Apply only the deterministic MusPsy evaluation rows.")
    parser.add_argument("--confirm-project-ref", default="")
    parser.add_argument("--confirm-evaluation-only", action="store_true")
    args = parser.parse_args()

    corpus = parse_original_sessions(MEMORIES.read_text(encoding="utf-8"))
    project_ref = _project_ref()
    existing = _existing_counts()
    safe, safety_reasons = _evaluation_target_evidence(project_ref)
    planned_chunks = sum(len(item["chunks"]) for item in corpus)
    summary = {
        "mode": "apply" if args.apply else "dry-run",
        "project_ref": project_ref,
        "case_id": CASE_ID,
        "planned_session_count": len(corpus),
        "planned_generated_note_count": len(corpus),
        "planned_case_memory_chunk_count": planned_chunks,
        "existing_same_case_rows": existing,
        "evaluation_target_confirmed": safe,
        "evaluation_target_evidence": safety_reasons,
        "source": "sample_data/muspsy_demo/original_source/memories_1416.txt",
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if not args.apply:
        print("DRY RUN ONLY. No database writes were made.")
        return 0
    if not settings.supabase_configured:
        raise SystemExit("RETRIEVAL_ENV_BLOCKED: Supabase credentials are unavailable.")
    if not safe:
        raise SystemExit("RETRIEVAL_ENV_BLOCKED: target is not clearly documented as a demo/development database.")
    if args.confirm_project_ref != project_ref:
        raise SystemExit("Refusing write: --confirm-project-ref must exactly match the displayed project ref.")
    if not args.confirm_evaluation_only:
        raise SystemExit("Refusing write: --confirm-evaluation-only is required.")

    _validate_existing_ownership(corpus)
    rows = _build_rows(corpus)
    _apply_rows(rows)
    verified = _existing_counts(include_embedding_count=True)
    print(json.dumps({"applied": True, "verified_same_case_rows": verified}, ensure_ascii=False, indent=2))
    return 0


def parse_original_sessions(text: str) -> list[dict[str, object]]:
    sessions: list[dict[str, object]] = []
    session_pattern = re.compile(
        r"The\s+(\d+)(?:st|nd|rd|th)\s+Counseling\s*\n(.*?)(?=\nThe\s+\d+(?:st|nd|rd|th)\s+Counseling|\Z)",
        re.DOTALL,
    )
    for match in session_pattern.finditer(text):
        session_number = int(match.group(1))
        if session_number not in {1, 2, 3, 4}:
            continue
        block = match.group(2)
        chunks = []
        for field_type, pattern in FIELD_PATTERNS.items():
            field_match = re.search(pattern, block)
            if not field_match:
                raise ValueError(f"Missing {field_type} in MusPsy session {session_number}")
            chunk_text = field_match.group(1).strip()
            line_start, line_end = _line_range(text, chunk_text)
            chunks.append(
                {
                    "field_type": field_type,
                    "chunk_text": chunk_text,
                    "source_ref": f"muspsy:memories_1416:session_{session_number}:{field_type}",
                    "line_start": line_start,
                    "line_end": line_end,
                }
            )
        sessions.append({"session_number": session_number, "chunks": chunks})
    if [item["session_number"] for item in sessions] != [1, 2, 3, 4]:
        raise ValueError("MusPsy original sessions 1-4 were not parsed exactly once.")
    return sessions


def _line_range(full_text: str, excerpt: str) -> tuple[int, int]:
    offset = full_text.find(excerpt)
    if offset < 0:
        raise ValueError("Chunk is not an exact substring of the original source.")
    start = full_text.count("\n", 0, offset) + 1
    end = start + excerpt.count("\n")
    return start, end


def _project_ref() -> str:
    host = urlparse(settings.normalized_supabase_url or "").hostname or ""
    if host in {"localhost", "127.0.0.1"}:
        return "local"
    return host.split(".")[0]


def _evaluation_target_evidence(project_ref: str) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    host = urlparse(settings.normalized_supabase_url or "").hostname or ""
    if host in {"localhost", "127.0.0.1"}:
        return True, ["local Supabase host"]
    if settings.runtime_environment.lower() in {"development", "dev", "test", "evaluation"}:
        reasons.append(f"RUNTIME_ENVIRONMENT={settings.runtime_environment}")
    linked_ref = LINKED_PROJECT.read_text(encoding="utf-8").strip() if LINKED_PROJECT.exists() else ""
    if project_ref and linked_ref == project_ref:
        reasons.append("SUPABASE_URL matches the repository linked project")
    verification = REMOTE_VERIFICATION.read_text(encoding="utf-8") if REMOTE_VERIFICATION.exists() else ""
    if "Data scope: synthetic/demo data only." in verification and f"Project ref: `{project_ref}`" in verification:
        reasons.append("repository verification states synthetic/demo data only")
    return len(reasons) == 3, reasons


def _existing_counts(*, include_embedding_count: bool = False) -> dict[str, int]:
    if not settings.supabase_configured:
        return {"cases": 0, "sessions": 0, "generated_notes": 0, "case_memory_chunks": 0}
    result = {
        "cases": len(storage.select("cases", {"id": f"eq.{CASE_ID}", "select": "id,counselor_id", "limit": 10})),
        "sessions": len(storage.select("sessions", {"case_id": f"eq.{CASE_ID}", "select": "id,session_number", "limit": 20})),
        "generated_notes": len(storage.select("generated_notes", {"case_id": f"eq.{CASE_ID}", "select": "id,session_id", "limit": 20})),
        "case_memory_chunks": len(storage.select("case_memory_chunks", {"case_id": f"eq.{CASE_ID}", "select": "id,source_ref", "limit": 100})),
    }
    if include_embedding_count:
        rows = storage.select("case_memory_chunks", {"case_id": f"eq.{CASE_ID}", "select": "id,embedding", "limit": 100})
        result["embedded_case_memory_chunks"] = sum(bool(row.get("embedding")) for row in rows)
    return result


def _validate_existing_ownership(corpus: list[dict[str, object]]) -> None:
    case_rows = storage.select("cases", {"id": f"eq.{CASE_ID}", "select": "id,counselor_id", "limit": 2})
    if case_rows and str(case_rows[0].get("counselor_id") or "") != COUNSELOR_ID:
        raise SystemExit("Refusing write: existing CASE-MUSPSY-1416 belongs to another counselor namespace.")
    expected_session_ids = {
        int(item["session_number"]): str(uuid.uuid5(NAMESPACE, f"{CASE_ID}:session:{item['session_number']}"))
        for item in corpus
    }
    session_rows = storage.select("sessions", {"case_id": f"eq.{CASE_ID}", "select": "id,session_number", "limit": 20})
    for row in session_rows:
        number = int(row.get("session_number") or 0)
        if number in expected_session_ids and str(row.get("id")) != expected_session_ids[number]:
            raise SystemExit(f"Refusing write: session {number} exists with a non-evaluation row id.")


def _build_rows(corpus: list[dict[str, object]]) -> dict[str, list[dict[str, object]]]:
    original_hash = hashlib.sha256(MEMORIES.read_bytes()).hexdigest()
    sessions: list[dict[str, object]] = []
    notes: list[dict[str, object]] = []
    chunks: list[dict[str, object]] = []
    for item in corpus:
        number = int(item["session_number"])
        session_id = str(uuid.uuid5(NAMESPACE, f"{CASE_ID}:session:{number}"))
        note_id = str(uuid.uuid5(NAMESPACE, f"{CASE_ID}:note:{number}"))
        item_chunks = list(item["chunks"])
        by_field = {str(chunk["field_type"]): chunk for chunk in item_chunks}
        summary = str(by_field["counseling_summary"]["chunk_text"])
        sessions.append({"id": session_id, "case_id": CASE_ID, "session_number": number, "session_title": f"MusPsy 1416 source session {number}", "raw_input_text": None, "sanitized_input_text": summary})
        notes.append(
            {
                "id": note_id,
                "case_id": CASE_ID,
                "session_id": session_id,
                "note_type": "session_note",
                "draft_json": {"session_content": {"text": summary}},
                "confirmed_json": {"sections": {"session_content": summary, "session_theme": str(by_field["session_goal"]["chunk_text"]), "presenting_problem": str(by_field["emotion_cognitive_state"]["chunk_text"])}, "source": "MusPsy original memories_1416.txt"},
                "counselor_edited": True,
                "confirmation_status": "demo_confirmed",
                "confirmed_by": COUNSELOR_ID,
            }
        )
        for chunk in item_chunks:
            field_type = str(chunk["field_type"])
            text = str(chunk["chunk_text"])
            chunks.append(
                {
                    "id": str(uuid.uuid5(NAMESPACE, f"{CASE_ID}:memory:{number}:{field_type}")),
                    "counselor_id": COUNSELOR_ID,
                    "case_id": CASE_ID,
                    "session_id": session_id,
                    "source_note_id": note_id,
                    "session_number": number,
                    "field_type": field_type,
                    "chunk_text": text,
                    "source_ref": chunk["source_ref"],
                    "metadata_json": {"source_file": "sample_data/muspsy_demo/original_source/memories_1416.txt", "source_session": number, "source_line_start": chunk["line_start"], "source_line_end": chunk["line_end"], "source_sha256": original_hash, "source_class": "muspsy_original", "public_demo_dataset": True},
                    "embedding_model": settings.embedding_model,
                    "content_hash": content_hash(text, model=settings.embedding_model),
                }
            )
    return {"sessions": sessions, "notes": notes, "chunks": chunks}


def _apply_rows(rows: dict[str, list[dict[str, object]]]) -> None:
    if not storage.select("cases", {"id": f"eq.{CASE_ID}", "select": "id", "limit": 1}):
        storage.insert("cases", [{"id": CASE_ID, "case_alias": CASE_ID, "counselor_id": COUNSELOR_ID, "status": "active"}])
    storage.upsert("sessions", rows["sessions"], on_conflict="id")
    storage.upsert("generated_notes", rows["notes"], on_conflict="id")
    existing_rows = storage.select("case_memory_chunks", {"case_id": f"eq.{CASE_ID}", "select": "id,content_hash,embedding_model,embedding", "limit": 100})
    existing = {str(row.get("id")): row for row in existing_rows}
    pending = []
    for row in rows["chunks"]:
        current = existing.get(str(row["id"]))
        if not current or current.get("content_hash") != row["content_hash"] or current.get("embedding_model") != settings.embedding_model or not current.get("embedding"):
            pending.append(row)
    if pending:
        embeddings = get_embedding_provider().embed([str(row["chunk_text"]) for row in pending])
        for row, embedding in zip(pending, embeddings, strict=True):
            row["embedding"] = embedding
        storage.upsert("case_memory_chunks", pending, on_conflict="id")


if __name__ == "__main__":
    raise SystemExit(main())
