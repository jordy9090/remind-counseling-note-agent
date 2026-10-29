"""Local-only browser fixture server. In-memory data and synthetic identity only.

Run from the repository root with PYTHONPATH=backend;.; never deploy this module.
"""
import os
from fastapi import FastAPI
import uvicorn
from app.api.routes.vouchers import router
from app.api.security import require_preview_access
from backend.test_voucher_documents import ServiceTests, OWNER, CASE, NOTE

fixture = ServiceTests()
fixture.setUp()
os.environ['ENABLE_VOUCHER_DOCUMENTS'] = '1'
app = FastAPI()
app.include_router(router)
app.dependency_overrides[require_preview_access] = lambda: OWNER

case = {'case_id': CASE, 'case_alias': '합성 내담자', 'status': 'active', 'total_session_count': 1, 'latest_session_number': 1,
        'first_consultation_date': '2026-10-01', 'latest_consultation_date': '2026-10-01', 'confirmed_note_count': 1,
        'document_count': 1, 'export_count': 0, 'temporary_draft_count': 0, 'draft_note_count': 0}
document = {'document_id': NOTE, 'document_type': 'session_note', 'title': '합성 회기', 'status': 'confirmed', 'session_number': 12, 'created_at': '2026-10-01'}


@app.get('/api/cases')
def cases():
    return {'cases': [case], 'total_count': 1, 'recent_documents': []}


@app.get('/api/cases/{case_id}/dashboard')
def dashboard(case_id: str):
    assert case_id == CASE
    return {**case, 'sessions': [{'session_id': 'synthetic-session', 'session_number': 12, 'session_date': '2026-10-01'}], 'documents': [document], 'exports': []}


@app.get('/api/notes/drafts')
def drafts():
    return []


@app.get('/api/fixture/remaining')
def remaining():
    return {'remaining': len(fixture.memory.rows)}


if __name__ == '__main__':
    try:
        uvicorn.run(app, host='127.0.0.1', port=8194, access_log=False)
    finally:
        fixture.doCleanups()
