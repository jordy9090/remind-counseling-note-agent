# Counselor Demo V1 Implementation Plan

## 1. Current Architecture Overview

- **Frontend**: React + TypeScript + Vite + Tailwind CSS + Lucide React.
  - Current entry page `SessionDraftPage.tsx` (~176KB) holds input forms, STT audio upload, document extraction, summary draft generation, evidence popups, note editing, document transformation, and export actions all in a single massive component.
  - Routing: Currently handled with simple `hasStarted` boolean state in `App.tsx`.
- **Backend**: FastAPI + Pydantic + LangGraph + docx/WeasyPrint exporters.
  - Endpoints: `/api/notes/generate`, `/api/notes/drafts`, `/api/notes/recompose`, `/api/documents/capabilities`, `/api/documents/export`, `/api/audio/capabilities`, `/api/materials/documents/extract`.
  - Exporter: `DocumentExportService` generates `.docx` files cleanly. PDF depends on WeasyPrint runtime (unavailable in default Windows env without GTK/Pango libraries).

---

## 2. Concrete UX & Functional Problems Identified

1. **Monolithic & Overwhelming UI**: `SessionDraftPage.tsx` mixes 6 different workflow stages (upload, input, STT, AI processing, raw evidence popovers, document transformation, export) into one crowded interface.
2. **Poor Evidence Verification UX**: Evidence popovers are tiny (190px width), truncated at 74px height, floating over text, making it extremely difficult for counselors to verify claims against original session source material.
3. **Confusing Mental Model**: "AI 요약 초안", "문서 변환", "최종 상담일지" are split across confusing UI modes rather than a clean 3-step counselor review flow: **1. AI 초안 검토 → 2. 상담일지 미리보기 → 3. 검토 완료 및 DOCX/인쇄 내보내기**.
4. **Unreliable Export UX**: PDF button fails abruptly when WeasyPrint runtime is absent without explaining why or providing a browser print alternative. DOCX download status is subtle, and error states expose technical jargon.
5. **No Standalone Off-line Demo Slice**: If OpenAI or Supabase APIs fail, the user cannot easily preview the counselor review flow with deterministic, clinically rich demo fixture data.

---

## 3. Files to Change & Add

### New Components & Files
- `docs/counselor_demo_v1_plan.md` (This document)
- `frontend/src/data/counselorDemoFixture.ts`: Rich Korean fictional counseling case (내담자 김민서, 20대 취준생 대인관계 및 취업 불안) with connected transcript, counselor memo, previous session summary, risk items, and weak evidence flags.
- `frontend/src/lib/evidenceAdapter.ts`: Adapter to normalize raw backend evidence structures into rich side-by-side evidence details.
- `frontend/src/lib/documentExport.ts`: Client exporter logic with capability check, DOCX download handling, and `window.print()` browser fallback.
- `frontend/src/hooks/useCounselorDemo.ts`: State management for section edits, review status, selected claims/sections, and demo reset.
- `frontend/src/hooks/useDocumentExport.ts`: Export status, capability state, loading, and error handling.
- `frontend/src/components/counselor-demo/DemoHeader.tsx`: Clean header with client alias, session info, review status, save status, reset button, and mode toggle.
- `frontend/src/components/counselor-demo/SessionSourcePanel.tsx`: Tabbed view of raw input materials (축어록, 상담사 메모, 이전 회기 요약).
- `frontend/src/components/counselor-demo/DraftSectionEditor.tsx`: Clean 15–16px Korean body editor for each structured section (주호소, 주요 내용, 상담자 개입, 내담자 반응, 위험·안전 확인, 다음 계획) with clear action badges.
- `frontend/src/components/counselor-demo/DraftReviewPanel.tsx`: Main center workspace assembling section editors.
- `frontend/src/components/counselor-demo/EvidencePanel.tsx`: Persistent 360px scrollable right sidebar displaying source text, excerpt length, match reason, and clinical cautions.
- `frontend/src/components/counselor-demo/FinalDocumentPreview.tsx`: Printable A4 paper-style preview modal for basic counseling note, supervision report, or termination report.
- `frontend/src/components/counselor-demo/ExportActions.tsx`: Action bar with primary DOCX export, browser print/PDF fallback, and review confirmation.
- `frontend/src/components/counselor-demo/ReviewStatusBar.tsx`: Status bar showing edit summary, unsaved changes, and review completion state.
- `frontend/src/pages/CounselorDemoPage.tsx`: Dedicated Counselor Demo V1 page.

