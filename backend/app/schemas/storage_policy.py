"""Non-secret storage behavior observable by an authenticated counselor."""
from typing import Literal

from pydantic import BaseModel


class NoteStoragePolicy(BaseModel):
    persistence_enabled: bool
    save_original_input: bool
    save_raw_input: bool
    generated_note_raw_input_mode: Literal["disabled", "original", "masked", "omitted"]
    temporary_drafts_apply_input_policy: Literal[False] = False
    existing_records_deleted: Literal[False] = False
