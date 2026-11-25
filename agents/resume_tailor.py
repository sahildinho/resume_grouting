"""Stage 2 Agent: Resume Tailor (Grounded or Hypothetical Shortlist Boost Mode)."""

import json
from typing import Optional

from core.schemas import (
    BaseExperience,
    ParsedJD,
    RevisionFeedback,
    TailoredResume,
    TailoringMode,
    TaxonomyGraph,
    TemplateSlot,
)
from tools.llm_router import LLMRouter


GROUNDED_SYSTEM_PROMPT = """You are a Grounded Resume Strategist (Resume Tailor).
Your job is to select the highest-signal AtomicExperience records for the target ParsedJD and synthesize tailored bullets within the template's slot & character limits.

RULES:
1. PROVENANCE: Every TailoredBullet MUST cite its exact `source_experience_id` from BaseExperience.
2. STRICT ANTI-HALLUCINATION: NEVER invent metrics, tools, dates, organizations, or role titles.
   - Copy organization, role_title, and date_range faithfully from BaseExperience.
   - If a Tier-1 competency demands quantification that BaseExperience lacks, insert `[ADD METRIC: <what to measure>]` in the bullet text and set `has_metric_placeholder = true`.
3. TEMPLATE BUDGET: Respect `max_items` and `max_chars_per_bullet` from TemplateSlot constraints.
4. REVISION FEEDBACK: If RevisionFeedback is provided, obey every `rejected_claims` constraint and `user_instructions` first.
5. SKILLS & SUMMARY: Only include skills/claims grounded in BaseExperience (or exact_alias equivalents from TaxonomyGraph). Leave `rendered_tex` as "". Set `is_hypothetical = false` and `hypothetical_additions = []` on all bullets.
"""


HYPOTHETICAL_SYSTEM_PROMPT = """You are a Strategic Resume Architect operating in HYPOTHETICAL SHORTLIST BOOST MODE.
The candidate explicitly wants to preview a realistic, high-shortlist-probability hypothetical resume tailored to the target ParsedJD, paired with full transparency on every added/upgraded claim so they know exactly what to study before an interview.

RULES:
1. REAL TIMELINE ANCHOR: Keep candidate organizations, role_titles, date_ranges, and education faithful to BaseExperience, and cite the closest `source_experience_id` on every entry and bullet.
2. STRATEGIC SHORTLIST BOOST:
   - Bridge missing `must_have` and `preferred` ParsedJD keywords, tools, architectures, and workflows into the strongest matching experiences (and optionally add 1-2 targeted `project_entries` citing a related `source_experience_id` if projects lack core JD skills).
   - Upgrade `summary` and `skills_grouped` to highlight both the candidate's verified strengths AND the missing high-priority JD skills required to pass ATS & recruiter screening.
   - Keep every addition technically coherent and learnable for the candidate's domain and seniority—avoid implausible claims.
3. NO RAW PLACEHOLDERS: Do NOT insert `[ADD METRIC: ...]` placeholders (`has_metric_placeholder = false`). State plausible technical scope and outcomes cleanly.
4. EXPLICIT HYPOTHETICAL TAGGING (CRITICAL):
   - For EVERY TailoredBullet that introduces ANY tool, framework, workflow, responsibility, or metric NOT explicitly verified in BaseExperience, set `is_hypothetical = true` and list the specific added/upgraded skills or claims in `hypothetical_additions`.
   - For purely grounded bullets backed completely by BaseExperience, keep `is_hypothetical = false` and `hypothetical_additions = []`.
5. TEMPLATE BUDGET & FEEDBACK: Respect `max_items` and `max_chars_per_bullet` from TemplateSlot constraints, and honor any RevisionFeedback. Leave `rendered_tex` as "".
"""

# Keep module-level alias for backward compatibility
SYSTEM_PROMPT = GROUNDED_SYSTEM_PROMPT


def run(
    base: BaseExperience,
    jd: ParsedJD,
    template_slots: list[TemplateSlot],
    taxonomy: Optional[TaxonomyGraph] = None,
    feedback: Optional[list[RevisionFeedback]] = None,
    router: Optional[LLMRouter] = None,
    mode: TailoringMode = "grounded",
) -> TailoredResume:
    """Context boundary: sees BaseExperience, ParsedJD, TemplateSlot[], relevant TaxonomyGraph, RevisionFeedback.
    Blind to raw .tex macros and CriticReport internals.
    """
    if router is None:
        raise ValueError("router is required.")

    payload_obj = {
        "tailoring_mode": mode,
        "base_experience": base.model_dump(exclude={"contact_lines"}),
        "parsed_jd": jd.model_dump(exclude={"raw_jd_text"}),
        "template_slots": [s.model_dump() for s in template_slots],
        "relevant_taxonomy_edges": [e.model_dump() for e in (taxonomy.edges if taxonomy else [])],
        "revision_feedback": [f.model_dump() for f in (feedback or [])],
    }
    payload = json.dumps(payload_obj, indent=2)
    system_prompt = HYPOTHETICAL_SYSTEM_PROMPT if mode == "hypothetical" else GROUNDED_SYSTEM_PROMPT
    return router.generate_structured(
        role="resume_tailor",
        system_prompt=system_prompt,
        user_payload=payload,
        response_model=TailoredResume,
    )
