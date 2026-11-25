"""Run full Phase 1 Backend API pipeline on 1 real resume and print a detailed diagnostic report."""

import json
import os
import time
from pathlib import Path

from dotenv import load_dotenv
from fastapi.testclient import TestClient

from api.app import create_app
from core.schemas import PipelineState
from tools.llm_router import LLMRouter, LLMRouterConfig


def main() -> None:
    load_dotenv()
    has_gemini = any(
        os.getenv(k) for k in ("GEMINI_API_KEY", '"GEMINI_API_KEY"', "GOOGLE_API_KEY", '"GOOGLE_API_KEY"')
    )
    provider = "gemini" if has_gemini else "claude"
    model = "gemini-3.8-flash" if provider == "gemini" else "claude-3-5-haiku-latest"

    root = Path(__file__).resolve().parent.parent
    pdf_path = root / "dataset" / "software" / "Resume_Sahil_Choudhari.pdf"
    jd_path = root / "dataset" / "software" / "JD.txt"
    tex_path = root / "dataset" / "software" / "template.tex"

    router = LLMRouter(LLMRouterConfig(provider=provider, model=model))
    app = create_app(runs_dir=root / "runs", default_router=router)
    client = TestClient(app)

    t0 = time.perf_counter()
    print(f"Creating session via POST /sessions (model={model})...")
    with pdf_path.open("rb") as f_res, tex_path.open("rb") as f_tex:
        create_resp = client.post(
            "/sessions",
            files={
                "tex_template": ("template.tex", f_tex, "application/x-tex"),
                "resume_file": (pdf_path.name, f_res, "application/pdf"),
            },
            data={"jd_text": jd_path.read_text(encoding="utf-8")},
        )
    if create_resp.status_code != 200:
        raise SystemExit(f"POST /sessions failed ({create_resp.status_code}): {create_resp.text}")

    t1 = time.perf_counter()
    created = PipelineState.model_validate(create_resp.json())
    session_id = created.session_id
    print(f"Session created: {session_id} in {t1 - t0:.2f}s")

    print(f"Running Stage 2 + parallel Stage 3 & 4a via POST /sessions/{session_id}/run...")
    run_resp = client.post(f"/sessions/{session_id}/run")
    if run_resp.status_code != 200:
        raise SystemExit(f"POST /sessions/{session_id}/run failed ({run_resp.status_code}): {run_resp.text}")

    t2 = time.perf_counter()
    state = PipelineState.model_validate(run_resp.json())
    print(f"Iteration completed in {t2 - t1:.2f}s (status={state.status})")

    report_path = root / "runs" / session_id / "e2e_report.json"
    report_path.write_text(state.model_dump_json(indent=2), encoding="utf-8")

    # Print concise structured summary to stdout
    summary = {
        "session_id": session_id,
        "status": state.status,
        "timings_sec": {"setup_and_jd": round(t1 - t0, 2), "tailor_ats_critic_parallel": round(t2 - t1, 2)},
        "base_experience": {
            "candidate_name": state.base_experience.candidate_name,
            "experiences_count": len(state.base_experience.experiences),
            "skills_count": len(state.base_experience.skills),
            "education_count": len(state.base_experience.education),
        },
        "parsed_jd": {
            "role_title": state.parsed_jd.role_title,
            "domain": state.parsed_jd.domain,
            "seniority": state.parsed_jd.seniority,
            "metric_archetypes": state.parsed_jd.metric_archetypes,
            "keywords_count": len(state.parsed_jd.keywords),
        },
        "tailored_resume": {
            "experience_entries": len(state.tailored_resume.experience_entries),
            "project_entries": len(state.tailored_resume.project_entries),
            "skills_groups": list(state.tailored_resume.skills_grouped.keys()),
            "rendered_tex_chars": len(state.tailored_resume.rendered_tex),
        },
        "ats_scorecard": {
            "overall_score": state.ats_scorecard.overall_score,
            "keyword_score": state.ats_scorecard.keyword_score,
            "hygiene_score": state.ats_scorecard.hygiene_score,
            "llm_recruiter_score": state.ats_scorecard.llm_recruiter_score,
            "tier1_coverage_pct": state.ats_scorecard.tier1_coverage_pct,
            "tier2_coverage_pct": state.ats_scorecard.tier2_coverage_pct,
            "unresolved_placeholders": state.ats_scorecard.hygiene.unresolved_placeholders,
            "warnings": state.ats_scorecard.hygiene.warnings,
            "gaps": [g.model_dump() for g in state.ats_scorecard.gaps],
        },
        "critic_report": {
            "total_audits": len(state.critic_report.audits),
            "unsupported_count": state.critic_report.unsupported_count,
            "stretched_count": state.critic_report.stretched_count,
            "flagged_items": [
                a.model_dump()
                for a in state.critic_report.audits
                if a.verdict != "SUPPORTED"
            ],
        },
        "saved_report_path": str(report_path),
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
