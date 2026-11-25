"""Stage 1 Agent: Auto-Atomizer (Raw resume text -> BaseExperience)."""

from core.schemas import BaseExperience
from tools.llm_router import LLMRouter


SYSTEM_PROMPT = """You are a Precision Data Extractor (Auto-Atomizer).
Your job is to decompose raw resume/experience text into a structured BaseExperience store.

RULES:
1. Decompose every role, project, research item, or certification into:
   - id: stable short ID like 'exp_01', 'proj_01', 'res_01'
   - context: problem statement, business/engineering environment, team size, constraints
   - action: candidate's specific individual contribution and methodology
   - tools_and_components: tech stack, CAD/FEA tools, financial models, standards, equipment
   - verified_metrics: ONLY numbers/ranges explicitly present in the input text
   - outcomes: qualitative impact where metrics are not stated
2. STRICT GROUNDING: Copy numbers, dates, organizations, and role titles verbatim.
   If a bullet has no quantitative metric, leave verified_metrics as [] — NEVER estimate or invent numbers.
3. Domain-agnostic: Preserve domain-specific units accurately (e.g., 'p95 ms', 'MPa', 'mm', 'IRR', 'bps', '$M').
"""


def run(raw_resume_text: str, router: LLMRouter) -> BaseExperience:
    """Context boundary: sees ONLY raw_resume_text (blind to JD, .tex template, Taxonomy)."""
    if not raw_resume_text.strip():
        raise ValueError("raw_resume_text cannot be empty.")
    payload = f"RAW RESUME / MASTER EXPERIENCE TEXT:\n{raw_resume_text.strip()}"
    return router.generate_structured(
        role="auto_atomizer",
        system_prompt=SYSTEM_PROMPT,
        user_payload=payload,
        response_model=BaseExperience,
    )
