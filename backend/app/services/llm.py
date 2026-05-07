"""LLM 호출 서비스 - 유일한 외부 호출점"""
from langchain_openai import ChatOpenAI
from pydantic import BaseModel
from app.core.config import settings


def get_llm() -> ChatOpenAI:
    """기본 ChatOpenAI 인스턴스"""
    return ChatOpenAI(
        model=settings.openai_model,
        api_key=settings.openai_api_key,
        temperature=0.3,
    )


def get_structured_llm(schema: type[BaseModel]):
    """Pydantic 스키마를 강제하는 structured output LLM"""
    llm = get_llm()
    return llm.with_structured_output(schema)
