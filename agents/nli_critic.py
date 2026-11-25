"""Stage 4a Agent: Blind Adversarial NLI Critic (BaseExperience + TailoredResume ONLY, NO JD)."""

import json

from core.schemas import BaseExperience, CriticReport, TailoredResume
from tools.llm_router import LLMRouter


SYSTEM_PROMPT = """You are a Skeptical Fact-Checker performing Natural Language Inference (NLI).
You see ONLY the candidate's BaseExperience (ground truth) and the TailoredResume draft.

RULES:
1. Audit EVERY claim across:
   - Each TailoredBullet (target_type='bullet', include bullet_id and source_experience_id)
   - The TailoredResume summary if present (target_type='summary')
   - Each skill in skills_grouped (target_type='skill')
2. Assign `verdict` strictly against BaseExperience:
   - SUPPORTED: Every tool, metric, and scope claim is directly entailed by BaseExperience.
   - STRETCHED: Plausible reframing or adjacent skill, but goes slightly beyond literal evidence.
   - UNSUPPORTED: Contains an unverified metric, unlisted tool, or exaggerated ownership/scope.
3. For any STRETCHED or UNSUPPORTED item, populate `flagged_phrase` and concise `reasoning`.
4. Set `unsupported_count` and `stretched_count` accurately to match `audits`.
"""


def run(
    base: BaseExperience,
    tailored: TailoredResume,
    router: LLMRouter,
) -> CriticReport:
    """STRICT CONTEXT ISOLATION: Sees ONLY BaseExperience + TailoredResume.
    NEVER receives ParsedJD, ATSScorecard, or TaxonomyGraph.
    """
    payload_obj = {
        "base_experience": base.model_dump(),
        "tailored_resume": tailored.model_dump(exclude={"rendered_tex"}),
    }
    return router.generate_structured(
        role="nli_critic",
        system_prompt=SYSTEM_PROMPT,
        user_payload=json.dumps(payload_obj, indent=2),
        response_model=CriticReport,
    )
