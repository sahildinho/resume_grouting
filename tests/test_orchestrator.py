"""Unit tests for core/orchestrator.py and core/session_store.py."""

import json
from pathlib import Path
from typing import Type

import pytest

from core import orchestrator
from core.schemas import (
    AtomicExperience,
    BaseExperience,
    ClaimAudit,
    CriticReport,
    HITLDecision,
    HypotheticalDelta,
    OrchestratorEvent,
    ParsedJD,
    StudyPlan,
    StudyPlanItem,
    TailoredBullet,
    TailoredEntry,
    TailoredResume,
    ToLearnItem,
    VerifiedMetric,
    WeightedKeyword,
)
from core.session_store import SessionStore
from tools.llm_router import LLMRouter, LLMRouterConfig


TEMPLATE_TEX = r"""\documentclass{article}
\begin{document}
\textbf{{{CANDIDATE_NAME}}} \\ {{CONTACT_BLOCK}}
\section{Summary}
{{SUMMARY_BLOCK}}
\section{Experience}
{{EXPERIENCE_BLOCK}}
\section{Skills}
{{SKILLS_BLOCK}}
\section{Education}
{{EDUCATION_BLOCK}}
\end{document}
"""


class ScriptedRouter(LLMRouter):
    """Thread-safe scripted router keyed by response_model name."""

    def __init__(self, responses_by_model: dict[str, list[str]]):
        super().__init__(LLMRouterConfig(provider="gemini", api_key="mock-key"))
        self._responses = {k: list(v) for k, v in responses_by_model.items()}
        self.recorded_models: list[str] = []

    def _call_provider(self, system_prompt: str, user_payload: str, response_model: Type) -> str:
        name = response_model.__name__
        self.recorded_models.append(name)
        queue = self._responses.get(name, [])
        if not queue:
            raise RuntimeError(f"No scripted response left for {name}")
        return queue.pop(0)


def _base_exp() -> BaseExperience:
    return BaseExperience(
        candidate_name="Sahil Choudhari",
        contact_lines=["sahil@example.com"],
        experiences=[
            AtomicExperience(
                id="exp_01",
                category="work",
                organization="Mahindra AI",
                role_title="ML Engineer",
                start_date="2022",
                end_date="2024",
                context="RAG and CV systems",
                action="Built LLM RAG pipeline",
                tools_and_components=["Python", "PyTorch", "LLMs"],
                verified_metrics=[VerifiedMetric(value="32%", context="latency reduction")],
            )
        ],
        skills=["Python", "PyTorch", "LLMs"],
        education=[{"degree": "M.Tech", "institution": "IIT Jodhpur", "dates": "2020-2022"}],
    )


def _parsed_jd() -> ParsedJD:
    return ParsedJD(
        role_title="LLM Architect",
        domain="software",
        seniority="Senior",
        metric_archetypes=["latency"],
        keywords=[
            WeightedKeyword(term="LLMs", tier="must_have", category="skill", weight=3.0),
            WeightedKeyword(term="Python", tier="must_have", category="tool", weight=2.0),
        ],
        raw_jd_text="LLM Architect requiring Python and LLMs.",
    )


def _tailored(with_placeholder: bool = False) -> TailoredResume:
    bullet_text = (
        "Built LLM pipeline reducing latency by [ADD METRIC: % gain]."
        if with_placeholder
        else "Built LLMs pipeline in Python reducing latency by 32%."
    )
    return TailoredResume(
        summary="ML Engineer specializing in LLMs.",
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
                        text=bullet_text,
                        has_metric_placeholder=with_placeholder,
                    )
                ],
            )
        ],
        skills_grouped={"AI": ["Python", "LLMs"]},
    )


def _ats_eval_json() -> str:
    return json.dumps(
        {
            "llm_recruiter_score": 85,
            "llm_recruiter_notes": "Strong match.",
            "gaps": [],
        }
    )


def _critic_report(unsupported: int = 0) -> CriticReport:
    audits = [
        ClaimAudit(
            target_type="bullet",
            bullet_id="b1",
            source_experience_id="exp_01",
            claim_text="Built LLMs pipeline in Python reducing latency by 32%.",
            verdict="UNSUPPORTED" if unsupported else "SUPPORTED",
            reasoning="Test verdict.",
            flagged_phrase="unverified claim" if unsupported else None,
        )
    ]
    return CriticReport(audits=audits, unsupported_count=unsupported, stretched_count=0)


