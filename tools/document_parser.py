"""Multi-format document ingestion for resumes and job descriptions."""

from pathlib import Path
import json

import fitz  # PyMuPDF
import trafilatura
import yaml
from docx import Document


SUPPORTED_RESUME_EXTENSIONS = {".pdf", ".docx", ".txt", ".md", ".json", ".yaml", ".yml", ".tex"}


def parse_resume_file(path: str | Path) -> str:
    """Extract clean plain text from PDF, DOCX, TXT, MD, JSON, YAML, or LaTeX files."""
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    ext = file_path.suffix.lower()
    if ext not in SUPPORTED_RESUME_EXTENSIONS:
        raise ValueError(
            f"Unsupported file extension '{ext}'. Supported: {sorted(SUPPORTED_RESUME_EXTENSIONS)}"
        )

    if ext == ".pdf":
        return _parse_pdf(file_path)
    if ext == ".docx":
        return _parse_docx(file_path)
    if ext in {".txt", ".md", ".tex"}:
        return file_path.read_text(encoding="utf-8").strip()
    if ext == ".json":
        data = json.loads(file_path.read_text(encoding="utf-8"))
        return json.dumps(data, indent=2, ensure_ascii=False)
    if ext in {".yaml", ".yml"}:
        data = yaml.safe_load(file_path.read_text(encoding="utf-8"))
        return yaml.safe_dump(data, sort_keys=False, allow_unicode=True).strip()

    raise ValueError(f"Unhandled extension: {ext}")


def _parse_pdf(file_path: Path) -> str:
    pages: list[str] = []
    with fitz.open(file_path) as doc:
        for page in doc:
            text = page.get_text("text")
            if text:
                pages.append(text.strip())
    return "\n\n".join(pages).strip()


def _parse_docx(file_path: Path) -> str:
    doc = Document(str(file_path))
    parts: list[str] = []
    for para in doc.paragraphs:
        if para.text.strip():
            parts.append(para.text.strip())
    for table in doc.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
            if cells:
                parts.append(" | ".join(cells))
    return "\n".join(parts).strip()


def parse_jd_input(text_or_url_or_path: str) -> str:
    """Ingest a Job Description from raw text, a URL, or a local file path."""
    raw = text_or_url_or_path.strip()
    if not raw:
        raise ValueError("Job description input is empty.")

    if raw.startswith("http://") or raw.startswith("https://"):
        downloaded = trafilatura.fetch_url(raw)
        if not downloaded:
            raise ValueError(
                f"Failed to fetch URL '{raw}'. If it is JS-rendered, paste the JD text or upload a PDF/DOCX."
            )
        extracted = trafilatura.extract(downloaded, include_comments=False, include_tables=True)
        if not extracted or not extracted.strip():
            raise ValueError(
                f"Extracted empty text from URL '{raw}'. Paste the JD text directly instead."
            )
        return extracted.strip()

    # Check if it looks like a local file path
    if "\n" not in raw and len(raw) < 512:
        candidate = Path(raw)
        if candidate.exists() and candidate.is_file():
            return parse_resume_file(candidate)

    return raw
