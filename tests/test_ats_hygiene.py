"""Unit tests for tools/ats_hygiene.py."""

from pathlib import Path

import fitz

from tools.ats_hygiene import check_tex_hygiene


def test_clean_single_column_tex_passes_hygiene():
    clean_tex = r"""\documentclass{article}
\begin{document}
\section{Experience}
Built distributed LLM inference pipeline.
\section{Education}
M.Tech, IIT Jodhpur
\section{Skills}
Python, PyTorch, Kubernetes
\end{document}
"""
    res = check_tex_hygiene(clean_tex)
    assert res.single_column_ok is True
    assert res.standard_headers_ok is True
    assert res.unresolved_placeholders == []
    assert res.hygiene_score == 100.0


def test_detects_multicolumn_tables_and_unresolved_placeholders():
    messy_tex = r"""\documentclass{article}
\begin{document}
\begin{multicols}{2}
\begin{tabular}{ll}
A & B \\
\end{tabular}
\end{multicols}
\section{My Background}
Improved throughput by [ADD METRIC: % throughput gain].
\end{document}
"""
    res = check_tex_hygiene(messy_tex)
    assert res.single_column_ok is False
    assert res.standard_headers_ok is False
    assert res.unresolved_placeholders == ["[ADD METRIC: % throughput gain]"]
    assert res.hygiene_score < 60.0
    assert len(res.warnings) >= 3


def test_pdf_page_count_check(tmp_path: Path):
    pdf_path = tmp_path / "two_page.pdf"
    doc = fitz.open()
    doc.new_page()
    doc.new_page()
    doc.save(pdf_path)
    doc.close()

    clean_tex = r"\section{Experience} Work \section{Education} Degree"
    res = check_tex_hygiene(clean_tex, pdf_path=pdf_path, page_target=1)
    assert res.tex_compiles is True
    assert res.estimated_pages == 2
    assert res.hygiene_score == 85.0
    assert any("exceeding target" in w for w in res.warnings)
