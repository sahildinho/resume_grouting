"""Strict LaTeX template gate, safe escaping, slot rendering, and optional PDF compile."""

import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from core.schemas import BaseExperience, TailoredEntry, TailoredResume, TemplateSlot, TemplateSpec


_LATEX_ESCAPE_MAP = {
    "\\": r"\textbackslash{}",
    "{": r"\{",
    "}": r"\}",
    "$": r"\$",
    "#": r"\#",
    "&": r"\&",
    "_": r"\_",
    "%": r"\%",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}
_LATEX_ESCAPE_RE = re.compile("|".join(re.escape(k) for k in _LATEX_ESCAPE_MAP))
_SLOT_MARKER_RE = re.compile(r"(\{\{[A-Z0-9_]+\}\})")
_SECTION_HEADER_RE = re.compile(r"\\section\*?\{([^}]+)\}")


def escape_latex(text: str) -> str:
    """Escape LaTeX reserved characters in plain text without double-escaping."""
    if not text:
        return ""
    return _LATEX_ESCAPE_RE.sub(lambda m: _LATEX_ESCAPE_MAP[m.group(0)], text)


def tag_template_slots(raw_tex: str) -> list[TemplateSlot]:
    """Detect explicit {{SLOT}} markers or fallback to \\section{...} headers."""
    markers = _SLOT_MARKER_RE.findall(raw_tex)
    if markers:
        seen: set[str] = set()
        slots: list[TemplateSlot] = []
        for marker in markers:
            if marker not in seen:
                seen.add(marker)
                section_name = marker.strip("{}").replace("_BLOCK", "").replace("_", " ").title()
                slots.append(TemplateSlot(section_name=section_name, placeholder_key=marker))
        return slots

    # Fallback for arbitrary Overleaf templates without {{...}} markers
    sections = _SECTION_HEADER_RE.findall(raw_tex)
    return [
        TemplateSlot(
            section_name=sec.strip(),
            placeholder_key=f"{{{{{_normalize_slot_name(sec)}_BLOCK}}}}",
        )
        for sec in sections
    ]


