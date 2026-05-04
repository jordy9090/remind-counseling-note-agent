"""FastAPI 메인 애플리케이션"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.routes import health, notes

# FastAPI 앱 생성
app = FastAPI(
    title="Remind Counseling Note Agent",
    description="상담 회기 정보 자동 요약 및 검증 시스템",
    version="0.1.0",
)

# CORS 미들웨어 설정 (프론트엔드 localhost:5173 허용)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 라우터 포함
app.include_router(health.router)
app.include_router(notes.router)


@app.get("/")
async def root():
    """루트 엔드포인트"""
    return {
        "message": "Remind Counseling Note Agent API",
        "docs": "/docs",
    }
