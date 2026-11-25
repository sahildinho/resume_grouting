"""Pydantic v2 data contracts for Resume Copilot (Phase 1)."""

from typing import Literal, Optional
from pydantic import BaseModel, Field


# ==============================================================================
# Stage 1 — Setup & Source of Truth
# ==============================================================================


class VerifiedMetric(BaseModel):
    value: str = Field(..., description="Exact number/range, e.g., '32%', '$1.2M', '0.05mm'")
    unit: Optional[str] = None
    context: str = Field(..., description="What the metric measures, e.g., 'p95 API latency reduction'")
    is_user_verified: bool = True


class AtomicExperience(BaseModel):
    id: str = Field(..., description="Stable ID, e.g., 'exp_01' or 'proj_02'")
    category: Literal["work", "project", "education", "research", "certification"]
    organization: str
    role_title: str
    start_date: str
    end_date: str
    context: str = Field(..., description="Problem statement, environment, team size, constraints")
    action: str = Field(..., description="Candidate's specific contribution & methodology")
    tools_and_components: list[str] = Field(
        default_factory=list,
        description="Tech stack, CAD/FEA tools, financial models, standards, equipment",
    )
    verified_metrics: list[VerifiedMetric] = Field(default_factory=list)
    outcomes: list[str] = Field(default_factory=list, description="Qualitative impact")
    raw_source_text: Optional[str] = None


class BaseExperience(BaseModel):
    candidate_name: str
    contact_lines: list[str] = Field(default_factory=list)
    experiences: list[AtomicExperience]
    skills: list[str] = Field(default_factory=list)
    education: list[dict[str, str]] = Field(default_factory=list)


class TemplateSlot(BaseModel):
    section_name: str
    placeholder_key: str = Field(..., description="Marker in .tex, e.g., '{{EXPERIENCE_BLOCK}}'")
    max_items: Optional[int] = None
    max_chars_per_bullet: Optional[int] = 180


class TemplateSpec(BaseModel):
    template_path: str
    raw_tex: str
    slots: list[TemplateSlot]
    page_target: int = 1
    is_validated: bool = False


class SkillEdge(BaseModel):
    source: str
    target: str
    relation: Literal["exact_alias", "adjacent_skill"]
    domain: Optional[Literal["software", "mechanical", "finance", "general"]] = "general"


class TaxonomyGraph(BaseModel):
    edges: list[SkillEdge] = Field(default_factory=list)


class GuardrailPolicy(BaseModel):
    allow_metric_invention: bool = False
    allow_title_or_date_edits: bool = False
    missing_metric_placeholder: str = "[ADD METRIC: ...]"


# ==============================================================================
# Stage 2 — JD Profiling & Resume Generation
# ==============================================================================


class WeightedKeyword(BaseModel):
    term: str
    tier: Literal["must_have", "preferred", "implicit"]
    category: Literal["tool", "skill", "domain_concept", "soft_skill"]
    weight: float = Field(..., ge=0.1, le=3.0)


class ParsedJD(BaseModel):
    company: Optional[str] = None
    role_title: str
    domain: Literal["software", "mechanical", "finance", "hybrid"]
    seniority: str
    metric_archetypes: list[str] = Field(
        default_factory=list,
        description="What impact looks like here, e.g., ['BOM cost', 'GD&T'] or ['IRR', 'DCF']",
    )
    keywords: list[WeightedKeyword]
    raw_jd_text: str


TailoringMode = Literal["grounded", "hypothetical"]


class TailoredBullet(BaseModel):
    bullet_id: str
    source_experience_id: str = Field(
        ..., description="Provenance link back to AtomicExperience.id for NLI audit"
    )
    text: str
    targeted_keywords: list[str] = Field(default_factory=list)
    has_metric_placeholder: bool = False
    is_hypothetical: bool = Field(
        False,
        description="True when bullet includes unverified/hypothetical skills or scope to boost shortlist rate",
    )
    hypothetical_additions: list[str] = Field(
        default_factory=list,
        description="Specific unverified tools, concepts, or responsibilities introduced in hypothetical mode",
    )


