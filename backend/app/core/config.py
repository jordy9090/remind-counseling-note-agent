"""설정 관리: 환경변수 로드 및 Pydantic 설정"""
from typing import Optional

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """애플리케이션 설정"""

    # OPENAI_API_KEY 가 없어도 앱이 뜨도록 Optional 처리.
    # 키가 없으면 스텁(샘플 응답) 모드로 동작한다.
    openai_api_key: Optional[str] = None
    openai_model: str = "gpt-4o-mini"

    # USE_STUB=1 이면 키가 있어도 강제로 스텁 모드 사용 (오프라인 데모용)
    use_stub: bool = False

    # Supabase: 상담 내용(임시저장 초안) 영구 저장용.
    # 값이 없으면 기존처럼 로컬 파일 시스템에 저장한다.
    supabase_url: Optional[str] = None
    supabase_service_key: Optional[str] = None
    supabase_drafts_table: str = "counseling_drafts"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

    @property
    def stub_mode(self) -> bool:
        """API 키가 없거나 USE_STUB 가 켜져 있으면 스텁 모드"""
        return self.use_stub or not self.openai_api_key

    @property
    def supabase_enabled(self) -> bool:
        """Supabase URL/키가 모두 설정되면 DB 저장 모드"""
        return bool(self.supabase_url and self.supabase_service_key)


# 전역 설정 인스턴스
settings = Settings()
