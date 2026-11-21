"""Keep PoC counseling state out of optional LangChain diagnostic collectors."""
from contextlib import contextmanager

from langchain_core.globals import get_debug, get_verbose
from langchain_core.runnables.config import var_child_runnable_config
from langchain_core.tracers.context import run_collector_var, tracing_v2_callback_var
from langsmith import tracing_context
from langsmith.utils import tracing_is_enabled

from app.core.config import settings


def require_private_diagnostics(*, allow_ambient_tracing: bool = False) -> None:
    """Reject explicit callbacks/debugging rather than changing process-wide flags."""
    if not settings.poc_mode:
        return
    config = var_child_runnable_config.get() or {}
    callbacks = config.get("callbacks")
    handlers = getattr(callbacks, "handlers", callbacks) or getattr(callbacks, "inheritable_handlers", None)
    if (get_debug() or get_verbose() or handlers
            or tracing_v2_callback_var.get() is not None
            or run_collector_var.get() is not None
            or (not allow_ambient_tracing and tracing_is_enabled())):
        raise RuntimeError("PoC processing requires private diagnostic settings.")


@contextmanager
def private_ai_execution():
    """Suppress environment/ambient tracing before graph inputs reach callbacks."""
    if not settings.poc_mode:
        yield
        return
    require_private_diagnostics(allow_ambient_tracing=True)
    # Request-local context restores the caller's state, including after failure.
    with tracing_context(enabled=False, parent=False):
        yield