def test_orchestrator_parallel_run_hitl_reject_and_approve_export(tmp_path: Path):
    tex_path = tmp_path / "template.tex"
    tex_path.write_text(TEMPLATE_TEX, encoding="utf-8")
    store = SessionStore(base_dir=tmp_path / "runs")

    router = ScriptedRouter(
        {
            "ParsedJD": [_parsed_jd().model_dump_json()],
            "TailoredResume": [
                _tailored().model_dump_json(),
                _tailored().model_dump_json(),
            ],
            "_LLMATSEval": [_ats_eval_json(), _ats_eval_json()],
            "CriticReport": [
                _critic_report(unsupported=1).model_dump_json(),
                _critic_report(unsupported=0).model_dump_json(),
            ],
        }
    )

    events: list[OrchestratorEvent] = []
    state = orchestrator.init_pipeline(
        template_path=tex_path,
        jd_input="LLM Architect requiring Python and LLMs.",
        router=router,
        base_experience=_base_exp(),
        session_id="sess_01",
        on_event=events.append,
    )
    assert state.status == "READY"
    assert any(e.event_type == "setup_completed" for e in events)

    # Iteration 1: returns 1 UNSUPPORTED claim -> Exit gate must block APPROVE
    state = orchestrator.run_iteration(state, router, store=store, on_event=events.append)
    assert state.status == "AWAITING_HITL"
    assert state.critic_report.unsupported_count == 1
    assert state.tailored_resume.rendered_tex != ""

    with pytest.raises(ValueError, match="Exit gate blocked"):
        orchestrator.apply_hitl_decision(state, HITLDecision(action="APPROVE"), store=store)

    # Reject & loop to iteration 2
    state = orchestrator.apply_hitl_decision(
        state,
        HITLDecision(action="REJECT", rejected_claims=["unverified claim"]),
        store=store,
    )
    assert state.iteration == 2
    assert state.status == "READY"

    # Iteration 2: clean draft (0 unsupported)
    state = orchestrator.run_iteration(state, router, store=store)
    assert state.critic_report.unsupported_count == 0

    # Accept & Learn logs to ToLearnQueue
    state = orchestrator.apply_hitl_decision(
        state,
        HITLDecision(
            action="ACCEPT_AND_LEARN",
            to_learn_items=[
                ToLearnItem(
                    topic_or_claim="TensorRT-LLM",
                    source="hard_tool_gap",
                    priority="medium",
                    context_note="Preferred skill in JD",
                )
            ],
        ),
        store=store,
    )
    assert len(state.to_learn_queue) == 1

    # Approve & Export
    state = orchestrator.apply_hitl_decision(state, HITLDecision(action="APPROVE"), store=store)
    assert state.approved is True
    assert state.status == "APPROVED"
    assert store.get_artifact_path("sess_01", "tailored_resume.tex") is not None
    assert store.get_artifact_path("sess_01", "ToLearnQueue.json") is not None
    assert store.load_state("sess_01").approved is True


def test_exit_gate_blocks_unresolved_placeholders(tmp_path: Path):
    tex_path = tmp_path / "template.tex"
    tex_path.write_text(TEMPLATE_TEX, encoding="utf-8")
    store = SessionStore(base_dir=tmp_path / "runs")

    router = ScriptedRouter(
        {
            "ParsedJD": [_parsed_jd().model_dump_json()],
            "TailoredResume": [_tailored(with_placeholder=True).model_dump_json()],
            "_LLMATSEval": [_ats_eval_json()],
            "CriticReport": [_critic_report(unsupported=0).model_dump_json()],
        }
    )

    state = orchestrator.init_pipeline(
        template_path=tex_path,
        jd_input="LLM Architect",
        router=router,
        base_experience=_base_exp(),
        session_id="sess_ph",
    )
    state = orchestrator.run_iteration(state, router, store=store)

    with pytest.raises(ValueError, match="unresolved metric placeholder"):
        orchestrator.apply_hitl_decision(state, HITLDecision(action="APPROVE"), store=store)

    # Verify & Promote resolves the metric and re-audits cleanly
    router._responses["_LLMATSEval"].append(_ats_eval_json())
    router._responses["CriticReport"].append(_critic_report(unsupported=0).model_dump_json())
    state = orchestrator.apply_hitl_decision(
        state,
        HITLDecision(
            action="VERIFY_AND_PROMOTE",
            promoted_metrics={"exp_01": [VerifiedMetric(value="40%", context="throughput")]},
            edited_tailored_resume=_tailored(with_placeholder=False),
        ),
        router=router,
        store=store,
    )
    state = orchestrator.apply_hitl_decision(state, HITLDecision(action="APPROVE"), store=store)
    assert state.approved is True


