"""Exercise real LangChain callbacks using synthetic state and mocked trace sinks."""
import io
import os
import unittest
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from unittest.mock import Mock, patch

if os.environ.get("REMIND_POC_OFFLINE") != "1":
    raise unittest.SkipTest("Use the protected PoC offline runner.")

from langchain_core.globals import get_debug, get_verbose, set_debug, set_verbose
from langchain_core.runnables import RunnableLambda
from langchain_core.runnables.config import var_child_runnable_config
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.tracers.context import collect_runs, tracing_v2_enabled
from langsmith import tracing_context
from langsmith.utils import get_env_var
from langsmith.run_helpers import get_tracing_context

from app.core.config import settings
from app.graph import graph, supervision_report
from app.schemas.note import SessionInput, SupervisionReportRequest
from app.services import llm
from test_poc_storage import synthetic_result


PRIVATE = "SYNTHETIC-PRIVATE-TRACE-CANARY"


class PoCTracingTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.multiple(settings, poc_mode=True, use_stub=True,
            require_deid_review=False, enable_rag=False))
        self.stack.enter_context(patch("langchain_core.tracers.langchain.get_runtime_environment", return_value={}))
        self.addCleanup(get_env_var.cache_clear)
        original_debug, original_verbose = get_debug(), get_verbose()
        self.addCleanup(set_debug, original_debug)
        self.addCleanup(set_verbose, original_verbose)
        set_debug(False)
        set_verbose(False)
        self.session = SessionInput(case_id="SYNTHETIC-TRACE", session_number=1,
                                    counselor_memo=PRIVATE, transcript_text="", insight_lens="none")
        result = synthetic_result()
        self.state = {name: getattr(result, name) for name in (
            "sanitized_input", "structured_case_data", "evidence_mapped_data",
            "session_summary_draft", "verification_report", "document_transform_preview")}
        self.original_graph = graph.note_graph
        self.stack.enter_context(patch.object(graph, "note_graph", RunnableLambda(lambda _: self.state)))

    def run_note(self):
        return graph.run_note_pipeline(self.session, actor="synthetic-owner", allow_retrieval=False)

    def test_ambient_langsmith_context_does_not_receive_note_state(self):
        client = Mock()
        with tracing_context(enabled=True, client=client):
            self.assertIsNotNone(self.run_note().session_summary_draft)
        self.assertEqual(client.create_run.call_count, 0, "PoC source reached the trace sink")
        self.assertEqual(client.update_run.call_count, 0)

    def test_environment_tracing_does_not_receive_note_state(self):
        client = Mock()
        with patch.dict(os.environ, {"LANGSMITH_TRACING": "true", "LANGCHAIN_TRACING_V2": "true"}), \
                tracing_context(enabled=None, client=client):
            get_env_var.cache_clear()
            self.run_note()
        self.assertEqual(client.create_run.call_count, 0)

    def test_explicit_tracer_and_run_collector_fail_closed(self):
        for context in (lambda: tracing_v2_enabled(client=Mock()), collect_runs):
            with self.subTest(context=context), context():
                with self.assertRaisesRegex(RuntimeError, "diagnostic"):
                    self.run_note()

    def test_debug_and_verbose_fail_before_any_source_is_printed(self):
        for setter in (set_debug, set_verbose):
            stream = io.StringIO()
            setter(True)
            try:
                with redirect_stdout(stream), redirect_stderr(stream):
                    with self.assertRaisesRegex(RuntimeError, "diagnostic"):
                        self.run_note()
                self.assertNotIn(PRIVATE, stream.getvalue())
            finally:
                setter(False)

    def test_supervision_graph_also_suppresses_ambient_tracing(self):
        client = Mock()
        request = SupervisionReportRequest(session_input=self.session,
            session_summary_draft=synthetic_result().session_summary_draft)
        with tracing_context(enabled=True, client=client):
            result = supervision_report.run_supervision_report_pipeline(request)
        self.assertIsNotNone(result)
        self.assertEqual(client.create_run.call_count, 0)

    def test_direct_model_construction_rejects_unprotected_tracing(self):
        with patch.object(llm, "ChatOpenAI") as model, \
                patch("app.services.deid_review.require_reviewed_egress"), \
                tracing_context(enabled=True, client=Mock()):
            with self.assertRaisesRegex(RuntimeError, "diagnostic"):
                llm.get_llm()
        model.assert_not_called()

    def test_explicit_non_poc_control_still_reaches_real_trace_callbacks(self):
        with patch.object(settings, "poc_mode", False), collect_runs() as collector:
            self.run_note()
        self.assertTrue(collector.traced_runs)
        self.assertIn(PRIVATE, str(collector.traced_runs[0].inputs))

    def test_inherited_callback_fails_before_receiving_source(self):
        callback = Mock(spec=BaseCallbackHandler)
        token = var_child_runnable_config.set({"callbacks": [callback]})
        try:
            with self.assertRaisesRegex(RuntimeError, "diagnostic"):
                self.run_note()
            callback.on_chain_start.assert_not_called()
        finally:
            var_child_runnable_config.reset(token)

    def test_failure_restores_callers_tracing_context(self):
        client = Mock()
        def fail(_):
            self.assertIs(get_tracing_context()["enabled"], False)
            raise ValueError("synthetic failure")
        with tracing_context(enabled=True, client=client), \
                patch.object(graph, "note_graph", RunnableLambda(fail)):
            with self.assertRaisesRegex(ValueError, "synthetic failure"):
                self.run_note()
            self.assertIs(get_tracing_context()["enabled"], True)
        client.create_run.assert_not_called()
        client.update_run.assert_not_called()

    def test_full_stub_graph_remains_available_with_tracing_suppressed(self):
        client = Mock()
        with tracing_context(enabled=True, client=client), patch.object(graph, "note_graph", self.original_graph):
            result = self.run_note()
        self.assertTrue(result.stub)
        self.assertIsNotNone(result.session_summary_draft)
        client.create_run.assert_not_called()
        client.update_run.assert_not_called()
