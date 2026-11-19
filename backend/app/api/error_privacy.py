"""Fixed public diagnostics for failures that may contain counseling content."""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError, ResponseValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError


logger = logging.getLogger("remind.api_errors")
PRIVATE_VALIDATION_MESSAGE = "요청 입력 형식을 확인해주세요."

# Exception classes alone do not establish that a message is safe. Preserve
# known application messages exactly, and replace all other text at the API boundary.
_PUBLIC_MESSAGES = frozenset({
    "해당 케이스를 찾을 수 없습니다.",
    "다른 사용자의 케이스에는 접근할 수 없습니다.",
    "동일한 케이스 ID가 다른 사용자에게 이미 등록되어 있습니다.",
    "이미 사용 중인 케이스 ID입니다. 다른 ID를 입력해주세요.",
    "저장할 요약 내용이 비어 있습니다.",
    "회기를 저장하지 못했습니다.",
    "저장소 연결을 확인할 수 없습니다.",
    "회기요약을 충분히 정리하지 못했습니다. 잠시 후 다시 생성해주세요. 입력 자료는 유지됩니다.",
    "요약할 상담 내용을 20자 이상 입력해주세요.",
    "확인할 내용은 200,000자까지 보낼 수 있어요.",
    "내담자 프로필 컬럼이 아직 준비되지 않았습니다. migration 20260918000100_case_client_profile.sql을 적용해주세요.",
    "인물 사전 컬럼이 아직 준비되지 않았습니다. migration 20261108000100_case_person_dictionary.sql을 적용해주세요.",
    "지원하지 않는 파일 형식입니다.",
    "파일 확장자와 Content-Type이 일치하지 않습니다.",
    "업로드 가능한 파일 크기를 초과했습니다.",
    "빈 파일은 업로드할 수 없습니다.",
    "파일 내용이 허용된 형식과 일치하지 않습니다.",
    "DOCX 파일 압축 구조가 허용된 범위를 초과했습니다.",
    "DOCX 파일 압축 해제 크기가 허용된 범위를 초과했습니다.",
    "DOCX 파일 압축률이 허용된 범위를 초과했습니다.",
    "TXT 파일은 UTF-8 인코딩이어야 합니다.",
    "DOCX 추출 런타임을 불러오지 못했습니다.",
    "DOCX 파일을 읽을 수 없습니다. 파일이 손상되지 않았는지 확인해주세요.",
    "PDF 추출 런타임을 불러오지 못했습니다.",
    "PDF 파일을 읽을 수 없습니다. 파일이 손상되지 않았는지 확인해주세요.",
    "암호화된 PDF는 현재 처리할 수 없습니다. 암호를 해제한 파일을 사용해주세요.",
    "내보낼 수 있는 본문 섹션이 없습니다.",
    "PDF 렌더링 런타임을 불러오지 못했습니다.",
    "HWPX 내보내기는 검증된 HWPX 템플릿 ZIP 구조가 준비된 뒤 활성화할 수 있습니다. 현재는 Word/한글 호환 DOCX 또는 PDF를 선택해주세요.",
    "음성을 16kHz 모노 WAV로 변환한 뒤 다시 시도해주세요.",
    "음성을 60초 이하 WAV 구간으로 나누어 업로드해주세요.",
    "화자 참조는 최대 4개입니다.",
    "화자 참조 형식이 올바르지 않습니다.",
    "화자 참조 이름이 올바르지 않습니다.",
    "화자 참조 오디오가 올바르지 않습니다.",
    "화자 참조는 2~4초여야 합니다.",
    "음성 축어록 생성 중 오류가 발생했습니다.",
    "음성에서 인식 가능한 발화를 찾지 못했습니다.",
    "음성 길이가 허용된 최대 처리 시간을 초과했습니다.",
    "다른 음성 축어록 작업이 진행 중입니다. 잠시 후 다시 시도해주세요.",
    "오디오를 해독하지 못했습니다. 파일 형식을 확인해주세요.",
    "GPU 메모리가 부족합니다. 배치 크기를 줄여 다시 시도해주세요.",
    "음성 인식에 실패했습니다. 로컬 모델과 실행 환경을 확인해주세요.",
    "로컬 음성 처리 설정을 확인해주세요.",
    "WhisperX 패키지가 설치되어 있지 않습니다.",
    "음성 API 연결 설정이 필요합니다.",
    "화자분리를 지원하는 음성 모델 설정을 확인해주세요.",
    "음성 API 사용량 또는 요청 한도를 초과했습니다. 잠시 후 다시 시도해주세요.",
    "음성 구간의 시간 정보가 올바르지 않습니다. 다시 시도해주세요.",
    "CLOVA Speech 연결 설정이 필요합니다.",
    "CLOVA Speech 시간 정보가 올바르지 않습니다.",
    "CLOVA Speech 응답 형식이 올바르지 않습니다.",
    "CLOVA Speech 단어 시간 정보가 올바르지 않습니다.",
    "CLOVA Speech 화자 참조와 본문을 구분하지 못했습니다. 구간을 다시 처리해주세요.",
    "CLOVA Speech 키워드 설정을 확인해주세요.",
    "CLOVA Speech 처리에 실패했습니다. 연결 또는 사용 한도를 확인해주세요.",
    "CLOVA Speech 인식이 완료되지 않았습니다. 다시 시도해주세요.",
    "Generated note was not found.",
    "Generated note is missing a session_id and cannot be confirmed.",
    "Generated note session was not found.",
    "Generated note case_id does not match the stored session case_id.",
    "Stored case for this note was not found.",
    "Stored session does not belong to the fetched case.",
    "This preview actor cannot confirm notes for the stored case.",
    "confirmed_note must contain the counselor-reviewed note sections.",
    "Generated note is already confirmed with different content; mark counselor_edited=true or use a revision flow.",
    "ENABLE_PERSISTENCE is false; note confirmation is disabled.",
    "Supabase credentials are missing; note confirmation cannot be validated.",
})


def public_error_message(error: Exception, fallback: str) -> str:
    value = error.args[0] if error.args else None
    return value if type(value) is str and value in _PUBLIC_MESSAGES else fallback


def log_private_failure(code: str) -> None:
    """Call only with a static operation code, without exception or request data."""
    logger.warning("operation_failed code=%s", code)


def install_private_validation_handler(app: FastAPI) -> None:
    """Avoid serializing rejected values, dynamic key names, or validator context."""
    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, error: RequestValidationError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": PRIVATE_VALIDATION_MESSAGE},
                            headers={"Cache-Control": "no-store"})

    @app.exception_handler(ResponseValidationError)
    @app.exception_handler(ValidationError)
    async def invalid_internal_model(request: Request, error: Exception) -> JSONResponse:
        log_private_failure("internal_validation")
        return JSONResponse(status_code=500,
                            content={"detail": "요청을 처리하지 못했습니다. 잠시 후 다시 시도해주세요."},
                            headers={"Cache-Control": "no-store"})
