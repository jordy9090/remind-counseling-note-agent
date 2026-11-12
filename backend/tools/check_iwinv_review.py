"""Exercise the actual iwinv detector with a synthetic transcript, without OpenAI."""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.config import settings
from app.services.deid_review import ReviewConfirm, ReviewStart, SpanEdit, confirm_review, start_review

parser = argparse.ArgumentParser()
parser.add_argument("--url", default="https://127.0.0.1:14443")
parser.add_argument("--credential-dir", type=Path, default=Path.home() / ".codex/secrets/iwinv-deid")
args = parser.parse_args()
directory = args.credential_dir
settings.deid_service_token = (directory / "worker.env").read_text().strip().split("=", 1)[1]
settings.deid_service_ca_pem = (directory / "server.crt").read_text()
settings.deid_review_signing_key = (directory / "review.key").read_text()
settings.deid_service_url = args.url

text = ("내담자: 제 이름은 윤가온입니다. 전화번호는 010-0000-3141이고 이메일은 gaon@example.invalid입니다. "
        "가상누리병원에서 일합니다. 약 5mg은 2주 동안 복용하지 않았어요. 검사점수는 72점입니다.\n"
        "상담자: 복용하지 않았다는 말씀을 확인했습니다.")
started = time.monotonic()
result = start_review(ReviewStart(purpose="quick", payload={"text": text}), "synthetic-owner")
while result.get("status") == "pending":
    time.sleep(5)
    result = start_review(ReviewStart(purpose="quick", payload={"text": text}, job_token=result["job_token"]), "synthetic-owner")
seconds = round(time.monotonic() - started, 2)
edits = []
occupied = set()
for item in sorted(result["items"], key=lambda value: len(value["original"]), reverse=True):
    offset = 0
    while (offset := text.find(item["original"], offset)) >= 0:
        end = offset + len(item["original"])
        if not occupied.intersection(range(offset, end)):
            edits.append(SpanEdit(path="/text", start=offset, end=end, original=item["original"], replacement=f'[{item["replacement"]}]'))
            occupied.update(range(offset, end))
        offset = end
approved = confirm_review(ReviewConfirm(purpose="quick", payload=result["payload"], detection_token=result["detection_token"], edits=edits), "synthetic-owner")
masked = approved["payload"]["text"]
for canary in ["윤가온", "010-0000-3141", "gaon@example.invalid", "가상누리병원"]:
    assert canary not in masked, "Synthetic identifier was missed"
for fact in ["5mg", "2주", "복용하지 않았어요", "72점"]:
    assert fact in masked, "Clinical fact was changed"
print(json.dumps({"status": "passed", "detection_seconds": seconds, "model_used": result["model_used"],
                  "candidate_count": len(result["items"]), "reviewed_text": masked}, ensure_ascii=True))
