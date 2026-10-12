"""LLM 호출 서비스 - 유일한 외부 호출점"""
from langchain_openai import ChatOpenAI
from pydantic import BaseModel
from app.core.config import settings


def get_llm(*, timeout: float | None = None, max_retries: int = 0) -> ChatOpenAI:
    """Use bounded provider calls and the evaluated reasoning setting by default."""
    options = {
        "model": settings.openai_model,
        "api_key": settings.openai_api_key,
        "timeout": timeout if timeout is not None else settings.openai_timeout_seconds,
        "max_retries": max_retries,
    }
    effort = settings.openai_reasoning_effort or ("low" if settings.openai_model == "gpt-5.4" else None)
    if effort:
        # Reasoning-enabled requests must omit sampling parameters.
        options["reasoning_effort"] = effort
    else:
        options["temperature"] = 0.3
    return ChatOpenAI(**options)


def get_structured_llm(schema: type[BaseModel], *, timeout: float | None = None, max_retries: int = 0):
    """Pydantic 스키마를 강제하는 structured output LLM"""
    llm = get_llm(timeout=timeout, max_retries=max_retries)
    return llm.with_structured_output(schema)