class TailoredEntry(BaseModel):
    source_experience_id: str
    organization: str
    role_title: str
    date_range: str
    bullets: list[TailoredBullet]


class TailoredResume(BaseModel):
    summary: Optional[str] = None
    experience_entries: list[TailoredEntry]
    project_entries: list[TailoredEntry] = Field(default_factory=list)
    custom_sections: dict[str, list[TailoredEntry]] = Field(
        default_factory=dict,
        description="Optional domain sections like Publications, Certifications, Patents",
    )
    skills_grouped: dict[str, list[str]] = Field(default_factory=dict)
    rendered_tex: str = ""


class RevisionFeedback(BaseModel):
    iteration: int
    rejected_claims: list[str] = Field(default_factory=list)
    user_instructions: list[str] = Field(default_factory=list)
    missing_tier1_to_surface: list[str] = Field(default_factory=list)


# ==============================================================================
# Stage 3 — Hybrid ATS Simulation & Gap Analysis
# ==============================================================================


class KeywordMatch(BaseModel):
    keyword: str
    tier: Literal["must_have", "preferred", "implicit"]
    status: Literal["exact_match", "alias_match", "adjacent_match", "missing"]
    matched_via: Optional[str] = None


class ATSHygieneCheck(BaseModel):
    tex_compiles: Optional[bool] = None
    estimated_pages: Optional[int] = None
    single_column_ok: bool = True
    standard_headers_ok: bool = True
    hygiene_score: float = Field(100.0, ge=0.0, le=100.0)
    unresolved_placeholders: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class GapItem(BaseModel):
    keyword: str
    tier: Literal["must_have", "preferred"]
    gap_type: Literal["framing_gap", "hard_tool_gap"]
    suggested_source_exp_id: Optional[str] = None


class ATSScorecard(BaseModel):
    overall_score: int = Field(..., ge=0, le=100)
    keyword_score: float = Field(..., ge=0.0, le=100.0)
    hygiene_score: float = Field(..., ge=0.0, le=100.0)
    llm_recruiter_score: int = Field(..., ge=0, le=100)
    tier1_coverage_pct: float = Field(..., ge=0.0, le=100.0)
    tier2_coverage_pct: float = Field(..., ge=0.0, le=100.0)
    llm_recruiter_notes: str
    keyword_heatmap: list[KeywordMatch]
    hygiene: ATSHygieneCheck
    gaps: list[GapItem]

    @staticmethod
    def compute_overall_score(
        keyword_score: float,
        hygiene_score: float,
        llm_recruiter_score: int,
    ) -> int:
        """Deterministic weighted formula for reproducible ATS overall_score."""
        raw = 0.50 * keyword_score + 0.20 * hygiene_score + 0.30 * llm_recruiter_score
        return max(0, min(100, round(raw)))


# ==============================================================================
# Stage 4 — Blind NLI Critic & Human-in-the-Loop State
# ==============================================================================


class ClaimAudit(BaseModel):
    target_type: Literal["bullet", "summary", "skill"] = "bullet"
    bullet_id: Optional[str] = None
    source_experience_id: Optional[str] = None
    claim_text: str
    verdict: Literal["SUPPORTED", "STRETCHED", "UNSUPPORTED"]
    reasoning: str
    flagged_phrase: Optional[str] = None


class CriticReport(BaseModel):
    audits: list[ClaimAudit]
    unsupported_count: int
    stretched_count: int


class ToLearnItem(BaseModel):
    topic_or_claim: str
    source: Literal["accepted_stretch", "hard_tool_gap", "hypothetical_addition"]
    priority: Literal["high", "medium", "low"]
    context_note: str
    resume_where: Optional[str] = None
    what_to_study: list[str] = Field(default_factory=list)
    hands_on_practice: Optional[str] = None
    interview_defense: Optional[str] = None
    estimated_hours: Optional[float] = None


