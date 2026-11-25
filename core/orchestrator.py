"""Plain Python State Machine orchestrating Stages 1-4 with parallel Stage 3 & 4a, hypothetical mode, and StudyPlan generation."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Optional

from agents import (
    ats_simulator,
    auto_atomizer,
    jd_profiler,
    nli_critic,
    resume_tailor,
    study_planner,
)
from core.schemas import (
    ATSScorecard,
    BaseExperience,
    CriticReport,
    GuardrailPolicy,
    HITLDecision,
    OrchestratorEvent,
    ParsedJD,
    PipelineState,
    RevisionFeedback,
    SkillEdge,
    TailoredResume,
    TailoringMode,
    ToLearnItem,
)
from core.session_store import SessionStore
from tools import ats_hygiene, document_parser, taxonomy_engine, tex_engine
from tools.llm_router import LLMRouter

EventCallback = Callable[[OrchestratorEvent], None]


def _emit(cb: Optional[EventCallback], event: OrchestratorEvent) -> None:
    if cb is not None:
        cb(event)


def _tailored_plain_text(tailored: TailoredResume) -> str:
    parts: list[str] = []
    if tailored.summary:
        parts.append(tailored.summary)
    for entry in tailored.experience_entries + tailored.project_entries:
        parts.append(f"{entry.role_title} {entry.organization} {entry.date_range}")
        parts.extend(b.text for b in entry.bullets)
    for entries in tailored.custom_sections.values():
        for entry in entries:
            parts.append(f"{entry.role_title} {entry.organization} {entry.date_range}")
            parts.extend(b.text for b in entry.bullets)
    for group, items in tailored.skills_grouped.items():
        parts.append(f"{group}: {', '.join(items)}")
    return "\n".join(parts)


def _merge_study_items_into_queue(
    existing: list[ToLearnItem],
    generated: list[ToLearnItem],
) -> list[ToLearnItem]:
    """Keep manual user items while refreshing auto-generated study roadmap items."""
    manual_items = [item for item in existing if item.source != "hypothetical_addition"]
    merged: list[ToLearnItem] = list(manual_items)
    seen = {item.topic_or_claim.strip().lower() for item in manual_items}
    for item in generated:
        key = item.topic_or_claim.strip().lower()
        if key not in seen:
            merged.append(item)
            seen.add(key)
    return merged


def init_pipeline(
    template_path: str | Path,
    jd_input: str,
    router: LLMRouter,
    resume_path: Optional[str | Path] = None,
    raw_resume_text: Optional[str] = None,
    base_experience: Optional[BaseExperience] = None,
    extra_skill_edges: Optional[list[SkillEdge]] = None,
    guardrails: Optional[GuardrailPolicy] = None,
    max_iterations: int = 5,
    session_id: Optional[str] = None,
    tailoring_mode: TailoringMode = "grounded",
    on_event: Optional[EventCallback] = None,
) -> PipelineState:
    """Stage 1 Setup Gate + Stage 2 Pre-Step (jd_profiler). Hard fail-fast on invalid .tex template."""
    _emit(
        on_event,
        OrchestratorEvent(
            event_type="stage_started",
            stage="stage_1_setup",
            message="Validating .tex template and preparing BaseExperience.",
        ),
    )

    # 1. Strict .tex template gate (runs first so missing/broken templates fail fast)
    template_spec = tex_engine.validate_tex_template(template_path)

    # 2. BaseExperience resolution
    if base_experience is not None:
        resolved_base = base_experience
    else:
        if resume_path is not None:
            text = document_parser.parse_resume_file(resume_path)
        elif raw_resume_text and raw_resume_text.strip():
            text = raw_resume_text.strip()
        else:
            raise ValueError("Provide either base_experience, resume_path, or raw_resume_text.")
        resolved_base = auto_atomizer.run(text, router)

    # 3. Taxonomy & Guardrails
    taxonomy = taxonomy_engine.load_taxonomy(extra_skill_edges)
    policy = guardrails or GuardrailPolicy()

    # 4. Stage 2 Pre-Step: JD Profiler
    _emit(
        on_event,
        OrchestratorEvent(
            event_type="stage_started",
            stage="stage_2_jd_profiler",
            message="Profiling Job Description into tiered keywords.",
        ),
    )
    raw_jd = document_parser.parse_jd_input(jd_input)
    parsed_jd: ParsedJD = jd_profiler.run(raw_jd, router)

    state = PipelineState(
        session_id=session_id,
        status="READY",
        tailoring_mode=tailoring_mode,
        iteration=1,
        max_iterations=max_iterations,
        base_experience=resolved_base,
        template_spec=template_spec,
        parsed_jd=parsed_jd,
        taxonomy=taxonomy,
        guardrails=policy,
    )

    _emit(
        on_event,
        OrchestratorEvent(
            event_type="setup_completed",
            stage="stage_1_setup",
            message="Setup gate and JD profiling complete.",
            data={
                "domain": parsed_jd.domain,
                "keywords_count": len(parsed_jd.keywords),
                "tailoring_mode": tailoring_mode,
            },
        ),
    )
    return state


def _evaluate_tailored_parallel(
    state: PipelineState,
    tailored: TailoredResume,
    router: LLMRouter,
    compile_dir: Optional[Path] = None,
    on_event: Optional[EventCallback] = None,
) -> tuple[ATSScorecard, CriticReport]:
    """Render .tex, run deterministic checks, then run Stage 3 (ats_simulator) & Stage 4a (blind nli_critic) in parallel."""
    tailored.rendered_tex = tex_engine.render_tex(
        state.template_spec, tailored, state.base_experience
    )

    pdf_path: Optional[Path] = None
    compile_warning: Optional[str] = None
    try:
        pdf_path = tex_engine.compile_pdf(tailored.rendered_tex, output_dir=compile_dir)
    except RuntimeError as exc:
        compile_warning = str(exc)

    plain_text = _tailored_plain_text(tailored)
    heatmap = taxonomy_engine.match_keywords(plain_text, state.parsed_jd.keywords, state.taxonomy)
    hygiene = ats_hygiene.check_tex_hygiene(
        tailored.rendered_tex,
        pdf_path=pdf_path,
        page_target=state.template_spec.page_target,
    )
    if compile_warning:
        hygiene.tex_compiles = False
        hygiene.warnings.append(compile_warning)
        hygiene.hygiene_score = max(0.0, round(hygiene.hygiene_score - 10.0, 2))

    _emit(
        on_event,
        OrchestratorEvent(
            event_type="deterministic_completed",
            stage="stage_3_deterministic",
            message="Completed LaTeX rendering, keyword heatmap, and ATS hygiene checks.",
            iteration=state.iteration,
            data={"hygiene_score": hygiene.hygiene_score},
        ),
    )

    _emit(
        on_event,
        OrchestratorEvent(
            event_type="stage_started",
            stage="stage_3_and_4a_parallel",
            message="Running Stage 3 (ATS Simulator) and Stage 4a (Blind NLI Critic) in parallel.",
            iteration=state.iteration,
        ),
    )

    with ThreadPoolExecutor(max_workers=2) as pool:
        ats_future = pool.submit(
            ats_simulator.run,
            tailored,
            state.parsed_jd,
            heatmap,
            hygiene,
            state.base_experience,
            router,
        )
        critic_future = pool.submit(
            nli_critic.run,
            state.base_experience,
            tailored,
            router,
        )
        scorecard = ats_future.result()
        critic_report = critic_future.result()

    _emit(
        on_event,
        OrchestratorEvent(
            event_type="agent_completed",
            stage="stage_3_and_4a_parallel",
            message="ATS simulation and NLI audit completed.",
            iteration=state.iteration,
            data={
                "overall_score": scorecard.overall_score,
                "unsupported_count": critic_report.unsupported_count,
                "stretched_count": critic_report.stretched_count,
            },
        ),
    )
    return scorecard, critic_report


def run_iteration(
    state: PipelineState,
    router: LLMRouter,
    store: Optional[SessionStore] = None,
    auto_repair: bool = False,
    on_event: Optional[EventCallback] = None,
    tailoring_mode: Optional[TailoringMode] = None,
) -> PipelineState:
    """Execute Stage 2 -> parallel Stage 3 & 4a -> optional StudyPlan, then pause at Stage 4b HITL.

    `auto_repair` defaults to False per project decision (surface first draft directly to HITL).
    """
    if tailoring_mode is not None and tailoring_mode != state.tailoring_mode:
        if (
            state.tailoring_mode == "grounded"
            and state.ats_scorecard is not None
            and state.baseline_ats_score is None
        ):
            state.baseline_ats_score = state.ats_scorecard.overall_score
        state.tailoring_mode = tailoring_mode
        state.approved = False

    if state.iteration > state.max_iterations:
        state.status = "MAX_ITERATIONS_REACHED"
        if store:
            store.save_state(state)
        return state

    state.status = "RUNNING"
    compile_dir = store.session_dir(state.session_id) if (store and state.session_id) else None

    mode_label = (
        "Hypothetical Shortlist Boost" if state.tailoring_mode == "hypothetical" else "Grounded"
    )
    _emit(
        on_event,
        OrchestratorEvent(
            event_type="stage_started",
            stage="stage_2_resume_tailor",
            message=f"Running Resume Tailor in {mode_label} mode (iteration {state.iteration}).",
            iteration=state.iteration,
        ),
    )

    tailored = resume_tailor.run(
        base=state.base_experience,
        jd=state.parsed_jd,
        template_slots=state.template_spec.slots,
        taxonomy=state.taxonomy,
        feedback=state.revision_feedback,
        router=router,
        mode=state.tailoring_mode,
    )
    scorecard, critic_report = _evaluate_tailored_parallel(
        state, tailored, router, compile_dir=compile_dir, on_event=on_event
    )

    # Optional bounded inner auto-repair (grounded mode only; disabled by default)
    if (
        auto_repair
        and state.tailoring_mode == "grounded"
        and critic_report.unsupported_count > 0
        and state.iteration < state.max_iterations
    ):
        rejected = [
            a.flagged_phrase or a.claim_text
            for a in critic_report.audits
            if a.verdict == "UNSUPPORTED"
        ]
        state.revision_feedback.append(
            RevisionFeedback(
                iteration=state.iteration,
                rejected_claims=rejected,
                user_instructions=["Auto-repair: remove or ground all UNSUPPORTED claims."],
            )
        )
        state.iteration += 1
        tailored = resume_tailor.run(
            base=state.base_experience,
            jd=state.parsed_jd,
            template_slots=state.template_spec.slots,
            taxonomy=state.taxonomy,
            feedback=state.revision_feedback,
            router=router,
            mode=state.tailoring_mode,
        )
        scorecard, critic_report = _evaluate_tailored_parallel(
            state, tailored, router, compile_dir=compile_dir, on_event=on_event
        )

    state.tailored_resume = tailored
    state.ats_scorecard = scorecard
    state.critic_report = critic_report

    if state.tailoring_mode == "grounded":
        state.baseline_ats_score = scorecard.overall_score
        if state.study_plan and state.study_plan.mode == "hypothetical":
            state.study_plan = None
    else:
        _emit(
            on_event,
            OrchestratorEvent(
                event_type="stage_started",
                stage="stage_4_study_planner",
                message="Building prioritized Study Roadmap for hypothetical resume additions.",
                iteration=state.iteration,
            ),
        )
        plan = study_planner.run(
            base=state.base_experience,
            tailored=tailored,
            jd=state.parsed_jd,
            router=router,
            scorecard=scorecard,
            critic=critic_report,
            to_learn_queue=state.to_learn_queue,
            mode="hypothetical",
        )
        state.study_plan = plan
        generated_queue = study_planner.study_plan_to_to_learn_items(plan)
        state.to_learn_queue = _merge_study_items_into_queue(state.to_learn_queue, generated_queue)
        if store and state.session_id:
            store.save_study_plan(state.session_id, plan)
            store.save_to_learn_queue(state.session_id, state.to_learn_queue)
        _emit(
            on_event,
            OrchestratorEvent(
                event_type="agent_completed",
                stage="stage_4_study_planner",
                message=f"Generated Study Roadmap ({len(plan.study_items)} topics, ~{plan.estimated_total_hours:.1f}h).",
                iteration=state.iteration,
                data={
                    "study_items_count": len(plan.study_items),
                    "estimated_total_hours": plan.estimated_total_hours,
                },
            ),
        )

    state.status = "AWAITING_HITL"

    if store:
        store.save_state(state)

    _emit(
        on_event,
        OrchestratorEvent(
            event_type="paused_for_hitl",
            stage="stage_4b_hitl",
            message="Draft ready for Human-in-the-Loop review.",
            iteration=state.iteration,
            data={
                "overall_score": scorecard.overall_score,
                "unsupported_count": critic_report.unsupported_count,
                "stretched_count": critic_report.stretched_count,
                "unresolved_placeholders": scorecard.hygiene.unresolved_placeholders,
                "tailoring_mode": state.tailoring_mode,
            },
        ),
    )
    return state


def generate_study_plan(
    state: PipelineState,
    router: LLMRouter,
    store: Optional[SessionStore] = None,
    on_event: Optional[EventCallback] = None,
) -> PipelineState:
    """Generate or refresh StudyPlan on demand for either Grounded or Hypothetical sessions."""
    if state.tailored_resume is None:
        raise ValueError("Cannot generate study plan before a TailoredResume exists.")

    _emit(
        on_event,
        OrchestratorEvent(
            event_type="stage_started",
            stage="stage_4_study_planner",
            message="Generating prioritized Study & Interview Prep Roadmap.",
            iteration=state.iteration,
        ),
    )
    plan = study_planner.run(
        base=state.base_experience,
        tailored=state.tailored_resume,
        jd=state.parsed_jd,
        router=router,
        scorecard=state.ats_scorecard,
        critic=state.critic_report,
        to_learn_queue=state.to_learn_queue,
        mode=state.tailoring_mode,
    )
    state.study_plan = plan
    generated_queue = study_planner.study_plan_to_to_learn_items(plan)
    state.to_learn_queue = _merge_study_items_into_queue(state.to_learn_queue, generated_queue)

    if store:
        store.save_state(state)
        if state.session_id:
            store.save_study_plan(state.session_id, plan)
            store.save_to_learn_queue(state.session_id, state.to_learn_queue)

    _emit(
        on_event,
        OrchestratorEvent(
            event_type="agent_completed",
            stage="stage_4_study_planner",
            message=f"Study Roadmap ready ({len(plan.study_items)} topics).",
            iteration=state.iteration,
            data={
                "study_items_count": len(plan.study_items),
                "estimated_total_hours": plan.estimated_total_hours,
            },
        ),
    )
    return state


def toggle_study_item(
    state: PipelineState,
    item_id: str,
    studied: bool,
    store: Optional[SessionStore] = None,
) -> PipelineState:
    """Persist studied/ready checkbox progress on a StudyPlanItem."""
    if state.study_plan is None:
        raise ValueError("No StudyPlan exists on this session.")
    found = False
    for item in state.study_plan.study_items:
        if item.id == item_id:
            item.studied = studied
            found = True
            break
    if not found:
        raise ValueError(f"Study item '{item_id}' not found.")

    if store:
        store.save_state(state)
        if state.session_id:
            store.save_study_plan(state.session_id, state.study_plan)
    return state


def apply_hitl_decision(
    state: PipelineState,
    decision: HITLDecision,
    router: Optional[LLMRouter] = None,
    store: Optional[SessionStore] = None,
    on_event: Optional[EventCallback] = None,
) -> PipelineState:
    """Apply one of the 5 Stage 4b HITL actions to PipelineState."""
    action = decision.action
    compile_dir = store.session_dir(state.session_id) if (store and state.session_id) else None

    if action == "REJECT":
        state.revision_feedback.append(
            RevisionFeedback(
                iteration=state.iteration,
                rejected_claims=decision.rejected_claims,
                user_instructions=decision.user_instructions,
                missing_tier1_to_surface=decision.missing_tier1_to_surface,
            )
        )
        state.iteration += 1
        if state.iteration > state.max_iterations:
            state.status = "MAX_ITERATIONS_REACHED"
        else:
            state.status = "READY"
        _emit(
            on_event,
            OrchestratorEvent(
                event_type="hitl_applied",
                stage="stage_4b_hitl",
                message=f"Rejected claims recorded; ready for iteration {state.iteration}.",
                iteration=state.iteration,
                data={"action": action, "status": state.status},
            ),
        )

    elif action == "ACCEPT_AND_LEARN":
        existing_topics = {item.topic_or_claim for item in state.to_learn_queue}
        for item in decision.to_learn_items:
            if item.topic_or_claim not in existing_topics:
                state.to_learn_queue.append(item)
                existing_topics.add(item.topic_or_claim)
        _emit(
            on_event,
            OrchestratorEvent(
                event_type="hitl_applied",
                stage="stage_4b_hitl",
                message=f"Logged {len(decision.to_learn_items)} item(s) to ToLearnQueue.",
                iteration=state.iteration,
                data={"action": action, "to_learn_count": len(state.to_learn_queue)},
            ),
        )

    elif action == "VERIFY_AND_PROMOTE":
        if decision.promoted_experience is not None:
            state.base_experience.experiences.append(decision.promoted_experience)
        for exp in state.base_experience.experiences:
            if exp.id in decision.promoted_metrics:
                exp.verified_metrics.extend(decision.promoted_metrics[exp.id])
        for skill in decision.promoted_skills:
            if skill not in state.base_experience.skills:
                state.base_experience.skills.append(skill)

        if decision.edited_tailored_resume is not None:
            state.tailored_resume = decision.edited_tailored_resume
        if state.tailored_resume is not None and router is not None:
            scorecard, critic_report = _evaluate_tailored_parallel(
                state, state.tailored_resume, router, compile_dir=compile_dir, on_event=on_event
            )
            state.ats_scorecard = scorecard
            state.critic_report = critic_report

        _emit(
            on_event,
            OrchestratorEvent(
                event_type="hitl_applied",
                stage="stage_4b_hitl",
                message="Promoted verified facts to BaseExperience and re-audited.",
                iteration=state.iteration,
                data={"action": action},
            ),
        )

    elif action == "DIRECT_EDIT":
        if decision.edited_tailored_resume is None:
            raise ValueError("DIRECT_EDIT requires edited_tailored_resume.")
        state.tailored_resume = decision.edited_tailored_resume
        if router is not None:
            scorecard, critic_report = _evaluate_tailored_parallel(
                state, state.tailored_resume, router, compile_dir=compile_dir, on_event=on_event
            )
            state.ats_scorecard = scorecard
            state.critic_report = critic_report
        else:
            state.tailored_resume.rendered_tex = tex_engine.render_tex(
                state.template_spec, state.tailored_resume, state.base_experience
            )
        _emit(
            on_event,
            OrchestratorEvent(
                event_type="hitl_applied",
                stage="stage_4b_hitl",
                message="Applied manual resume edits and re-validated.",
                iteration=state.iteration,
                data={"action": action},
            ),
        )

    elif action == "APPROVE":
        _enforce_exit_gate(state)
        state.approved = True
        state.status = "APPROVED"
        if store:
            export_outputs(state, store, on_event=on_event)

    if store:
        store.save_state(state)
    return state


def _enforce_exit_gate(state: PipelineState) -> None:
    if state.tailored_resume is None:
        raise ValueError("Cannot approve: no TailoredResume has been generated yet.")
    if state.critic_report is None:
        raise ValueError("Cannot approve: NLI Critic audit has not run yet.")
    if state.ats_scorecard and state.ats_scorecard.hygiene.unresolved_placeholders:
        placeholders = ", ".join(state.ats_scorecard.hygiene.unresolved_placeholders)
        raise ValueError(
            f"Exit gate blocked: unresolved metric placeholder(s) remain: {placeholders}."
        )
    if state.tailoring_mode == "grounded":
        if state.critic_report.unsupported_count > 0:
            raise ValueError(
                f"Exit gate blocked: {state.critic_report.unsupported_count} UNSUPPORTED claim(s) remain. "
                "Reject, edit, or verify/promote them first."
            )
    else:
        if state.study_plan is None:
            raise ValueError(
                "Exit gate blocked: Hypothetical mode requires a generated StudyPlan before approval."
            )


def export_outputs(
    state: PipelineState,
    store: SessionStore,
    on_event: Optional[EventCallback] = None,
) -> dict[str, str]:
    """Write tailored_resume.tex, optional tailored_resume.pdf, ToLearnQueue.json, and StudyPlan files."""
    if not state.session_id:
        state.session_id = store.new_session_id()
    if state.tailored_resume is None:
        raise ValueError("Cannot export: tailored_resume is None.")

    tex_str = state.tailored_resume.rendered_tex or tex_engine.render_tex(
        state.template_spec, state.tailored_resume, state.base_experience
    )
    state.tailored_resume.rendered_tex = tex_str

    tex_path = store.save_text_artifact(state.session_id, "tailored_resume.tex", tex_str)
    queue_path = store.save_to_learn_queue(state.session_id, state.to_learn_queue)

    outputs: dict[str, str] = {
        "tex_path": str(tex_path),
        "to_learn_queue_path": str(queue_path),
    }

    if state.study_plan is not None:
        sp_paths = store.save_study_plan(state.session_id, state.study_plan)
        outputs["study_plan_json_path"] = str(sp_paths["study_plan_json_path"])
        outputs["study_plan_md_path"] = str(sp_paths["study_plan_md_path"])

    try:
        pdf_path = tex_engine.compile_pdf(
            tex_str, output_dir=store.session_dir(state.session_id), filename="tailored_resume"
        )
        if pdf_path is not None:
            outputs["pdf_path"] = str(pdf_path)
    except RuntimeError:
        pass

    _emit(
        on_event,
        OrchestratorEvent(
            event_type="exported",
            stage="export",
            message="Exported final .tex, ToLearnQueue.json, and study artifacts.",
            iteration=state.iteration,
            data=outputs,
        ),
    )
    return outputs
