"""Stage 2 Pre-Step Agent: JD Profiler & Tiered Keyword Weighter (Raw JD -> ParsedJD)."""

from core.schemas import ParsedJD
from tools.llm_router import LLMRouter


SYSTEM_PROMPT = """You are a Domain-Agnostic Job Analyst (JD Profiler).
Your job is to analyze a raw Job Description and produce a structured ParsedJD.

RULES:
1. Classify `domain` as one of: 'software', 'mechanical', 'finance', or 'hybrid'.
2. Extract `seniority` (e.g., 'Junior', 'Mid-Level', 'Senior', 'Staff / Lead') and `role_title`.
3. Infer 3-5 `metric_archetypes` valued by this role (e.g., ['p95 latency', 'throughput', 'uptime'] for Software; ['BOM cost', 'tolerances', 'cycle time'] for Mechanical; ['IRR', 'DCF', 'AUM'] for Finance).
4. Extract `keywords` as WeightedKeyword items using positional & semantic hierarchy:
   - must_have (weight 2.0 to 3.0): Explicit required qualifications, title-level tools, repeated core responsibilities.
   - preferred (weight 1.0 to 1.5): 'Good to have', 'bonus', 'preferred qualifications'.
   - implicit (weight 0.3 to 0.8): Cultural, collaboration, or seniority signals.
5. Set `raw_jd_text` to the exact input JD text.
"""


def run(raw_jd_text: str, router: LLMRouter) -> ParsedJD:
    """Context boundary: sees ONLY raw_jd_text (blind to BaseExperience and TemplateSpec)."""
    if not raw_jd_text.strip():
        raise ValueError("raw_jd_text cannot be empty.")
    payload = f"RAW JOB DESCRIPTION:\n{raw_jd_text.strip()}"
    return router.generate_structured(
        role="jd_profiler",
        system_prompt=SYSTEM_PROMPT,
        user_payload=payload,
        response_model=ParsedJD,
    )
