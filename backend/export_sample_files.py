"""Generate local sample export files through the document export API.

Run from the backend directory:
    uv run python export_sample_files.py --output-dir ../sample_exports
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path
from urllib.parse import unquote

from fastapi.testclient import TestClient

from app.main import app


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="../sample_exports")
    args = parser.parse_args()

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    client = TestClient(app)
    session_payload = {
        "document_type": "session_note",
        "case_id": "CASE-DEMO-001",
        "session_number": 5,
        "session_date": "2026-05-24",
        "title": "상담 회기 기록",
        "metadata": {
            "client_alias": "가명 은하",
            "counselor_name": "박상담사",
        },
        "sections": [
            {
                "id": "main_issue",
                "title": "주요 호소",
                "content": "진로 불안과 자기비난 사고를 호소함.",
            },
            {
                "id": "session_content",
                "title": "상담 내용",
                "content": "첫 줄 상담 내용\n둘째 줄 상담 내용\n- 지원 전 회피 행동을 줄이는 과제를 논의함.",
            },
        ],
    }
    supervision_payload = {
        "document_type": "supervision_report",
        "case_id": "CASE-DEMO-001",
        "session_number": 5,
        "session_date": "2026-05-24",
        "title": "개인상담 사례 수퍼비전 보고서",
        "metadata": {
            "client_alias": "가명 은하",
            "counselor_name": "박상담사",
            "supervisor": "이수현 상담심리사 1급",
        },
        "sections": [
            {"id": "part-c", "title": "C. 상담 과정", "level": 1},
            {
                "id": "process",
                "title": "C-1. 상담진행 과정 및 회기주제",
                "level": 2,
                "contentBlocks": [
                    {
                        "id": "paragraph-1",
                        "type": "paragraph",
                        "text": "불안 자동사고를 사건-생각-감정-행동으로 구분함.",
                    },
                    {
                        "id": "table-1",
                        "type": "table",
                        "rows": [
                            {"영역": "정서", "내용": "불안 80"},
                            {"영역": "행동", "내용": "지원 전 회피"},
                        ],
                    },
                    {
                        "id": "transcript-1",
                        "type": "transcript",
                        "speakerTurns": [
                            {"turnId": "t1", "speaker": "client", "text": "계속 망했다는 생각이 들어요."},
                            {"turnId": "t2", "speaker": "counselor", "text": "그 생각의 근거를 함께 보겠습니다."},
                        ],
                    },
                    {
                        "id": "reflection-1",
                        "type": "reflection_box",
                        "text": "상담자는 정서 확인과 행동 계획의 균형을 점검할 필요가 있음.",
                    },
                ],
            },
        ],
    }

    write_export(client, {**session_payload, "format": "docx"}, output_dir)
    write_export(client, {**supervision_payload, "format": "docx"}, output_dir)
    write_export(client, {**session_payload, "format": "pdf"}, output_dir)


def write_export(client: TestClient, payload: dict, output_dir: Path) -> None:
    response = client.post("/api/documents/export", json=payload)
    label = f"{payload['document_type']} {payload['format']}"
    if response.status_code != 200:
        print(f"Skipped {label}: {response.status_code} {response.text}")
        return

    filename = download_filename(response.headers.get("content-disposition", "")) or (
        f"{payload['document_type']}_{payload['case_id']}_{payload['session_number']}회기_"
        f"{payload['session_date']}.{payload['format']}"
    )
    target = output_dir / filename
    target.write_bytes(response.content)
    print(f"Wrote {target}")


def download_filename(content_disposition: str) -> str | None:
    match = re.search(r"filename\*=UTF-8''([^;]+)", content_disposition)
    if match:
        return unquote(match.group(1))
    fallback = re.search(r'filename="?([^";]+)"?', content_disposition)
    return fallback.group(1) if fallback else None


if __name__ == "__main__":
    main()
