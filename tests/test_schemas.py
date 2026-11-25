"""Unit tests for core/schemas.py."""

import pytest
from pydantic import ValidationError

from core.schemas import (
    ATSHygieneCheck,
    ATSScorecard,
    AtomicExperience,
    BaseExperience,
    ClaimAudit,
    CriticReport,
    GuardrailPolicy,
    KeywordMatch,
    ParsedJD,
    PipelineState,
    TailoredBullet,
    TailoredEntry,
    TailoredResume,
    TemplateSlot,
    TemplateSpec,
    VerifiedMetric,
    WeightedKeyword,
)


def test_base_experience_round_trip():
    base = BaseExperience(
        candidate_name="Sahil Choudhari",
        contact_lines=["sahil@example.com", "github.com/sahildinho"],
        experiences=[
            AtomicExperience(
                id="exp_01",
                category="work",
                organization="Mahindra AI",
                role_title="ML Engineer",
                start_date="2022-01",
                end_date="2024-06",
                context="Production defect inspection on assembly line",
                action="Built YOLOv8 + Triton inference pipeline",
                tools_and_components=["PyTorch", "TensorRT", "Kubernetes"],
                verified_metrics=[
                    VerifiedMetric(value="32%", context="p95 latency reduction")
                ],
                outcomes=["Deployed across 3 plants"],
            )
        ],
        skills=["Python", "PyTorch", "LLMs"],
        education=[{"degree": "M.Tech", "institution": "IIT Jodhpur", "dates": "2020-2022"}],
    )
    json_str = base.model_dump_json()
    restored = BaseExperience.model_validate_json(json_str)
    assert restored == base


def test_ats_scorecard_reproducible_formula():
    score = ATSScorecard.compute_overall_score(
        keyword_score=80.0,
        hygiene_score=100.0,
        llm_recruiter_score=70,
    )
    # 0.5*80 + 0.2*100 + 0.3*70 = 40 + 20 + 21 = 81
    assert score == 81


def test_claim_audit_supports_summary_and_skill_targets():
    audit_summary = ClaimAudit(
        target_type="summary",
        claim_text="4+ years in production LLMs",
        verdict="SUPPORTED",
        reasoning="Matches executive bio",
    )
    audit_skill = ClaimAudit(
        target_type="skill",
        claim_text="Rust",
        verdict="UNSUPPORTED",
        reasoning="Not found in BaseExperience",
        flagged_phrase="Rust",
    )
    report = CriticReport(
        audits=[audit_summary, audit_skill],
        unsupported_count=1,
        stretched_count=0,
    )
    assert report.audits[0].bullet_id is None
    assert report.audits[1].target_type == "skill"


def test_validation_rejects_out_of_bounds_values():
    with pytest.raises(ValidationError):
        WeightedKeyword(term="Python", tier="must_have", category="tool", weight=5.0)

    with pytest.raises(ValidationError):
        ATSHygieneCheck(hygiene_score=120.0)


def test_tailored_resume_custom_sections_and_pipeline_state():
    tailored = TailoredResume(
        summary="AI Engineer",
        experience_entries=[
            TailoredEntry(
                source_experience_id="exp_01",
                organization="Mahindra AI",
                role_title="ML Engineer",
                date_range="2022 - 2024",
                bullets=[
                    TailoredBullet(
                        bullet_id="b1",
                        source_experience_id="exp_01",
                        text="Reduced p95 latency by 32%.",
                    )
                ],
            )
        ],
        custom_sections={
            "Publications": [
                TailoredEntry(
                    source_experience_id="pub_01",
                    organization="ASME",
                    role_title="First Author",
                    date_range="2022",
                    bullets=[],
                )
            ]
        },
    )
    state = PipelineState(
        base_experience=BaseExperience(candidate_name="Test", experiences=[]),
        template_spec=TemplateSpec(
            template_path="t.tex",
            raw_tex="",
            slots=[TemplateSlot(section_name="Experience", placeholder_key="{{EXPERIENCE_BLOCK}}")],
            is_validated=True,
        ),
        parsed_jd=ParsedJD(
            role_title="LLM Architect",
            domain="software",
            seniority="Senior",
            keywords=[],
            raw_jd_text="LLM Architect",
        ),
        guardrails=GuardrailPolicy(),
        tailored_resume=tailored,
    )
    assert "Publications" in state.tailored_resume.custom_sections
