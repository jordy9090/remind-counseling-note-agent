"""Serve the supplied blank form packet without rewriting its HWPX contents."""
from hashlib import sha256
import json
from pathlib import Path
from typing import Literal

from app.services.voucher_renderer import VoucherError

ROOT = Path(__file__).resolve().parents[1] / 'templates/vouchers/original'


def original_file(format: Literal['pdf', 'hwpx']) -> bytes:
    metadata = json.loads((ROOT / 'manifest.json').read_text('utf-8'))
    asset = metadata['assets'][format]
    data = (ROOT / asset['file']).read_bytes()
    if sha256(data).hexdigest() != asset['sha256']:
        raise VoucherError('ORIGINAL_FORM_UNAVAILABLE', '원본 양식 파일을 확인하지 못했습니다.', 503)
    return data
