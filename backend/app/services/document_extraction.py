"""Extract text from temporary document uploads."""
from __future__ import annotations

import zipfile
from pathlib import Path
from uuid import uuid4

from app.schemas.material import DocumentExtractionResponse
from app.services.upload_validation import ValidatedUpload


SCANNED_PDF_WARNING = "텍스트를 충분히 추출하지 못했습니다. 스캔 이미지 PDF는 현재 OCR을 지원하지 않습니다."


class DocumentExtractionError(Exception):
    """Raised when a validated document cannot be parsed."""


class DocumentExtractionService:
    """Extract text from supported document uploads."""

    def extract(self, upload: ValidatedUpload) -> DocumentExtractionResponse:
        if upload.suffix == ".txt":
            text, page_count, warnings = self._extract_txt(upload.temp_path)
        elif upload.suffix == ".docx":
            text, page_count, warnings = self._extract_docx(upload.temp_path)
        elif upload.suffix == ".pdf":
            text, page_count, warnings = self._extract_pdf(upload.temp_path)
        else:
            raise DocumentExtractionError("지원하지 않는 문서 형식입니다.")

        stripped_text = normalize_text(text)
        return DocumentExtractionResponse(
            material_id=f"material_{uuid4().hex}",
            filename=upload.filename,
            media_type=upload.media_type,
            status="warning" if warnings else "completed",
            character_count=len(stripped_text),
            page_count=page_count,
            extracted_text=stripped_text,
            warnings=warnings,
        )

    def _extract_txt(self, path: Path) -> tuple[str, int | None, list[str]]:
        try:
            return path.read_text(encoding="utf-8-sig"), None, []
        except UnicodeDecodeError as error:
            raise DocumentExtractionError("TXT 파일은 UTF-8 인코딩이어야 합니다.") from error

    def _extract_docx(self, path: Path) -> tuple[str, int | None, list[str]]:
        try:
            from docx import Document
            from docx.document import Document as DocumentObject
            from docx.opc.exceptions import PackageNotFoundError
            from docx.oxml.table import CT_Tbl
            from docx.oxml.text.paragraph import CT_P
            from docx.table import Table
            from docx.text.paragraph import Paragraph
        except ImportError as error:
            raise DocumentExtractionError("DOCX 추출 런타임을 불러오지 못했습니다.") from error

        try:
            document: DocumentObject = Document(path)
            parts: list[str] = []
            for child in document.element.body.iterchildren():
                if isinstance(child, CT_P):
                    paragraph = Paragraph(child, document)
                    if paragraph.text.strip():
                        parts.append(paragraph.text)
                elif isinstance(child, CT_Tbl):
                    table = Table(child, document)
                    rows = []
                    for row in table.rows:
                        cells = [cell.text.strip() for cell in row.cells]
                        if any(cells):
                            rows.append("\t".join(cells))
                    if rows:
                        parts.append("\n".join(rows))
            return "\n\n".join(parts), None, []
        except (PackageNotFoundError, zipfile.BadZipFile, KeyError, ValueError, OSError) as error:
            raise DocumentExtractionError("DOCX 파일을 읽을 수 없습니다. 파일이 손상되지 않았는지 확인해주세요.") from error
        except Exception as error:
            raise DocumentExtractionError("DOCX 파일을 읽을 수 없습니다. 파일이 손상되지 않았는지 확인해주세요.") from error

    def _extract_pdf(self, path: Path) -> tuple[str, int | None, list[str]]:
        try:
            from pypdf import PdfReader
            from pypdf.errors import PdfReadError
        except ImportError as error:
            raise DocumentExtractionError("PDF 추출 런타임을 불러오지 못했습니다.") from error

        try:
            if not pdf_has_eof_marker(path):
                raise DocumentExtractionError("PDF 파일을 읽을 수 없습니다. 파일이 손상되지 않았는지 확인해주세요.")
            reader = PdfReader(str(path))
            if reader.is_encrypted:
                raise DocumentExtractionError("암호화된 PDF는 현재 처리할 수 없습니다. 암호를 해제한 파일을 사용해주세요.")
            page_texts = [(page.extract_text() or "").strip() for page in reader.pages]
            text = "\n\n".join(part for part in page_texts if part)
            warnings = [SCANNED_PDF_WARNING] if len(text.strip()) < 20 else []
            return text, len(reader.pages), warnings
        except DocumentExtractionError:
            raise
        except (PdfReadError, KeyError, ValueError, OSError, EOFError) as error:
            raise DocumentExtractionError("PDF 파일을 읽을 수 없습니다. 파일이 손상되지 않았는지 확인해주세요.") from error
        except Exception as error:
            raise DocumentExtractionError("PDF 파일을 읽을 수 없습니다. 파일이 손상되지 않았는지 확인해주세요.") from error


def normalize_text(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n").strip()


def pdf_has_eof_marker(path: Path) -> bool:
    with path.open("rb") as file:
        file.seek(0, 2)
        size = file.tell()
        file.seek(max(0, size - 1024))
        tail = file.read()
    return b"%%EOF" in tail
