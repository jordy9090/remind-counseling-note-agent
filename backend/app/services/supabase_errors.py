"""Metadata-only diagnostics for Supabase REST failures."""
from __future__ import annotations

import json
from contextlib import suppress
from urllib.error import HTTPError


# Only documented diagnostic values may cross into logs or API errors. Custom
# PostgREST codes can contain arbitrary text, even when they resemble SQLSTATE.
_SAFE_ERROR_CODES = frozenset({
    "23502", "23503", "23505", "23514", "42501", "42703", "42883", "42P01",
    "42P17", "57014", "P0001",
    "PGRST000", "PGRST001", "PGRST002", "PGRST003",
    "PGRST100", "PGRST101", "PGRST102", "PGRST103", "PGRST105", "PGRST106",
    "PGRST107", "PGRST108", "PGRST111", "PGRST112", "PGRST114", "PGRST115",
    "PGRST116", "PGRST117", "PGRST118", "PGRST120", "PGRST121", "PGRST122",
    "PGRST123", "PGRST124", "PGRST125", "PGRST126", "PGRST127", "PGRST128",
    "PGRST200", "PGRST201", "PGRST202", "PGRST203", "PGRST204", "PGRST205",
    "PGRST300", "PGRST301", "PGRST302", "PGRST303", "PGRSTX00",
})
_MAX_ERROR_BYTES = 65536


def read_error_code(error: HTTPError) -> str | None:
    """Extract a known code without retaining upstream text; always close I/O."""
    try:
        payload = error.read(_MAX_ERROR_BYTES + 1)
        if len(payload) > _MAX_ERROR_BYTES:
            return None
        body = json.loads(payload)
        code = body.get("code") if isinstance(body, dict) else None
        return code if isinstance(code, str) and code in _SAFE_ERROR_CODES else None
    except Exception:
        # Failed reads, invalid encodings and malformed JSON carry no safe code.
        return None
    finally:
        # A cleanup error must not replace the safe HTTP diagnostic with text
        # from the upstream transport.
        with suppress(Exception):
            error.close()
