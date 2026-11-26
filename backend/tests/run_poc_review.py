"""Run only the local PoC contracts, before any application settings are imported."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


BACKEND = Path(__file__).resolve().parents[1]
SUITES = (
    "test_poc_processing_authorization",
    "test_poc_approval",
    "test_poc_diagnostics",
    "test_poc_storage",
    "test_poc_reviewed_history",
    "test_poc_auth_boundary",
    "test_poc_tracing",
    "test_poc_deletion_lifecycle",
    "test_poc_upload_cleanup_signal",
)


def deny_external_io(event, args):
    if event in {"socket.connect", "socket.bind", "socket.sendto", "socket.getaddrinfo",
                 "socket.gethostbyname", "socket.gethostbyaddr", "subprocess.Popen", "os.system"}:
        # Windows asyncio may implement its internal wakeup socketpair over loopback.
        if event in {"socket.bind", "socket.connect"} and args[1][0] in {"127.0.0.1", "::1"}:
            frame = sys._getframe(1)
            while frame:
                if (frame.f_globals.get("__name__") == "socket"
                        and frame.f_code.co_name in {"socketpair", "_fallback_socketpair"}):
                    return
                frame = frame.f_back
        raise RuntimeError(f"Offline PoC suite blocked {event}")
    if event == "open" and isinstance(args[0], (str, bytes)):
        name = Path(os.fsdecode(args[0])).name.lower()
        if (name == ".env" or name.startswith(".env.") or name.endswith((".env", ".key", ".pfx", ".p12"))
                or name in {"id_rsa", "id_ed25519", "credentials", "credentials.json"}):
            raise RuntimeError("Offline PoC suite blocked a configuration or credential file")


def main() -> int:
    suites = sys.argv[1:]
    legacy = bool(suites and suites[0] == "--legacy")
    if legacy:
        suites = suites[1:]
    sys.dont_write_bytecode = True
    sys.addaudithook(deny_external_io)
    # Keep just OS runtime paths; no inherited service credentials or proxy/tracing settings.
    essential = {key: os.environ[key] for key in ("SystemRoot", "WINDIR", "PATH") if key in os.environ}
    with tempfile.TemporaryDirectory(prefix="remind-poc-offline-") as scratch:
        os.environ.clear()
        os.environ.update(essential, REMIND_POC_OFFLINE="1", RUNTIME_ENVIRONMENT="test",
                          USE_STUB="1", HF_HUB_OFFLINE="1", LANGSMITH_TRACING="false",
                          LANGCHAIN_TRACING_V2="false", USERPROFILE=scratch, HOME=scratch,
                          TMP=scratch, TEMP=scratch, TMPDIR=scratch, UPLOAD_TMP_DIR=scratch,
                          RECOMPOSE_CACHE_DIR=str(Path(scratch, "cache")),
                          TEMP_DRAFT_DIR=str(Path(scratch, "drafts")))
        if legacy:
            # Existing subsystem tests deliberately bypass review; PoC suites patch it back on.
            os.environ.update(POC_MODE="0", REQUIRE_DEID_REVIEW="0", SAVE_ORIGINAL_INPUT="1",
                              OPENAI_API_KEY="synthetic-offline-key")
        tempfile.tempdir = scratch
        sys.path[:0] = [str(BACKEND), str(BACKEND.parent)]
        from pydantic_settings import DotEnvSettingsSource

        # Settings names backend/.env explicitly; changing working directory alone is insufficient.
        with patch.object(DotEnvSettingsSource, "_read_env_files", return_value={}):
            suite = unittest.defaultTestLoader.loadTestsFromNames(suites or SUITES)
            result = unittest.TextTestRunner(verbosity=2).run(suite)
        tempfile.tempdir = None
    return int(not result.wasSuccessful() or bool(result.skipped))


if __name__ == "__main__":
    raise SystemExit(main())
