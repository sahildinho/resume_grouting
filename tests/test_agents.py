"""Modular unit tests for tools/llm_router.py and all 5 agents (with context-boundary assertions)."""

import json
from typing import Type

import pytest

from agents import ats_simulator, auto_atomizer, jd_profiler, nli_critic, resume_tailor, study_planner
from core.schemas import (
    ATSHygieneCheck,
    AtomicExperience,
    BaseExperience,
    ClaimAudit,
    CriticReport,
    GapItem,
    HypotheticalDelta,
    KeywordMatch,
    ParsedJD,
    StudyPlan,
    StudyPlanItem,
    TailoredBullet,
    TailoredEntry,
    TailoredResume,
    TemplateSlot,
    VerifiedMetric,
    WeightedKeyword,
)
from tools.llm_router import LLMRouter, LLMRouterConfig


class MockLLMRouter(LLMRouter):
    """Deterministic mock router that records calls and returns scripted JSON responses."""

    def __init__(self, responses: list[str]):
        super().__init__(LLMRouterConfig(provider="gemini", api_key="mock-key", max_retries=2))
        self._responses = list(responses)
        self.calls: list[dict] = []

    def _call_provider(self, system_prompt: str, user_payload: str, response_model: Type) -> str:
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "user_payload": user_payload,
                "response_model": response_model.__name__,
            }
        )
        return self._responses.pop(0)


def _sample_base() -> BaseExperience:
    return BaseExperience(
        candidate_name="Sahil Choudhari",
        contact_lines=["sahil@example.com"],
        experiences=[
            AtomicExperience(
                id="exp_01",
                category="work",
                organization="Mahindra AI",
                role_title="ML Engineer",
                start_date="2022-01",
                end_date="2024-06",
                context="Enterprise RAG & defect inspection",
                action="Built LLM RAG pipeline and PyTorch CV models",
                tools_and_components=["Python", "PyTorch", "LLMs", "RAG"],
                verified_metrics=[VerifiedMetric(value="32%", context="latency reduction")],
            )
        ],
        skills=["Python", "PyTorch", "LLMs", "RAG"],
    )


def _sample_jd() -> ParsedJD:
    return ParsedJD(
        role_title="Large Language Model Architect",
        domain="software",
        seniority="Senior",
        metric_archetypes=["latency", "throughput"],
        keywords=[
            WeightedKeyword(term="Large Language Models", tier="must_have", category="skill", weight=3.0),
            WeightedKeyword(term="Python", tier="must_have", category="tool", weight=2.5),
            WeightedKeyword(term="TensorFlow", tier="preferred", category="tool", weight=1.5),
        ],
        raw_jd_text="Large Language Model Architect requiring Python and LLMs.",
    )


def test_llm_router_retries_on_invalid_json_then_succeeds():
    bad_json = '{"candidate_name": "Sahil"}'  # missing required `experiences`
    good_json = _sample_base().model_dump_json()
    router = MockLLMRouter([f"```json\n{bad_json}\n```", good_json])

    result = auto_atomizer.run("Sahil worked at Mahindra AI on LLMs.", router)
    assert result.candidate_name == "Sahil Choudhari"
    assert len(router.calls) == 2
    assert "[RETRY 1]" in router.calls[1]["user_payload"]


def test_jd_profiler_context_isolation():
    jd = _sample_jd()
    router = MockLLMRouter([jd.model_dump_json()])

    result = jd_profiler.run("Role: Large Language Model Architect", router)
    assert result.domain == "software"
    assert "BaseExperience" not in router.calls[0]["user_payload"]


def test_resume_tailor_provenance_and_context_boundaries():
    tailored = TailoredResume(
        summary="ML Engineer specializing in LLMs and PyTorch.",
        experience_entries=[
            TailoredEntry(
                source_experience_id="exp_01",
                organization="Mahindra AI",
                role_title="ML Engineer",
                date_range="2022-01 - 2024-06",
                bullets=[
                    TailoredBullet(
                        bullet_id="b1",
                        source_experience_id="exp_01",
                        text="Built LLM RAG pipeline reducing latency by 32%.",
                        targeted_keywords=["Large Language Models"],
                    )
                ],
            )
        ],
        skills_grouped={"AI/ML": ["Python", "PyTorch", "LLMs"]},
    )
    router = MockLLMRouter([tailored.model_dump_json()])
    slots = [TemplateSlot(section_name="Experience", placeholder_key="{{EXPERIENCE_BLOCK}}", max_items=3)]

    result = resume_tailor.run(_sample_base(), _sample_jd(), slots, router=router)
    assert result.experience_entries[0].bullets[0].source_experience_id == "exp_01"
    # Blind to raw LaTeX macros and CriticReport
    assert r"\documentclass" not in router.calls[0]["user_payload"]


def test_ats_simulator_combines_deterministic_and_llm_scores():
    llm_eval_json = json.dumps(
        {
            "llm_recruiter_score": 80,
            "llm_recruiter_notes": "Strong LLM & Python match; TensorFlow is adjacent to PyTorch.",
            "gaps": [
                {
                    "keyword": "TensorFlow",
                    "tier": "preferred",
                    "gap_type": "hard_tool_gap",
                    "suggested_source_exp_id": None,
                }
            ],
        }
    )
    router = MockLLMRouter([llm_eval_json])
    tailored = TailoredResume(
        experience_entries=[
            TailoredEntry(
                source_experience_id="exp_01",
                organization="Mahindra AI",
                role_title="ML Engineer",
                date_range="2022-01 - 2024-06",
                bullets=[
                    TailoredBullet(
                        bullet_id="b1",
                        source_experience_id="exp_01",
                        text="Built Large Language Models pipeline in Python.",
                    )
                ],
            )
        ],
    )
    heatmap = [
        KeywordMatch(keyword="Large Language Models", tier="must_have", status="exact_match"),
        KeywordMatch(keyword="Python", tier="must_have", status="exact_match"),
        KeywordMatch(keyword="TensorFlow", tier="preferred", status="adjacent_match", matched_via="PyTorch"),
    ]
    hygiene = ATSHygieneCheck(hygiene_score=100.0)

    scorecard = ats_simulator.run(tailored, _sample_jd(), heatmap, hygiene, _sample_base(), router)
    assert scorecard.tier1_coverage_pct == 100.0
    assert scorecard.llm_recruiter_score == 80
    assert 0 <= scorecard.overall_score <= 100
    assert len(scorecard.gaps) == 1


