"""Stage 3 Agent: Hybrid Enterprise ATS Simulator & Gap Classifier."""

import json
from pydantic import BaseModel, Field

from core.schemas import (
    ATSHygieneCheck,
    ATSScorecard,
    BaseExperience,
    GapItem,
    KeywordMatch,
    ParsedJD,
    TailoredResume,
)
from tools.llm_router import LLMRouter
from tools.taxonomy_engine import compute_keyword_scores


class _LLMATSEval(BaseModel):
    llm_recruiter_score: int = Field(..., ge=0, le=100)
    llm_recruiter_notes: str
    gaps: list[GapItem] = Field(default_factory=list)


SYSTEM_PROMPT = """You are an Enterprise ATS & First-Pass Recruiter Simulator (Workday / Greenhouse).
You receive pre-computed deterministic KeywordMatch[] results and ATSHygieneCheck results—DO NOT recount keywords manually.

RULES:
1. Evaluate semantic fit, clarity, and role-level alignment from a recruiter's 10-second scan (`llm_recruiter_score` 0-100 and concise `llm_recruiter_notes`).
2. For every missing `must_have` or `preferred` keyword in `keyword_heatmap`, classify it against `base_experience_summary` into `gaps`:
   - `framing_gap`: Candidate HAS the underlying experience (`suggested_source_exp_id`), just not phrased clearly in the tailored draft.
   - `hard_tool_gap`: Candidate lacks the tool/skill entirely (`suggested_source_exp_id = null`).
"""


def _tailored_to_plain_text(tailored: TailoredResume) -> str:
    parts: list[str] = []
    if tailored.summary:
        parts.append(f"SUMMARY:\n{tailored.summary}")
    for entry in tailored.experience_entries + tailored.project_entries:
        bullets = "\n".join(f"- {b.text}" for b in entry.bullets)
        parts.append(f"{entry.role_title} | {entry.organization} ({entry.date_range})\n{bullets}")
    if tailored.skills_grouped:
        skills_lines = [f"{k}: {', '.join(v)}" for k, v in tailored.skills_grouped.items()]
        parts.append("SKILLS:\n" + "\n".join(skills_lines))
    return "\n\n".join(parts)


def run(
    tailored: TailoredResume,
    jd: ParsedJD,
    heatmap: list[KeywordMatch],
    hygiene: ATSHygieneCheck,
    base: BaseExperience,
    router: LLMRouter,
) -> ATSScorecard:
    """Context boundary: sees plain-text TailoredResume, ParsedJD, deterministic heatmap/hygiene,
    and BaseExperience (skills + experience IDs/summaries only). Blind to raw .tex macros.
    """
    det_scores = compute_keyword_scores(heatmap, jd.keywords)

    base_summary = {
        "skills": base.skills,
        "experiences": [
            {
                "id": exp.id,
                "role_title": exp.role_title,
                "tools_and_components": exp.tools_and_components,
                "action": exp.action,
            }
            for exp in base.experiences
        ],
    }

    payload_obj = {
        "tailored_resume_plain_text": _tailored_to_plain_text(tailored),
        "parsed_jd": jd.model_dump(exclude={"raw_jd_text"}),
        "keyword_heatmap": [m.model_dump() for m in heatmap],
        "hygiene": hygiene.model_dump(),
        "base_experience_summary": base_summary,
    }

    llm_eval = router.generate_structured(
        role="ats_simulator",
        system_prompt=SYSTEM_PROMPT,
        user_payload=json.dumps(payload_obj, indent=2),
        response_model=_LLMATSEval,
    )

    overall = ATSScorecard.compute_overall_score(
        keyword_score=det_scores["keyword_score"],
        hygiene_score=hygiene.hygiene_score,
        llm_recruiter_score=llm_eval.llm_recruiter_score,
    )

    return ATSScorecard(
        overall_score=overall,
        keyword_score=det_scores["keyword_score"],
        hygiene_score=hygiene.hygiene_score,
        llm_recruiter_score=llm_eval.llm_recruiter_score,
        tier1_coverage_pct=det_scores["tier1_coverage_pct"],
        tier2_coverage_pct=det_scores["tier2_coverage_pct"],
        llm_recruiter_notes=llm_eval.llm_recruiter_notes,
        keyword_heatmap=heatmap,
        hygiene=hygiene,
        gaps=llm_eval.gaps,
    )