def _hypothetical_tailored() -> TailoredResume:
    return TailoredResume(
        summary="ML Architect experienced in LLMs, Python, and distributed vLLM serving.",
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
                        text="Built LLMs pipeline with vLLM PagedAttention reducing latency by 32%.",
                        is_hypothetical=True,
                        hypothetical_additions=["vLLM", "PagedAttention"],
                    )
                ],
            )
        ],
        skills_grouped={"AI": ["Python", "LLMs", "vLLM"]},
    )


def _sample_study_plan() -> StudyPlan:
    return StudyPlan(
        target_role="LLM Architect",
        mode="hypothetical",
        estimated_total_hours=3.5,
        shortlist_boost_summary="Added vLLM inference serving to match LLM Architect JD.",
        hypothetical_deltas=[
            HypotheticalDelta(
                target_type="bullet",
                location="exp_01 / b1",
                added_or_upgraded_claim="vLLM PagedAttention serving",
                gap_addressed="vLLM",
                rationale="Bridges high-throughput serving requirement.",
            )
        ],
        study_items=[
            StudyPlanItem(
                id="study_01",
                topic="vLLM & PagedAttention",
                category="architecture_system",
                priority="high",
                estimated_hours=3.5,
                resume_claim_to_defend="Built LLMs pipeline with vLLM PagedAttention.",
                where_it_appears="Experience · exp_01 / b1",
                subtopics_to_study=["KV cache paging", "Continuous batching"],
                hands_on_exercise="Benchmark vLLM serving locally.",
                likely_interview_questions=["How does PagedAttention work?"],
            )
        ],
    )


def test_hypothetical_mode_generates_study_plan_allows_export_and_persists_progress(tmp_path: Path):
    tex_path = tmp_path / "template.tex"
    tex_path.write_text(TEMPLATE_TEX, encoding="utf-8")
    store = SessionStore(base_dir=tmp_path / "runs")

    router = ScriptedRouter(
        {
            "ParsedJD": [_parsed_jd().model_dump_json()],
            "TailoredResume": [
                _tailored().model_dump_json(),
                _hypothetical_tailored().model_dump_json(),
            ],
            "_LLMATSEval": [_ats_eval_json(), _ats_eval_json()],
            "CriticReport": [
                _critic_report(unsupported=0).model_dump_json(),
                _critic_report(unsupported=1).model_dump_json(),
            ],
            "StudyPlan": [_sample_study_plan().model_dump_json()],
        }
    )

    state = orchestrator.init_pipeline(
        template_path=tex_path,
        jd_input="LLM Architect requiring Python, LLMs, and vLLM.",
        router=router,
        base_experience=_base_exp(),
        session_id="sess_hypo",
        tailoring_mode="grounded",
    )

    # First run in grounded mode captures baseline score
    state = orchestrator.run_iteration(state, router, store=store)
    assert state.baseline_ats_score == state.ats_scorecard.overall_score
    assert state.study_plan is None

    # Switch to hypothetical mode: generates StudyPlan, syncs ToLearnQueue, allows export despite unsupported_count=1
    state = orchestrator.run_iteration(
        state, router, store=store, tailoring_mode="hypothetical"
    )
    assert state.tailoring_mode == "hypothetical"
    assert state.study_plan is not None
    assert len(state.study_plan.study_items) == 1
    assert any(item.source == "hypothetical_addition" for item in state.to_learn_queue)

    # Toggle studied progress
    state = orchestrator.toggle_study_item(state, "study_01", True, store=store)
    assert state.study_plan.study_items[0].studied is True

    # Approve & export succeeds with StudyPlan artifacts
    state = orchestrator.apply_hitl_decision(state, HITLDecision(action="APPROVE"), store=store)
    assert state.approved is True
    assert store.get_artifact_path("sess_hypo", "StudyPlan.md") is not None
    assert store.get_artifact_path("sess_hypo", "StudyPlan.json") is not None
    assert "[x] vLLM & PagedAttention" in store.get_artifact_path("sess_hypo", "StudyPlan.md").read_text(encoding="utf-8")
