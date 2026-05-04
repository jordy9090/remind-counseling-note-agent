"""설정 관리: 환경변수 로드 및 Pydantic 설정"""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """애플리케이션 설정"""
    openai_api_key: str
    openai_model: str = "gpt-4o-mini"
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


# 전역 설정 인스턴스
settings = Settings()
