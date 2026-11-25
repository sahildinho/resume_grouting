"""Unit tests for tools/document_parser.py."""

import json
from pathlib import Path

import pytest
from docx import Document

from tools.document_parser import parse_jd_input, parse_resume_file


DATASET_DIR = Path(__file__).resolve().parent.parent / "dataset"


def test_parse_real_software_pdf_and_yaml():
    pdf_path = DATASET_DIR / "software" / "Resume_Sahil_Choudhari.pdf"
    yaml_path = DATASET_DIR / "software" / "master_experience.yaml"

    pdf_text = parse_resume_file(pdf_path)
    yaml_text = parse_resume_file(yaml_path)

    assert "Sahil" in pdf_text
    assert len(pdf_text) > 200
    assert "Mahindra" in yaml_text


def test_parse_real_mechanical_pdf():
    mech_pdf = DATASET_DIR / "mechanical" / "Mayur Khade Resume -9 June 2024.pdf"
    text = parse_resume_file(mech_pdf)
    assert len(text) > 200


def test_parse_docx_json_txt_tex(tmp_path: Path):
    # DOCX
    docx_path = tmp_path / "resume.docx"
    doc = Document()
    doc.add_paragraph("Jane Doe — Mechanical Engineer")
    doc.add_paragraph("Designed chassis with SolidWorks and FEA.")
    doc.save(docx_path)
    assert "SolidWorks" in parse_resume_file(docx_path)

    # JSON
    json_path = tmp_path / "resume.json"
    json_path.write_text(json.dumps({"name": "Alex", "role": "Quant"}), encoding="utf-8")
    assert "Quant" in parse_resume_file(json_path)

    # TXT
    txt_path = tmp_path / "resume.txt"
    txt_path.write_text("Plain text resume", encoding="utf-8")
    assert parse_resume_file(txt_path) == "Plain text resume"

    # TEX
    tex_path = tmp_path / "resume.tex"
    tex_path.write_text(r"\section{Experience} Built DCF models.", encoding="utf-8")
    assert "DCF models" in parse_resume_file(tex_path)


def test_parse_jd_input_file_and_raw_text():
    jd_path = DATASET_DIR / "software" / "JD.txt"
    from_file = parse_jd_input(str(jd_path))
    assert "Large Language Model Architect" in from_file

    raw = "Senior Mechanical Engineer — GD&T, SolidWorks, Tolerance Stackup"
    assert parse_jd_input(raw) == raw


def test_parse_errors_on_missing_or_unsupported(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        parse_resume_file(tmp_path / "nonexistent.pdf")

    bad_file = tmp_path / "resume.exe"
    bad_file.write_text("binary", encoding="utf-8")
    with pytest.raises(ValueError, match="Unsupported file extension"):
        parse_resume_file(bad_file)

    with pytest.raises(ValueError, match="empty"):
        parse_jd_input("   ")
