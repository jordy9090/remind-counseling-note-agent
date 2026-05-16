"""Re:mind — 상담 회기 노트 어시스턴트 (Streamlit 데모 UI)

흐름: 입력 → 구조화 → 회기요약 → 검증 리포트
LangGraph 로직은 backend/app 에 분리되어 있고, 이 파일은 화면만 담당한다.

실행:
    pip install -r requirements-streamlit.txt   (또는 backend uv 환경)
    streamlit run streamlit_app.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import streamlit as st

# --- backend 패키지 경로 등록 + .env 로드 (settings 임포트 전에 처리) ---
ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

try:
    from dotenv import load_dotenv

    load_dotenv(BACKEND / ".env")
except ImportError:
    pass

from app.core.config import settings  # noqa: E402
from app.pipeline import run_pipeline  # noqa: E402
from app.schemas.session import SessionInput  # noqa: E402

SAMPLE_INPUT = ROOT / "sample_data" / "session_input_001.json"

# 구조화 결과 8필드 라벨
STRUCTURE_FIELDS = [
    ("basic_info", "회기 기본정보"),
    ("presenting_problem", "주호소 / 핵심 이슈"),
    ("goals", "상담목표"),
    ("session_content", "상담 내용 · 과정"),
    ("counselor_intervention", "상담자 개입 · 성찰"),
    ("client_response", "내담자 반응 · 변화"),
    ("assessment", "상담사 평가"),
    ("next_plan", "추후 개입 계획"),
]

# 회기요약 4섹션 라벨
SUMMARY_FIELDS = [
    ("session_content", "상담 내용"),
    ("counselor_opinion", "상담자 소견"),
    ("session_summary", "회기 요약"),
    ("next_counseling_plan", "추후 상담 계획"),
]

# 검증 4분류: key → (라벨, 색상, 설명)
VERIFICATION_CATS = {
    "grounded": ("근거 있음", "#16A34A", "입력(메모·축어록)에 직접 근거가 있는 내용"),
    "ungrounded": ("근거 부족 · 추론", "#EA580C", "입력에 없으나 AI가 추론·생성한 내용"),
    "sensitive": ("민감정보 가능성", "#DC2626", "개인정보·민감 내용 — 검토 필요"),
    "needs_human_judgment": ("상담사 판단 필요", "#2563EB", "상담사가 직접 확인·수정해야 할 해석"),
}


# --------------------------- 스타일 ---------------------------
def inject_css() -> None:
    st.markdown(
        """
        <style>
          .stApp { background:#F8FAFF; }
          h1, h2, h3 { color:#1E3A8A; }
          .remind-hero {
            background:linear-gradient(135deg,#2563EB 0%,#1D4ED8 100%);
            color:#fff; padding:22px 28px; border-radius:16px; margin-bottom:8px;
          }
          .remind-hero h1 { color:#fff; margin:0; font-size:1.7rem; }
          .remind-hero p { margin:6px 0 0; opacity:.92; font-size:.95rem; }
          .vcard {
            border-left:5px solid var(--c); background:#fff;
            border-radius:10px; padding:10px 14px; margin-bottom:8px;
            box-shadow:0 1px 3px rgba(30,58,138,.08);
          }
          .vcard .src { color:#64748B; font-size:.78rem; margin-top:4px; }
          .vbadge {
            display:inline-block; color:#fff; font-size:.8rem; font-weight:600;
            padding:3px 12px; border-radius:999px; margin:14px 0 8px;
          }
        </style>
        """,
        unsafe_allow_html=True,
    )


# --------------------------- 입력 ---------------------------
def load_sample_into_state() -> None:
    data = json.loads(SAMPLE_INPUT.read_text(encoding="utf-8"))
    st.session_state.in_case_id = data["case_id"]
    st.session_state.in_session_no = int(data["session_no"])
    st.session_state.in_memo = data["counselor_memo"]
    st.session_state.in_transcript = data["transcript"]
    st.session_state.in_prev = data.get("prev_summary") or ""


def input_panel() -> SessionInput | None:
    st.subheader("① 회기 입력")
    st.caption("상담 직후 메모 · 축어록/STT · 이전 회기 요약을 붙여넣으세요.")

    st.button("📋 샘플 회기 불러오기", on_click=load_sample_into_state, use_container_width=True)

    c1, c2 = st.columns(2)
    case_id = c1.text_input("케이스 ID / 가명", key="in_case_id", placeholder="예: CASE001")
    session_no = c2.number_input("회기 번호", min_value=1, step=1, key="in_session_no")

    memo = st.text_area(
        "상담사 메모", key="in_memo", height=110,
        placeholder="상담 직후 빠르게 남긴 메모를 자유롭게 입력하세요.",
    )
    transcript = st.text_area(
        "축어록 / STT 텍스트", key="in_transcript", height=170,
        placeholder="C: ... \nCl: ...  형태로 붙여넣으세요. (선택)",
    )
    prev = st.text_area(
        "이전 회기 요약", key="in_prev", height=90,
        placeholder="이전 회기 요약이 있으면 붙여넣으세요. (선택)",
    )

    generate = st.button("✨ 초안 생성하기", type="primary", use_container_width=True)
    if not generate:
        return None

    if not (memo.strip() or transcript.strip()):
        st.warning("상담사 메모 또는 축어록 중 최소 하나는 입력해주세요.")
        return None

    return SessionInput(
        case_id=case_id.strip() or "UNTITLED",
        session_no=int(session_no),
        counselor_memo=memo.strip(),
        transcript=transcript.strip(),
        prev_summary=prev.strip() or None,
    )


# --------------------------- 출력 ---------------------------
def render_structured(data: dict, gen: int) -> dict:
    st.subheader("② 구조화 결과")
    st.caption("AI가 나눈 구역입니다. 기준이 맞는지 확인하고 직접 수정할 수 있어요.")
    edited = {}
    for key, label in STRUCTURE_FIELDS:
        edited[key] = st.text_area(
            label, value=data.get(key, ""), height=90, key=f"st_{gen}_{key}"
        )
    return edited


def render_summary(data: dict, gen: int) -> dict:
    st.subheader("③ 회기 요약 초안")
    st.info("AI가 생성한 초안입니다. 상담사가 검토·수정 후 사용하세요. (진단·임상 판단 대체 아님)")
    edited = {}
    for key, label in SUMMARY_FIELDS:
        edited[key] = st.text_area(
            label, value=data.get(key, ""), height=110, key=f"sm_{gen}_{key}"
        )
    return edited


def render_verification(data: dict) -> None:
    st.subheader("④ 검증 리포트")
    st.caption("AI 초안에서 주의 깊게 볼 지점입니다. 최종 판단은 상담사 몫입니다.")
    for cat, (label, color, desc) in VERIFICATION_CATS.items():
        items = data.get(cat, []) or []
        st.markdown(
            f'<span class="vbadge" style="background:{color}">{label} · {len(items)}</span>'
            f'<br><span style="color:#64748B;font-size:.82rem">{desc}</span>',
            unsafe_allow_html=True,
        )
        if not items:
            st.caption("· 해당 항목 없음")
            continue
        for it in items:
            st.markdown(
                f'<div class="vcard" style="--c:{color}">{it["content"]}'
                f'<div class="src">출처: {it["source"]}</div></div>',
                unsafe_allow_html=True,
            )


def build_export(case_id, session_no, structured, summary) -> str:
    lines = [f"# 회기 요약 — {case_id} / {session_no}회기\n", "## 구조화 결과"]
    for key, label in STRUCTURE_FIELDS:
        lines.append(f"\n### {label}\n{structured.get(key, '')}")
    lines.append("\n\n## 회기 요약 초안")
    for key, label in SUMMARY_FIELDS:
        lines.append(f"\n### {label}\n{summary.get(key, '')}")
    return "\n".join(lines)


# --------------------------- 메인 ---------------------------
def main() -> None:
    st.set_page_config(page_title="Re:mind — 상담 회기 노트", page_icon="🧭", layout="wide")
    inject_css()

    st.markdown(
        '<div class="remind-hero"><h1>🧭 Re:mind</h1>'
        "<p>상담 회기 노트 어시스턴트 — 입력 → 구조화 → 회기요약 → 검증 리포트</p></div>",
        unsafe_allow_html=True,
    )
    if settings.stub_mode:
        st.warning(
            "🔌 **스텁 모드**: OPENAI_API_KEY 미설정(또는 USE_STUB=1). "
            "샘플 응답으로 전체 흐름만 보여줍니다. 실제 분석은 backend/.env 에 키를 넣으면 동작합니다."
        )

    left, right = st.columns([1, 1.4], gap="large")

    with left:
        session_input = input_panel()

    if session_input is not None:
        with st.spinner("구조화 → 회기요약 → 검증 진행 중..."):
            result = run_pipeline(session_input)
        st.session_state.gen = st.session_state.get("gen", 0) + 1
        st.session_state.result = {
            "case_id": session_input.case_id,
            "session_no": session_input.session_no,
            "structured": result.structured.model_dump(),
            "summary": result.summary.model_dump(),
            "verification": result.verification.model_dump(),
            "stub": result.stub,
        }

    with right:
        res = st.session_state.get("result")
        if not res:
            st.info("← 왼쪽에서 회기 정보를 입력하고 **초안 생성하기**를 눌러주세요.")
            return

        gen = st.session_state.get("gen", 0)
        tab_s, tab_m, tab_v = st.tabs(["② 구조화 결과", "③ 회기 요약 초안", "④ 검증 리포트"])
        with tab_s:
            edited_struct = render_structured(res["structured"], gen)
        with tab_m:
            edited_summary = render_summary(res["summary"], gen)
        with tab_v:
            render_verification(res["verification"])

        st.divider()
        export_text = build_export(
            res["case_id"], res["session_no"], edited_struct, edited_summary
        )
        with st.expander("📄 통합 텍스트 미리보기 / 복사"):
            st.code(export_text, language="markdown")
        st.download_button(
            "⬇️ 마크다운 다운로드",
            data=export_text,
            file_name=f"remind_{res['case_id']}_{res['session_no']}회기.md",
            mime="text/markdown",
            use_container_width=True,
        )


if __name__ == "__main__":
    main()
