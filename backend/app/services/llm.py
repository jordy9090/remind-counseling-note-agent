"""LLM 호출 서비스 - 유일한 외부 호출점"""
from langchain_openai import ChatOpenAI
from pydantic import BaseModel
from app.core.config import settings


def get_llm(*, timeout: float | None = None, max_retries: int = 2) -> ChatOpenAI:
    """기본 ChatOpenAI 인스턴스"""
    options = {
        "model": settings.openai_model,
        "api_key": settings.openai_api_key,
        "timeout": timeout,
        "max_retries": max_retries,
    }
    if settings.openai_reasoning_effort:
        # Reasoning-enabled requests must omit sampling parameters.
        options["reasoning_effort"] = settings.openai_reasoning_effort
    else:
        options["temperature"] = 0.3
    return ChatOpenAI(**options)


def get_structured_llm(schema: type[BaseModel], *, timeout: float | None = None, max_retries: int = 2):
    """Pydantic 스키마를 강제하는 structured output LLM"""
    llm = get_llm(timeout=timeout, max_retries=max_retries)
    return llm.with_structured_output(schema)
