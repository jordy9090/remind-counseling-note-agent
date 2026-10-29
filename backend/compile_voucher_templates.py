"""Rebuild fixed PDF text layers without retaining example text underneath.

Extraction (authoring environment with pdfplumber):
    python backend/compile_voucher_templates.py extract --work-dir tmp_ab/voucher-layout
Compilation (normal backend dependencies):
    python backend/compile_voucher_templates.py compile --work-dir tmp_ab/voucher-layout

This is a maintainer tool, never part of a request or an automatic deployment.
"""
import argparse
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent / 'app/templates/vouchers/2026'


def extract(directory):
    import pdfplumber
    for name in ('form10', 'form26'):
        with pdfplumber.open(ROOT / f'source/{name}.pdf') as document:
            chars = [{key: char[key] for key in ('text', 'x0', 'top', 'bottom', 'size')} for char in document.pages[0].chars]
            (directory / f'{name}.json').write_text(json.dumps(chars, ensure_ascii=False), encoding='utf8')


def compile_templates(directory):
    from app.services.voucher_renderer import bindings, font
    from pypdf import PdfReader, PdfWriter
    from reportlab.pdfgen.canvas import Canvas
    font()
    for name in ('form10', 'form26'):
        chars = json.loads((directory / f'{name}.json').read_text('utf8'))
        overlay = BytesIO()
        canvas = Canvas(overlay, pagesize=(595, 841), invariant=1)
        rectangles = [rect for _, rect in bindings(name).values()]
        for char in chars:
            if any(x-.1 <= char['x0'] < x+w and y-.1 <= (char['top']+char['bottom'])/2 < y+h for x, y, w, h in rectangles):
                continue
            canvas.setFont('VoucherKorean', char['size'])
            canvas.drawString(char['x0'], 841-char['top']-char['size']*.85, char['text'])
        canvas.save()
        writer = PdfWriter()
        writer.add_page(PdfReader(ROOT / f'source/{name}.pdf').pages[0])
        writer.remove_text()
        writer.pages[0].merge_page(PdfReader(overlay).pages[0])
        writer.write(ROOT / f'compiled/{name}.pdf')
    manifest_file = ROOT / 'manifest.json'
    manifest = json.loads(manifest_file.read_text('utf8'))
    manifest['assets'] = {name: sha256((ROOT / name).read_bytes()).hexdigest() for name in manifest['assets']}
    manifest_file.write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n', encoding='utf8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('action', choices=['extract', 'compile'])
    parser.add_argument('--work-dir', type=Path, required=True)
    args = parser.parse_args()
    args.work_dir.mkdir(parents=True, exist_ok=True)
    (extract if args.action == 'extract' else compile_templates)(args.work_dir)
