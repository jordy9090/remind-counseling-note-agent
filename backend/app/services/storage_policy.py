"""Report effective input-storage settings without credentials or record access."""
from app.core.config import settings
from app.schemas.storage_policy import NoteStoragePolicy


def note_storage_policy(actor: str | None = None) -> NoteStoragePolicy:
    account_opt_in = getattr(actor, "store_original_input", True) is not False
    save_original = settings.save_original_input and not settings.poc_mode
    save_raw = settings.save_raw_input and not settings.poc_mode
    if not settings.enable_persistence:
        mode = "disabled"
    elif not account_opt_in:
        mode = "omitted"
    elif save_original:
        mode = "original"
    elif save_raw:
        mode = "masked"
    else:
        mode = "omitted"
    return NoteStoragePolicy(
        persistence_enabled=settings.enable_persistence,
        save_original_input=save_original,
        save_raw_input=save_raw,
        account_store_original_input=account_opt_in,
        generated_note_raw_input_mode=mode,
    )
