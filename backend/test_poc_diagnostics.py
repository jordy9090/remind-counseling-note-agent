"""Synthetic error privacy contracts for the isolated PoC regression runner."""
from __future__ import annotations

import io
import logging
import os
import traceback
import unittest
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

if os.environ.get("REMIND_POC_OFFLINE") != "1":
    raise unittest.SkipTest("Use backend/tests/run_poc_review.py")

from fastapi import HTTPException, Response
from pydantic import BaseModel, ValidationError

PRIVATE = "SYNTHETIC-PRIVATE-POC-CONTENT"


@contextmanager
def diagnostics():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    root = logging.getLogger()
    root.addHandler(handler)
    try:
        with redirect_stderr(stream), redirect_stdout(stream):
            yield stream
    finally:
        root.removeHandler(handler)
        handler.close()


def validation_failure():
    class Result(BaseModel):
        count: int
    try:
        Result.model_validate({"count": PRIVATE})
    except ValidationError as error:
        return error
    raise AssertionError("Synthetic invalid value must be rejected")


class ErrorPrivacyTests(unittest.IsolatedAsyncioTestCase):
    def assert_private(self, error, output, status):
        if not isinstance(error, HTTPException):
            raise self.failureException("Dependency failure escaped the API boundary") from None
        self.assertEqual(status, error.status_code)
        rendered = output.getvalue() + str(error.detail) + "".join(traceback.format_exception(error))
        if PRIVATE in rendered:
            raise self.failureException("Sensitive exception content crossed the response or diagnostic boundary") from None
        self.assertTrue(error.__suppress_context__, "The private exception chain remains visible")
        self.assertIsNone(error.__cause__)

    async def test_case_operations_suppress_unexpected_and_storage_error_content(self):
        from app.api.routes import cases
        from app.api.security import AuthenticatedActor
        from app.services.supabase_storage import SupabaseStorageError

        actor = AuthenticatedActor("synthetic-owner", "synthetic-token")
        operations = [
            (cases.get_case_list, "list_cases", {}),
            (cases.post_case, "create_case", {"request": object()}),
            (cases.patch_case_profile, "update_case_profile", {"case_id": "poc-case", "request": object()}),
            (cases.get_case_dashboard, "fetch_case_dashboard", {"case_id": "poc-case"}),
            (cases.patch_case_schedule, "update_case_schedule", {"case_id": "poc-case", "request": object()}),
            (cases.post_quick_summary_session, "save_quick_summary_session", {"case_id": "poc-case", "request": object()}),
            (cases.get_case_person_dictionary, "fetch_case_person_dictionary", {"case_id": "poc-case"}),
            (cases.put_case_person_dictionary, "update_case_person_dictionary", {"case_id": "poc-case", "request": object()}),
        ]
        for handler, dependency, kwargs in operations:
            for failure, status in [(ValueError(PRIVATE), 500), (validation_failure(), 500), (SupabaseStorageError(PRIVATE), 502)]:
                with self.subTest(operation=dependency, failure=type(failure).__name__), \
                     patch.object(cases, dependency, side_effect=failure), diagnostics() as output:
                    try:
                        await handler(actor=actor, **kwargs)
                    except Exception as error:
                        self.assert_private(error, output, status)
                    else:
                        self.fail("Dependency failure must produce an API error")

    async def test_case_success_and_known_not_found_status_remain(self):
        from app.api.routes import cases
        from app.api.security import AuthenticatedActor
        from app.services.supabase_storage import SupabaseStorageError

        actor = AuthenticatedActor("synthetic-owner", "synthetic-token")
        expected = object()
        with patch.object(cases, "fetch_case_dashboard", return_value=expected):
            self.assertIs(expected, await cases.get_case_dashboard("poc-case", actor))
        with patch.object(cases, "fetch_case_dashboard", side_effect=SupabaseStorageError("케이스를 찾을 수 없습니다.")):
            with self.assertRaises(HTTPException) as caught:
                await cases.get_case_dashboard("poc-case", actor)
        self.assertEqual(404, caught.exception.status_code)

    async def test_generation_and_record_errors_hide_private_exception_chain(self):
        from app.api.routes import notes
        from app.schemas.note import SessionInput

        session = SessionInput(case_id="poc-case", session_number=1, counselor_memo="synthetic memo", transcript_text="")
        with patch.object(notes, "deidentify_session_input", return_value=(session, [])), \
             patch.object(notes, "run_note_pipeline", side_effect=validation_failure()), diagnostics() as output:
            with self.assertRaises(HTTPException) as caught:
                notes._generate_reviewed(session, actor="synthetic-owner")
            self.assert_private(caught.exception, output, 502)
        for handler, dependency in [(notes.get_note_record, "fetch_generated_note"), (notes.delete_note_session_input, "delete_session_input")]:
            with self.subTest(operation=dependency), patch.object(notes, dependency, side_effect=ValueError(PRIVATE)), diagnostics() as output:
                with self.assertRaises(HTTPException) as caught:
                    await handler("poc-note", "synthetic-owner", Response())
                self.assert_private(caught.exception, output, 503)

    async def test_document_export_errors_hide_details_and_persist_only_error_codes(self):
        from app.api.routes import documents
        from app.services.document_export import DocumentExportRuntimeError
        from api.documents import export as wrapper

        request = SimpleNamespace(case_id="poc-case", session_number=1, document_type="session_note", format="pdf", title="Synthetic title")
        for host in (documents, wrapper):
            for failure in (DocumentExportRuntimeError(PRIVATE), validation_failure()):
                with self.subTest(host=host.__name__, failure=type(failure).__name__), \
                     patch.object(host, "run_in_threadpool", AsyncMock(side_effect=failure)), \
                     patch.object(documents, "record_document_export") as saved, diagnostics() as output:
                    try:
                        await host.export_document(request, "synthetic-owner")
                    except Exception as error:
                        self.assert_private(error, output, 500)
                    else:
                        self.fail("Renderer failure must produce an API error")
                    self.assertFalse(PRIVATE in str(saved.call_args_list), "Export history retained private error content")

    async def test_document_extraction_and_audio_suppress_private_parser_causes(self):
        from app.api.routes import audio, materials
        from app.services.audio_transcription import AudioTranscriptionRuntimeError
        from app.services.document_extraction import DocumentExtractionError
        from api.materials.documents import extract as wrapper

        upload = SimpleNamespace(temp_path="synthetic-unused-temp-path")
        for host, failure, status in [(materials, DocumentExtractionError(PRIVATE), 422), (wrapper, DocumentExtractionError(PRIVATE), 422),
                                      (materials, validation_failure(), 500), (wrapper, validation_failure(), 500)]:
            with self.subTest(host=host.__name__, failure=type(failure).__name__), \
                 patch.object(host, "persist_upload_to_temp", AsyncMock(return_value=upload)), \
                 patch.object(host, "run_in_threadpool", AsyncMock(side_effect=failure)), \
                 patch.object(host, "cleanup_temp_file") as cleanup, diagnostics() as output:
                try:
                    await host.extract_document_material(Response(), "synthetic-owner", object())
                except Exception as error:
                    self.assert_private(error, output, status)
                else:
                    self.fail("Parser failure must produce an API error")
                cleanup.assert_called_once_with(upload.temp_path)
        with patch.object(audio, "current_audio_engine", return_value="faster-whisper"), \
             patch.object(audio, "persist_upload_to_temp", AsyncMock(return_value=upload)), \
             patch.object(audio, "get_transcription_service", return_value=Mock()), \
             patch.object(audio, "run_in_threadpool", AsyncMock(side_effect=AudioTranscriptionRuntimeError(PRIVATE))), \
             patch.object(audio, "cleanup_temp_file") as cleanup, diagnostics() as output:
            with self.assertRaises(HTTPException) as caught:
                await audio.transcribe_audio(Response(), "synthetic-owner", object(), "ko", "transcribe", 2)
            self.assert_private(caught.exception, output, 500)
            cleanup.assert_called_once_with(upload.temp_path)

    async def test_invalid_request_bodies_do_not_echo_input_in_main_or_wrappers(self):
        from fastapi.testclient import TestClient
        from app.api.security import require_preview_access
        from app.main import app
        from api.cases import dashboard
        from api.notes import generate
        from api.documents import export
        from api.materials.documents import extract

        hosts = [
            (app, "/api/notes/generate", {"session_number": PRIVATE}),
            (generate.app, "/api/notes/generate", {"session_number": PRIVATE}),
            (dashboard.app, "/api/cases", {"case_alias": {"sensitive": PRIVATE}}),
            (export.app, "/api/documents/export", {"session_number": PRIVATE}),
            (extract.app, "/api/audio/deidentify", {"text": {"sensitive": PRIVATE}}),
        ]
        for host, path, payload in hosts:
            previous = host.dependency_overrides.copy()
            host.dependency_overrides[require_preview_access] = lambda: "synthetic-owner"
            try:
                with self.subTest(host=host.title), diagnostics() as output:
                    response = TestClient(host).post(path, json=payload)
                    self.assertEqual(422, response.status_code)
                    self.assertFalse(PRIVATE in response.text + output.getvalue(), "Validation echoed private request content")
            finally:
                host.dependency_overrides = previous

    async def test_invalid_stored_response_hides_rejected_content(self):
        from fastapi.testclient import TestClient
        from app.api.routes import notes
        from app.api.security import require_preview_access
        from app.main import app
        from api.notes import record

        for host, path in [(app, "/api/notes/records/poc-note"), (record.app, "/api/notes/record?note_id=poc-note")]:
            previous = host.dependency_overrides.copy()
            host.dependency_overrides[require_preview_access] = lambda: "synthetic-owner"
            try:
                with self.subTest(host=host.title), patch.object(notes, "fetch_generated_note", return_value={"private": PRIVATE}), diagnostics() as output:
                    try:
                        response = TestClient(host).get(path)
                    except Exception:
                        raise self.failureException("Response validation escaped the private diagnostic boundary") from None
                    self.assertEqual(500, response.status_code)
                    self.assertFalse(PRIVATE in response.text + output.getvalue(), "Response validation exposed stored content")
            finally:
                host.dependency_overrides = previous

    async def test_draft_storage_validation_errors_remain_private(self):
        from fastapi.testclient import TestClient
        from app.api.routes import notes
        from app.api.security import require_preview_access
        from app.main import app
        from api.notes import draft, drafts

        hosts = [(app, notes), (drafts.app, drafts)]
        operations = [("GET", "/api/notes/drafts/poc-draft", "get_temporary_draft"),
                      ("GET", "/api/notes/drafts", "list_temporary_drafts"),
                      ("POST", "/api/notes/drafts", "save_temporary_draft")]
        cases = [(host, module, method, path, dependency) for host, module in hosts
                 for method, path, dependency in operations]
        cases.append((draft.app, draft, "GET", "/api/notes/drafts/poc-draft", "get_temporary_draft"))
        for host, module, method, path, dependency in cases:
            previous = host.dependency_overrides.copy()
            host.dependency_overrides[require_preview_access] = lambda: "synthetic-owner"
            try:
                with self.subTest(host=host.title, operation=dependency), \
                     patch.object(module, dependency, side_effect=validation_failure()), diagnostics() as output:
                    try:
                        response = TestClient(host).request(method, path, json={"case_id": "poc-case", "session_number": 1})
                    except Exception:
                        raise self.failureException("Draft validation escaped the private diagnostic boundary") from None
                    self.assertEqual(500, response.status_code)
                    self.assertFalse(PRIVATE in response.text + output.getvalue(), "Draft validation exposed stored content")
            finally:
                host.dependency_overrides = previous