class HypotheticalDelta(BaseModel):
    target_type: Literal["bullet", "summary", "skill", "project"]
    location: str = Field(..., description="Where on the resume this change appears, e.g. 'exp_01 / b2' or 'Skills'")
    added_or_upgraded_claim: str
    gap_addressed: str = Field(..., description="JD requirement or keyword this bridges")
    rationale: str = Field(..., description="Why this addition increases shortlisting probability")


class StudyPlanItem(BaseModel):
    id: str
    topic: str
    category: Literal[
        "core_concept",
        "tool_framework",
        "architecture_system",
        "project_story",
        "metric_benchmark",
    ]
    priority: Literal["high", "medium", "low"]
    estimated_hours: float = Field(2.0, ge=0.5, le=200.0)
    resume_claim_to_defend: str
    where_it_appears: str
    subtopics_to_study: list[str] = Field(default_factory=list)
    hands_on_exercise: str
    likely_interview_questions: list[str] = Field(default_factory=list)
    recommended_resources: list[str] = Field(default_factory=list)
    studied: bool = False


class StudyPlan(BaseModel):
    target_role: str
    mode: TailoringMode = "hypothetical"
    estimated_total_hours: float = 0.0
    shortlist_boost_summary: str
    hypothetical_deltas: list[HypotheticalDelta] = Field(default_factory=list)
    study_items: list[StudyPlanItem] = Field(default_factory=list)


SessionStatus = Literal[
    "READY",
    "RUNNING",
    "AWAITING_HITL",
    "APPROVED",
    "MAX_ITERATIONS_REACHED",
    "FAILED",
]

HITLAction = Literal[
    "REJECT",
    "ACCEPT_AND_LEARN",
    "VERIFY_AND_PROMOTE",
    "DIRECT_EDIT",
    "APPROVE",
]


class OrchestratorEvent(BaseModel):
    event_type: Literal[
        "setup_completed",
        "stage_started",
        "deterministic_completed",
        "agent_completed",
        "paused_for_hitl",
        "hitl_applied",
        "exported",
        "error",
    ]
    stage: str
    message: str
    iteration: int = 1
    data: dict = Field(default_factory=dict)


class HITLDecision(BaseModel):
    action: HITLAction
    rejected_claims: list[str] = Field(default_factory=list)
    user_instructions: list[str] = Field(default_factory=list)
    missing_tier1_to_surface: list[str] = Field(default_factory=list)
    to_learn_items: list[ToLearnItem] = Field(default_factory=list)
    promoted_experience: Optional[AtomicExperience] = None
    promoted_metrics: dict[str, list[VerifiedMetric]] = Field(
        default_factory=dict,
        description="Map of AtomicExperience.id -> newly verified metrics to promote",
    )
    promoted_skills: list[str] = Field(default_factory=list)
    edited_tailored_resume: Optional[TailoredResume] = None


class PipelineState(BaseModel):
    session_id: Optional[str] = None
    status: SessionStatus = "READY"
    tailoring_mode: TailoringMode = "grounded"
    iteration: int = 1
    max_iterations: int = 5
    base_experience: BaseExperience
    template_spec: TemplateSpec
    parsed_jd: ParsedJD
    taxonomy: TaxonomyGraph = Field(default_factory=TaxonomyGraph)
    guardrails: GuardrailPolicy = Field(default_factory=GuardrailPolicy)
    tailored_resume: Optional[TailoredResume] = None
    ats_scorecard: Optional[ATSScorecard] = None
    baseline_ats_score: Optional[int] = None
    critic_report: Optional[CriticReport] = None
    study_plan: Optional[StudyPlan] = None
    revision_feedback: list[RevisionFeedback] = Field(default_factory=list)
    to_learn_queue: list[ToLearnItem] = Field(default_factory=list)
    approved: bool = False