### Modified Files
- `frontend/src/App.tsx`: Support direct navigation to `/demo` or mode selection ("상담사 검토 데모" vs "기존 전체 워크플로우").
- `frontend/src/pages/LandingPage.tsx`: Update "무료로 시작하기" / "데모 체험하기" buttons to launch the polished Counselor Demo experience.
- `frontend/src/index.css`: Add `@media print` styling rules for print-optimized A4 document rendering.

---

## 4. Implementation Plan

1. **Fixture & Data Layer (`counselorDemoFixture.ts`, `evidenceAdapter.ts`)**
   - Define deterministic, realistic counseling draft fixture data with 6 structured sections.
   - Include 3 source types: transcript (`STT 축어록`), memo (`상담사 메모`), prior session (`이전 회기 요약`).
   - Include 1 item requiring counselor review (`위험·안전 확인 - 약물 복용 및 우울감 수면 변화`) and 1 weak claim (`추측성 문장`).

2. **Custom Hooks & Export Logic (`useCounselorDemo.ts`, `useDocumentExport.ts`, `documentExport.ts`)**
   - Manage local edited section text, dirty state, temporary save timestamp, and review status.
   - Capability-aware document export with fallback to client-side browser print (`window.print()`) for PDF when server PDF capability is disabled.

3. **Counselor Demo UI Components (`components/counselor-demo/*`)**
   - **DemoHeader**: Professional title, client info badge (`김민서 (가명) | CASE-2026-05 | 5회기 (2026.04.28)`), demo mode label (`가상 사례 · 데모 데이터`), status badges.
   - **DraftReviewPanel & DraftSectionEditor**: Clean typography, 15px font, line-height 1.65, direct text area editing, explicit "근거 연결됨" (blue) / "상담사 확인 필요" (amber) tags.
   - **EvidencePanel**: Fixed 360px right column. Selecting a section or claim highlights exact original sentences, source type, and rationale.
   - **FinalDocumentPreview & ExportActions**: Modal rendering clean A4 paper format of the updated draft. DOCX download button, print/PDF button with capability explanation, export success toast.

4. **App & Router Integration (`App.tsx`, `LandingPage.tsx`)**
   - Provide seamless demo navigation with demo reset capability.

5. **Print CSS Styles (`index.css`)**
   - Formatted `@media print` rules ensuring headers, buttons, and sidebars disappear on print, leaving only the A4 document layout.

---

## 5. Acceptance Criteria

1. **Instant Clarity**: Counselor opens demo and sees a clear workspace with draft on left/center and source evidence on right.
2. **Reliable Standalone Execution**: Demo functions perfectly without backend/OpenAI/Supabase dependency using `counselorDemoFixture.ts`.
3. **Interactive Section Editing**: Editing section text updates live state, persists through preview, and updates exported document content.
4. **Persistent Evidence Verification**: Selecting a section highlights the exact original source excerpt in a 360px scrollable evidence panel.
5. **Clear Review & Export**:
   - Marking review complete updates status banner.
   - Final preview shows clean A4 printable document.
   - DOCX export downloads valid file with content > 0 bytes.
   - Server PDF capability error is caught gracefully and offers `window.print()` browser PDF export fallback.
6. **Build & Test**:
   - `npm run build` succeeds without TypeScript/Vite errors.
   - `uv run --link-mode=copy python smoke_test.py` passes.
   - Live browser testing verified on `http://localhost:5173`.
