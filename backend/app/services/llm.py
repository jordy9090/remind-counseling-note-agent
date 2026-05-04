"""LLM 서비스 - 모든 외부 LLM 호출을 여기서만 처리"""
from langchain_openai import ChatOpenAI
from app.core.config import settings


def get_llm():
    """OpenAI ChatGPT 인스턴스 반환"""
    return ChatOpenAI(
        model=settings.openai_model,
        temperature=0.7,
        api_key=settings.openai_api_key,
    )


def get_structured_llm(response_schema):
    """구조화된 응답을 위한 LLM 인스턴스 반환"""
    llm = get_llm()
    # LangChain 0.1.0+ with_structured_output 메서드 사용
    return llm.with_structured_output(response_schema)
