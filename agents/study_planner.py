"""Stage 4 Study Planner Agent: Maps hypothetical additions, NLI stretches, and hard gaps into a study roadmap."""

import json
from typing import Optional

from core.schemas import (
    ATSScorecard,
    BaseExperience,
    CriticReport,
    ParsedJD,
    StudyPlan,
    TailoredResume,
    TailoringMode,
    ToLearnItem,
)
from tools.llm_router import LLMRouter


SYSTEM_PROMPT = """You are a Technical Career Coach & Interview Strategist (Study Planner).
Your job is to compare the candidate's actual BaseExperience against the generated TailoredResume (which may include hypothetical shortlist-boosting additions), the Blind NLI Critic's flagged claims, and the ATS gap analysis—then produce an actionable, prioritized StudyPlan so the candidate can genuinely learn and defend every claim in an interview.

RULES:
1. ACCOUNT FOR EVERY HYPOTHETICAL OR UNGROUNDED ADDITION:
   - Inspect every bullet where `is_hypothetical == true` or `hypothetical_additions` is non-empty.
   - Inspect every `STRETCHED` or `UNSUPPORTED` claim in `critic_flags`.
   - Inspect every `hard_tool_gap` in `ats_gaps` and any existing `to_learn_queue` items.
   - Record every added/upgraded claim in `hypothetical_deltas` with its exact `location`, `added_or_upgraded_claim`, `gap_addressed`, and `rationale`.
2. ACTIONABLE STUDY ROADMAP (`study_items`):
   - Group related gaps/additions into cohesive, high-impact `StudyPlanItem` entries (unique `id` like `study_01`, `study_02`, ...).
   - Prioritize `high` for `must_have` JD requirements and prominent resume claims; `medium` for `preferred`; `low` for peripheral concepts.
   - Quote the exact `resume_claim_to_defend` and `where_it_appears`.
   - Provide 3-6 specific, non-generic `subtopics_to_study` tailored to the target role/domain (Software, Mechanical, Finance, or Hybrid).
   - Provide 1 realistic, laptop-friendly `hands_on_exercise` (1-4 hours) so the candidate builds practical intuition, not just memorized definitions.
   - Provide 2-3 `likely_interview_questions` an interviewer will ask when probing that resume line.
   - Provide 2-4 concrete `recommended_resources` (official docs, key papers, textbooks, or exact tutorial topics).
   - Estimate realistic `estimated_hours` per item (and set `studied: false`).
3. Write a concise `shortlist_boost_summary` explaining how the hypothetical/tailored adjustments improve recruiter shortlisting and what the candidate's top focus areas are.
"""


def run(
    base: BaseExperience,
    tailored: TailoredResume,
    jd: ParsedJD,
    router: LLMRouter,
    scorecard: Optional[ATSScorecard] = None,
    critic: Optional[CriticReport] = None,
    to_learn_queue: Optional[list[ToLearnItem]] = None,
    mode: TailoringMode = "hypothetical",
) -> StudyPlan:
    """Build a structured StudyPlan bridging BaseExperience and TailoredResume for ParsedJD."""
    if router is None:
        raise ValueError("router is required.")

    critic_flags = [
        a.model_dump()
        for a in (critic.audits if critic else [])
        if a.verdict != "SUPPORTED"
    ]
    ats_gaps = [g.model_dump() for g in (scorecard.gaps if scorecard else [])]

    base_summary = {
        "candidate_name": base.candidate_name,
        "skills": base.skills,
        "experiences": [
            {
                "id": exp.id,
                "role_title": exp.role_title,
                "organization": exp.organization,
                "tools_and_components": exp.tools_and_components,
                "action": exp.action,
                "verified_metrics": [m.model_dump() for m in exp.verified_metrics],
            }
            for exp in base.experiences
        ],
    }

    payload_obj = {
        "tailoring_mode": mode,
        "target_role": jd.role_title,
        "domain": jd.domain,
        "seniority": jd.seniority,
        "jd_keywords": [kw.model_dump() for kw in jd.keywords],
        "base_experience_summary": base_summary,
        "tailored_resume": tailored.model_dump(exclude={"rendered_tex"}),
        "critic_flags": critic_flags,
        "ats_gaps": ats_gaps,
        "existing_to_learn_queue": [item.model_dump() for item in (to_learn_queue or [])],
    }

    plan = router.generate_structured(
        role="study_planner",
        system_prompt=SYSTEM_PROMPT,
        user_payload=json.dumps(payload_obj, indent=2),
        response_model=StudyPlan,
    )

    # Normalize metadata deterministically
    plan.target_role = plan.target_role or jd.role_title
    plan.mode = mode
    seen_ids: set[str] = set()
    for idx, item in enumerate(plan.study_items, start=1):
        if not item.id or item.id in seen_ids:
            item.id = f"study_{idx:02d}"
        seen_ids.add(item.id)
    plan.estimated_total_hours = round(sum(item.estimated_hours for item in plan.study_items), 1)
    return plan


def study_plan_to_to_learn_items(plan: StudyPlan) -> list[ToLearnItem]:
    """Convert StudyPlanItem entries into enriched ToLearnItem records for ToLearnQueue.json."""
    items: list[ToLearnItem] = []
    for s in plan.study_items:
        defense_hint = (
            f"Practice: {s.hands_on_exercise}"
            + (
                f" | Prep Q: {s.likely_interview_questions[0]}"
                if s.likely_interview_questions
                else ""
            )
        )
        items.append(
            ToLearnItem(
                topic_or_claim=s.topic,
                source="hypothetical_addition" if plan.mode == "hypothetical" else "hard_tool_gap",
                priority=s.priority,
                context_note=f"{s.where_it_appears}: {s.resume_claim_to_defend}",
                resume_where=s.where_it_appears,
                what_to_study=list(s.subtopics_to_study),
                hands_on_practice=s.hands_on_exercise,
                interview_defense=defense_hint,
                estimated_hours=s.estimated_hours,
            )
        )
    return items
