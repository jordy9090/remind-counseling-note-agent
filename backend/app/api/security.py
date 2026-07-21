"""Temporary API access controls for public preview deployments."""
from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import Header, HTTPException

from app.core.config import settings


PreviewTokenHeader = Annotated[str | None, Header(alias="X-Remind-Preview-Token")]


def require_preview_access(x_remind_preview_token: PreviewTokenHeader = None) -> str:
    """Require a backend-configured preview token until production Auth exists."""
    if settings.local_preview_bypass_enabled:
        return settings.remind_preview_actor

    configured_token = settings.remind_preview_api_token or ""
    if not configured_token:
        raise HTTPException(status_code=401, detail="Preview API token is not configured.")
    if not x_remind_preview_token:
        raise HTTPException(status_code=401, detail="Missing preview API token.")
    if not secrets.compare_digest(configured_token, x_remind_preview_token):
        raise HTTPException(status_code=401, detail="Invalid preview API token.")
    return settings.remind_preview_actor