def _normalize_slot_name(section_name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", section_name.strip()).strip("_")
    return cleaned.upper() or "SECTION"


def validate_tex_template(path: str | Path) -> TemplateSpec:
    """Hard pre-flight gate: verify .tex file exists, has valid document structure, and extract slots."""
    tex_path = Path(path)
    if not tex_path.exists():
        raise FileNotFoundError(f"LaTeX template not found: {tex_path}")
    if tex_path.suffix.lower() != ".tex":
        raise ValueError(f"Template must be a .tex file, got: {tex_path.suffix}")

    raw_tex = tex_path.read_text(encoding="utf-8")
    if r"\documentclass" not in raw_tex:
        raise ValueError("Invalid LaTeX template: missing \\documentclass declaration.")
    if r"\begin{document}" not in raw_tex or r"\end{document}" not in raw_tex:
        raise ValueError("Invalid LaTeX template: missing \\begin{document} or \\end{document}.")

    slots = tag_template_slots(raw_tex)
    if not slots:
        raise ValueError(
            "Invalid LaTeX template: no {{...}} slot markers or \\section{...} headers found."
        )

    return TemplateSpec(
        template_path=str(tex_path),
        raw_tex=raw_tex,
        slots=slots,
        is_validated=True,
    )


def _format_entries_latex(entries: list[TailoredEntry]) -> str:
    blocks: list[str] = []
    for entry in entries:
        org = escape_latex(entry.organization)
        role = escape_latex(entry.role_title)
        dates = escape_latex(entry.date_range)
        header = f"\\textbf{{{role}}} --- {org} \\hfill {dates}\\\\"
        bullets_tex = "\n".join(
            f"  \\item {escape_latex(b.text)}" for b in entry.bullets
        )
        block = f"{header}\n\\begin{{itemize}}\n{bullets_tex}\n\\end{{itemize}}"
        blocks.append(block)
    return "\n\n".join(blocks)


def _format_skills_latex(skills_grouped: dict[str, list[str]]) -> str:
    lines: list[str] = []
    for group, items in skills_grouped.items():
        if not items:
            continue
        escaped_group = escape_latex(group)
        escaped_items = ", ".join(escape_latex(item) for item in items)
        lines.append(f"\\textbf{{{escaped_group}:}} {escaped_items}\\\\")
    return "\n".join(lines)


def _format_education_latex(education: list[dict[str, str]]) -> str:
    lines: list[str] = []
    for edu in education:
        degree = escape_latex(edu.get("degree", ""))
        school = escape_latex(edu.get("institution", edu.get("school", "")))
        dates = escape_latex(edu.get("dates", edu.get("year", "")))
        parts = [p for p in [f"\\textbf{{{degree}}}" if degree else "", school] if p]
        line = " --- ".join(parts)
        if dates:
            line += f" \\hfill {dates}"
        if line:
            lines.append(line + r"\\")
    return "\n".join(lines)


def render_tex(
    spec: TemplateSpec,
    tailored: TailoredResume,
    base_experience: BaseExperience,
) -> str:
    """Inject escaped TailoredResume + static BaseExperience header/education into TemplateSpec."""
    rendered = spec.raw_tex

    replacements: dict[str, str] = {
        "{{CANDIDATE_NAME}}": escape_latex(base_experience.candidate_name),
        "{{CONTACT_BLOCK}}": " $\\cdot$ ".join(
            escape_latex(line) for line in base_experience.contact_lines
        ),
        "{{SUMMARY_BLOCK}}": escape_latex(tailored.summary or ""),
        "{{EXPERIENCE_BLOCK}}": _format_entries_latex(tailored.experience_entries),
        "{{PROJECTS_BLOCK}}": _format_entries_latex(tailored.project_entries),
        "{{SKILLS_BLOCK}}": _format_skills_latex(tailored.skills_grouped),
        "{{EDUCATION_BLOCK}}": _format_education_latex(base_experience.education),
    }

    extra_blocks: list[str] = []
    for section_name, entries in tailored.custom_sections.items():
        if not entries:
            continue
        key = f"{{{{{_normalize_slot_name(section_name)}_BLOCK}}}}"
        formatted = _format_entries_latex(entries)
        if key in rendered:
            replacements[key] = formatted
        else:
            extra_blocks.append(f"\\section*{{{escape_latex(section_name)}}}\n{formatted}")

    for marker, value in replacements.items():
        if marker in rendered:
            if not value.strip() and marker == "{{PROJECTS_BLOCK}}":
                rendered = re.sub(
                    r"\\section\*?\{Projects\}\s*\{\{PROJECTS_BLOCK\}\}\s*",
                    "",
                    rendered,
                )
            else:
                rendered = rendered.replace(marker, value)

    if extra_blocks and r"\end{document}" in rendered:
        extra_tex = "\n\n".join(extra_blocks) + "\n\n"
        rendered = rendered.replace(r"\end{document}", extra_tex + r"\end{document}")

    return rendered


def compile_pdf(
    tex_str: str,
    output_dir: Optional[str | Path] = None,
    filename: str = "tailored_resume",
) -> Optional[Path]:
    """Compile LaTeX string to PDF using tectonic or pdflatex if installed; return None if unavailable."""
    compiler = shutil.which("tectonic") or shutil.which("pdflatex")
    if not compiler:
        return None

    target_dir = Path(output_dir) if output_dir else Path(tempfile.mkdtemp(prefix="resume_tex_"))
    target_dir.mkdir(parents=True, exist_ok=True)
    tex_path = target_dir / f"{filename}.tex"
    tex_path.write_text(tex_str, encoding="utf-8")

    compiler_name = Path(compiler).name
    if compiler_name == "tectonic":
        cmd = [compiler, str(tex_path), "--outdir", str(target_dir)]
    else:
        cmd = [
            compiler,
            "-interaction=nonstopmode",
            "-halt-on-error",
            "-output-directory",
            str(target_dir),
            str(tex_path),
        ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise RuntimeError(f"LaTeX compilation failed ({compiler_name}):\n{result.stderr or result.stdout}")

    pdf_path = target_dir / f"{filename}.pdf"
    return pdf_path if pdf_path.exists() else None
