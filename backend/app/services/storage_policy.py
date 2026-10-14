"""Report effective input-storage settings without credentials or record access."""
from app.core.config import settings
from app.schemas.storage_policy import NoteStoragePolicy


def note_storage_policy() -> NoteStoragePolicy:
    if not settings.enable_persistence:
        mode = "disabled"
    elif settings.save_original_input:
        mode = "original"
    elif settings.save_raw_input:
        mode = "masked"
    else:
        mode = "omitted"
    return NoteStoragePolicy(
        persistence_enabled=settings.enable_persistence,
        save_original_input=settings.save_original_input,
        save_raw_input=settings.save_raw_input,
        generated_note_raw_input_mode=mode,
    )
