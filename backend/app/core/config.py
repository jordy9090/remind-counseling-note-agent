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
    runtime_environment: str = "production"

    # Preview API guard. Until production Supabase Auth mapping exists, every
    # /api/notes route must be protected by this backend-only token.
    remind_preview_api_token: Optional[str] = None
    remind_preview_actor: str = "preview_server_actor"
    remind_allow_local_bypass: bool = False
    enable_real_user_auth: bool = False

    # Supabase: 기존 임시저장 persistence와 V1 note/RAG persistence를 모두 지원한다.
    # SUPABASE_SERVICE_KEY는 팀원의 drafts 저장 구현, SUPABASE_SERVICE_ROLE_KEY는
    # Re:mind V1 note/RAG 저장 구현에서 사용할 수 있게 둘 다 허용한다.
    supabase_url: Optional[str] = None
    supabase_service_key: Optional[str] = None
    supabase_service_role_key: Optional[str] = None
    supabase_drafts_table: str = "counseling_drafts"
    enable_persistence: bool = False
    enable_rag: bool = False
    enable_case_memory: bool = False
    save_raw_input: bool = False
    enable_dense_retrieval: bool = False
    enable_hybrid_retrieval: bool = True
    embedding_model: str = "text-embedding-3-small"
    embedding_dimension: int = 1536
    embedding_cache_ttl_seconds: int = 300
    embedding_cache_max_entries: int = 256
    disable_embedding_cache: bool = False

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

    @property
    def stub_mode(self) -> bool:
        """API 키가 없거나 USE_STUB 가 켜져 있으면 스텁 모드"""
        return self.use_stub or not self.openai_api_key

    @property
    def effective_supabase_key(self) -> str | None:
        return self.supabase_service_role_key or self.supabase_service_key

    @property
    def supabase_enabled(self) -> bool:
        """Supabase URL/키가 모두 설정되면 DB 저장 모드"""
        return bool(self.supabase_url and self.effective_supabase_key)

    @property
    def supabase_configured(self) -> bool:
        return self.supabase_enabled

    @property
    def normalized_supabase_url(self) -> str:
        return (self.supabase_url or "").rstrip("/")

    @property
    def is_local_environment(self) -> bool:
        return self.runtime_environment.lower() in {"local", "development", "dev", "test"}

    @property
    def local_preview_bypass_enabled(self) -> bool:
        return self.remind_allow_local_bypass and self.is_local_environment


def validate_runtime_security() -> None:
    """Fail closed when persistent counseling state could be exposed."""
    has_access_guard = bool(settings.remind_preview_api_token) or settings.enable_real_user_auth
    if settings.local_preview_bypass_enabled:
        has_access_guard = True
    if settings.enable_persistence and not has_access_guard:
        raise RuntimeError(
            "ENABLE_PERSISTENCE=1 requires REMIND_PREVIEW_API_TOKEN or real user auth. "
            "For local-only development, set RUNTIME_ENVIRONMENT=development and REMIND_ALLOW_LOCAL_BYPASS=1."
        )
    if settings.enable_case_memory and not has_access_guard:
        raise RuntimeError(
            "ENABLE_CASE_MEMORY=1 requires REMIND_PREVIEW_API_TOKEN or real user auth before indexing note memory."
        )


# 전역 설정 인스턴스
settings = Settings()