def test_nli_critic_strict_blindness_to_jd():
    report = CriticReport(
        audits=[
            ClaimAudit(
                target_type="bullet",
                bullet_id="b1",
                source_experience_id="exp_01",
                claim_text="Built LLM RAG pipeline reducing latency by 32%.",
                verdict="SUPPORTED",
                reasoning="Directly backed by exp_01.",
            ),
            ClaimAudit(
                target_type="skill",
                claim_text="Rust",
                verdict="UNSUPPORTED",
                reasoning="Not present in BaseExperience.",
                flagged_phrase="Rust",
            ),
        ],
        unsupported_count=1,
        stretched_count=0,
    )
    router = MockLLMRouter([report.model_dump_json()])
    tailored = TailoredResume(
        experience_entries=[
            TailoredEntry(
                source_experience_id="exp_01",
                organization="Mahindra AI",
                role_title="ML Engineer",
                date_range="2022-01 - 2024-06",
                bullets=[
                    TailoredBullet(
                        bullet_id="b1",
                        source_experience_id="exp_01",
                        text="Built LLM RAG pipeline reducing latency by 32%.",
                    )
                ],
            )
        ],
        skills_grouped={"Systems": ["Rust"]},
    )

    result = nli_critic.run(_sample_base(), tailored, router)
    assert result.unsupported_count == 1
    # Crucial context isolation check: NLI Critic NEVER sees ParsedJD
    payload_sent = router.calls[0]["user_payload"]
    assert "parsed_jd" not in payload_sent
    assert "raw_jd_text" not in payload_sent
    assert "Large Language Model Architect" not in payload_sent


def test_study_planner_builds_roadmap_and_to_learn_items():
    plan = StudyPlan(
        target_role="Large Language Model Architect",
        mode="hypothetical",
        estimated_total_hours=0.0,
        shortlist_boost_summary="Added distributed vLLM serving and TensorFlow familiarity to cover JD Tier-1/2 gaps.",
        hypothetical_deltas=[
            HypotheticalDelta(
                target_type="bullet",
                location="exp_01 / b1",
                added_or_upgraded_claim="Deployed vLLM PagedAttention serving layer.",
                gap_addressed="Large Language Models",
                rationale="Demonstrates production LLM inference architecture.",
            )
        ],
        study_items=[
            StudyPlanItem(
                id="",
                topic="vLLM & PagedAttention Inference",
                category="architecture_system",
                priority="high",
                estimated_hours=4.5,
                resume_claim_to_defend="Deployed vLLM PagedAttention serving layer.",
                where_it_appears="Experience · exp_01 / b1",
                subtopics_to_study=["KV cache fragmentation", "Continuous batching"],
                hands_on_exercise="Serve a 7B quantized model locally with vLLM and benchmark TTFT.",
                likely_interview_questions=["How does PagedAttention reduce KV-cache memory waste?"],
                recommended_resources=["vLLM official docs"],
            ),
            StudyPlanItem(
                id="",
                topic="TensorFlow Keras Migration Basics",
                category="tool_framework",
                priority="medium",
                estimated_hours=2.0,
                resume_claim_to_defend="Cross-framework PyTorch and TensorFlow workflows.",
                where_it_appears="Skills · ML Frameworks",
                subtopics_to_study=["tf.function graph tracing"],
                hands_on_exercise="Port one PyTorch MLP training loop to TensorFlow.",
                likely_interview_questions=["How does TensorFlow graph execution differ from eager PyTorch?"],
            ),
        ],
    )
    router = MockLLMRouter([plan.model_dump_json()])
    tailored = TailoredResume(
        experience_entries=[
            TailoredEntry(
                source_experience_id="exp_01",
                organization="Mahindra AI",
                role_title="ML Engineer",
                date_range="2022-01 - 2024-06",
                bullets=[
                    TailoredBullet(
                        bullet_id="b1",
                        source_experience_id="exp_01",
                        text="Deployed vLLM PagedAttention serving layer.",
                        is_hypothetical=True,
                        hypothetical_additions=["vLLM", "PagedAttention"],
                    )
                ],
            )
        ],
    )
    critic = CriticReport(
        audits=[
            ClaimAudit(
                target_type="bullet",
                bullet_id="b1",
                source_experience_id="exp_01",
                claim_text="Deployed vLLM PagedAttention serving layer.",
                verdict="UNSUPPORTED",
                reasoning="vLLM not in BaseExperience.",
                flagged_phrase="vLLM",
            )
        ],
        unsupported_count=1,
        stretched_count=0,
    )

    out = study_planner.run(
        base=_sample_base(),
        tailored=tailored,
        jd=_sample_jd(),
        router=router,
        critic=critic,
        mode="hypothetical",
    )
    assert out.estimated_total_hours == 6.5
    assert [i.id for i in out.study_items] == ["study_01", "study_02"]
    queue_items = study_planner.study_plan_to_to_learn_items(out)
    assert len(queue_items) == 2
    assert queue_items[0].source == "hypothetical_addition"
    assert queue_items[0].estimated_hours == 4.5
