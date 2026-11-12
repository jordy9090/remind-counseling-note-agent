"""Local synthetic browser check: real iwinv discovery, stub generation, no storage."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.config import settings

directory = Path.home() / ".codex/secrets/iwinv-deid"
settings.deid_service_token = (directory / "worker.env").read_text().strip().split("=", 1)[1]
settings.deid_service_ca_pem = (directory / "server.crt").read_text()
settings.deid_review_signing_key = (directory / "review.key").read_text()
settings.deid_service_url = "https://127.0.0.1:14443"
settings.require_deid_review = True
settings.runtime_environment = "test"
settings.remind_allow_local_bypass = True
settings.enable_real_user_auth = False
settings.use_stub = True
settings.enable_rag = settings.enable_persistence = settings.enable_case_memory = False
import uvicorn
uvicorn.run("app.main:app", host="127.0.0.1", port=8787, access_log=False)
