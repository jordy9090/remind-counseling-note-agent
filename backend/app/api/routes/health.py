"""Health check 엔드포인트"""
from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health_check():
    """애플리케이션 상태 확인"""
    return {"status": "ok"}
