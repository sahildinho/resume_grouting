"""Deterministic Workday/Greenhouse ATS structural hygiene & placeholder checks."""

import re
from pathlib import Path
from typing import Optional

import fitz  # PyMuPDF

from core.schemas import ATSHygieneCheck


_PLACEHOLDER_RE = re.compile(r"\[ADD\s+METRIC:[^\]]*\]", re.IGNORECASE)
_SECTION_RE = re.compile(r"\\section\*?\{([^}]+)\}")
_MULTI_COLUMN_PATTERNS = [
    (r"\\begin\{multicols\}", "Multi-column layout (multicols) can scramble ATS reading order."),
    (r"\\begin\{tabular\*?\}", "Tabular layout detected; complex tables can break Workday/Greenhouse parsers."),
    (r"\\begin\{minipage\}", "Minipage blocks detected; side-by-side minipages can scramble ATS reading order."),
]
_STANDARD_HEADERS = {"experience", "work experience", "education", "skills", "technical skills", "projects", "summary"}


def check_tex_hygiene(
    tex_str: str,
    pdf_path: Optional[str | Path] = None,
    page_target: int = 1,
) -> ATSHygieneCheck:
    """Run deterministic structural ATS hygiene checks on rendered LaTeX (and optional compiled PDF)."""
    warnings: list[str] = []
    score = 100.0

    single_column_ok = True
    for pattern, msg in _MULTI_COLUMN_PATTERNS:
        if re.search(pattern, tex_str):
            single_column_ok = False
            warnings.append(msg)
            score -= 15.0

    sections = [s.strip().lower() for s in _SECTION_RE.findall(tex_str)]
    standard_headers_ok = any(sec in _STANDARD_HEADERS for sec in sections) if sections else False
    if not standard_headers_ok:
        warnings.append("No standard ATS section headers (Experience, Education, Skills) detected.")
        score -= 15.0

    unresolved = _PLACEHOLDER_RE.findall(tex_str)
    if unresolved:
        warnings.append(
            f"Found {len(unresolved)} unresolved metric placeholder(s); resolve before final export."
        )
        score -= min(30.0, 10.0 * len(unresolved))

    tex_compiles: Optional[bool] = None
    estimated_pages: Optional[int] = None
    if pdf_path is not None:
        pdf_file = Path(pdf_path)
        if pdf_file.exists():
            tex_compiles = True
            with fitz.open(pdf_file) as doc:
                estimated_pages = len(doc)
            if estimated_pages > page_target:
                warnings.append(
                    f"Compiled PDF is {estimated_pages} page(s), exceeding target of {page_target}."
                )
                score -= 15.0
        else:
            tex_compiles = False
            warnings.append(f"Expected compiled PDF not found at {pdf_file}.")
            score -= 10.0

    return ATSHygieneCheck(
        tex_compiles=tex_compiles,
        estimated_pages=estimated_pages,
        single_column_ok=single_column_ok,
        standard_headers_ok=standard_headers_ok,
        hygiene_score=max(0.0, min(100.0, round(score, 2))),
        unresolved_placeholders=unresolved,
        warnings=warnings,
    )
