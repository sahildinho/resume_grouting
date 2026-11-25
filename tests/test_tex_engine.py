"""Unit tests for tools/tex_engine.py."""

from pathlib import Path

import pytest

from core.schemas import (
    BaseExperience,
    TailoredBullet,
    TailoredEntry,
    TailoredResume,
)
from tools.tex_engine import (
    compile_pdf,
    escape_latex,
    render_tex,
    tag_template_slots,
    validate_tex_template,
)


SAMPLE_TEMPLATE = r"""\documentclass[11pt]{article}
\begin{document}
\begin{center}
  {\LARGE \textbf{{{CANDIDATE_NAME}}}} \\
  {{CONTACT_BLOCK}}
\end{center}
\section{Summary}
{{SUMMARY_BLOCK}}
\section{Experience}
{{EXPERIENCE_BLOCK}}
\section{Skills}
{{SKILLS_BLOCK}}
\section{Education}
{{EDUCATION_BLOCK}}
\end{document}
"""


def test_escape_latex_special_chars():
    raw = r"Saved 32% & $1.2M on R&D_project #1 (100% ^ ~ {ok} \path)"
    escaped = escape_latex(raw)
    assert r"\%" in escaped
    assert r"\&" in escaped
    assert r"\$" in escaped
    assert r"\#" in escaped
    assert r"\_" in escaped
    assert r"\textasciicircum{}" in escaped
    assert r"\textasciitilde{}" in escaped
    assert r"\{" in escaped and r"\}" in escaped
    assert r"\textbackslash{}" in escaped


def test_validate_tex_template_and_slot_tagging(tmp_path: Path):
    tex_file = tmp_path / "template.tex"
    tex_file.write_text(SAMPLE_TEMPLATE, encoding="utf-8")

    spec = validate_tex_template(tex_file)
    assert spec.is_validated is True
    keys = {s.placeholder_key for s in spec.slots}
    assert "{{EXPERIENCE_BLOCK}}" in keys
    assert "{{SKILLS_BLOCK}}" in keys


def test_tag_arbitrary_overleaf_template_without_markers():
    overleaf_tex = r"""\documentclass{article}
\begin{document}
\section{Experience}
\section*{Technical Skills}
\section{Education}
\end{document}
"""
    slots = tag_template_slots(overleaf_tex)
    assert [s.placeholder_key for s in slots] == [
        "{{EXPERIENCE_BLOCK}}",
        "{{TECHNICAL_SKILLS_BLOCK}}",
        "{{EDUCATION_BLOCK}}",
    ]


def test_validate_tex_template_rejects_invalid(tmp_path: Path):
    bad_ext = tmp_path / "template.txt"
    bad_ext.write_text("hello", encoding="utf-8")
    with pytest.raises(ValueError, match="must be a .tex file"):
        validate_tex_template(bad_ext)

    missing_doc = tmp_path / "broken.tex"
    missing_doc.write_text(r"\section{Experience}", encoding="utf-8")
    with pytest.raises(ValueError, match="documentclass"):
        validate_tex_template(missing_doc)


def test_render_tex_injects_and_escapes(tmp_path: Path):
    tex_file = tmp_path / "template.tex"
    tex_file.write_text(SAMPLE_TEMPLATE, encoding="utf-8")
    spec = validate_tex_template(tex_file)

    base = BaseExperience(
        candidate_name="Sahil Choudhari",
        contact_lines=["sahil@example.com", "Bengaluru"],
        experiences=[],
        education=[{"degree": "M.Tech", "institution": "IIT Jodhpur", "dates": "2020-2022"}],
    )
    tailored = TailoredResume(
        summary="LLM & CV Engineer with 4+ years experience.",
        experience_entries=[
            TailoredEntry(
                source_experience_id="exp_01",
                organization="Mahindra & Mahindra",
                role_title="ML Engineer",
                date_range="2022 - 2024",
                bullets=[
                    TailoredBullet(
                        bullet_id="b1",
                        source_experience_id="exp_01",
                        text="Reduced latency by 32% using PyTorch_2.0.",
                    )
                ],
            )
        ],
        skills_grouped={"ML & AI": ["PyTorch", "LLMs"]},
    )

    rendered = render_tex(spec, tailored, base)
    assert "Sahil Choudhari" in rendered
    assert r"Mahindra \& Mahindra" in rendered
    assert r"32\%" in rendered
    assert r"PyTorch\_2.0" in rendered
    assert r"\textbf{ML \& AI:}" in rendered
    assert "IIT Jodhpur" in rendered


def test_render_tex_removes_empty_projects_and_appends_custom_sections(tmp_path: Path):
    tpl = SAMPLE_TEMPLATE.replace(
        "\\section{Experience}\n{{EXPERIENCE_BLOCK}}",
        "\\section{Experience}\n{{EXPERIENCE_BLOCK}}\n\\section*{Projects}\n{{PROJECTS_BLOCK}}",
    )
    tex_file = tmp_path / "template.tex"
    tex_file.write_text(tpl, encoding="utf-8")
    spec = validate_tex_template(tex_file)

    base = BaseExperience(candidate_name="Alex", experiences=[])
    tailored = TailoredResume(
        experience_entries=[],
        project_entries=[],
        custom_sections={
            "Publications & Patents": [
                TailoredEntry(
                    source_experience_id="pub_01",
                    organization="ASME",
                    role_title="Author",
                    date_range="2023",
                    bullets=[],
                )
            ]
        },
    )
    rendered = render_tex(spec, tailored, base)
    assert r"\section*{Projects}" not in rendered
    assert r"\section*{Publications \& Patents}" in rendered
    assert "ASME" in rendered


def test_compile_pdf_handles_missing_compiler_gracefully(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("shutil.which", lambda _: None)
    assert compile_pdf(SAMPLE_TEMPLATE, output_dir=tmp_path) is None
