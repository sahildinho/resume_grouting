"""API endpoint tests using FastAPI TestClient and zero-DB JSON session store."""

from pathlib import Path

from fastapi.testclient import TestClient

from api.app import create_app
from tests.test_orchestrator import (
    ScriptedRouter,
    TEMPLATE_TEX,
    _ats_eval_json,
    _base_exp,
    _critic_report,
    _hypothetical_tailored,
    _parsed_jd,
    _sample_study_plan,
    _tailored,
)


def test_full_api_session_lifecycle(tmp_path: Path):
    router = ScriptedRouter(
        {
            "ParsedJD": [_parsed_jd().model_dump_json()],
            "TailoredResume": [_tailored().model_dump_json()],
            "_LLMATSEval": [_ats_eval_json()],
            "CriticReport": [_critic_report(unsupported=0).model_dump_json()],
        }
    )
    app = create_app(runs_dir=tmp_path / "runs", default_router=router)
    client = TestClient(app)

    assert client.get("/health").json() == {"status": "ok"}

    # 1. Create session (Stage 1 + jd_profiler)
    resp = client.post(
        "/sessions",
        files={"tex_template": ("template.tex", TEMPLATE_TEX.encode("utf-8"), "application/x-tex")},
        data={
            "jd_text": "LLM Architect requiring Python and LLMs.",
            "base_experience_json": _base_exp().model_dump_json(),
        },
    )
    assert resp.status_code == 200, resp.text
    created = resp.json()
    session_id = created["session_id"]
    assert created["status"] == "READY"

    # 2. List & get session
    assert session_id in client.get("/sessions").json()["sessions"]
    assert client.get(f"/sessions/{session_id}").status_code == 200

    # 3. Run iteration (Stage 2 + parallel Stage 3 & 4a)
    run_resp = client.post(f"/sessions/{session_id}/run")
    assert run_resp.status_code == 200, run_resp.text
    run_data = run_resp.json()
    assert run_data["status"] == "AWAITING_HITL"
    assert run_data["ats_scorecard"]["overall_score"] > 0

    # 4. Approve via HITL & download exported .tex and ToLearnQueue.json
    hitl_resp = client.post(
        f"/sessions/{session_id}/hitl",
        json={"action": "APPROVE"},
    )
    assert hitl_resp.status_code == 200, hitl_resp.text
    assert hitl_resp.json()["approved"] is True

    tex_dl = client.get(f"/sessions/{session_id}/artifacts/tailored_resume.tex")
    assert tex_dl.status_code == 200
    assert "Sahil Choudhari" in tex_dl.text

    queue_dl = client.get(f"/sessions/{session_id}/artifacts/ToLearnQueue.json")
    assert queue_dl.status_code == 200
    assert queue_dl.json() == []


def test_api_sse_stream_endpoint(tmp_path: Path):
    router = ScriptedRouter(
        {
            "ParsedJD": [_parsed_jd().model_dump_json()],
            "TailoredResume": [_tailored().model_dump_json()],
            "_LLMATSEval": [_ats_eval_json()],
            "CriticReport": [_critic_report(unsupported=0).model_dump_json()],
        }
    )
    app = create_app(runs_dir=tmp_path / "runs", default_router=router)
    client = TestClient(app)

    created = client.post(
        "/sessions",
        files={"tex_template": ("template.tex", TEMPLATE_TEX.encode("utf-8"), "application/x-tex")},
        data={
            "jd_text": "LLM Architect",
            "base_experience_json": _base_exp().model_dump_json(),
        },
    ).json()
    session_id = created["session_id"]

    stream_resp = client.get(f"/sessions/{session_id}/stream")
    assert stream_resp.status_code == 200
    body = stream_resp.text
    assert "event: stage_started" in body
    assert "event: paused_for_hitl" in body
    assert "event: state" in body


def test_api_rejects_invalid_tex_template(tmp_path: Path):
    app = create_app(runs_dir=tmp_path / "runs", default_router=ScriptedRouter({}))
    client = TestClient(app)

    resp = client.post(
        "/sessions",
        files={"tex_template": ("bad.txt", b"not a tex file", "text/plain")},
        data={
            "jd_text": "LLM Architect",
            "base_experience_json": _base_exp().model_dump_json(),
        },
    )
    assert resp.status_code == 400
    assert "must be a .tex file" in resp.json()["detail"]


def test_api_web_ui_hypothetical_mode_and_study_endpoints(tmp_path: Path):
    router = ScriptedRouter(
        {
            "ParsedJD": [_parsed_jd().model_dump_json()],
            "TailoredResume": [_hypothetical_tailored().model_dump_json()],
            "_LLMATSEval": [_ats_eval_json()],
            "CriticReport": [_critic_report(unsupported=1).model_dump_json()],
            "StudyPlan": [_sample_study_plan().model_dump_json(), _sample_study_plan().model_dump_json()],
        }
    )
    app = create_app(runs_dir=tmp_path / "runs", default_router=router)
    client = TestClient(app)

    # Web UI & metadata endpoints
    ui_resp = client.get("/")
    assert ui_resp.status_code == 200
    assert "Resume Copilot" in ui_resp.text
    assert client.get("/api/config").status_code == 200
    assert "samples" in client.get("/api/samples").json()

    # Create hypothetical session
    created = client.post(
        "/sessions",
        files={"tex_template": ("template.tex", TEMPLATE_TEX.encode("utf-8"), "application/x-tex")},
        data={
            "jd_text": "LLM Architect requiring vLLM.",
            "base_experience_json": _base_exp().model_dump_json(),
            "tailoring_mode": "hypothetical",
        },
    )
    assert created.status_code == 200, created.text
    sid = created.json()["session_id"]

    # Run hypothetical iteration
    run_resp = client.post(f"/sessions/{sid}/run")
    assert run_resp.status_code == 200, run_resp.text
    run_data = run_resp.json()
    assert run_data["tailoring_mode"] == "hypothetical"
    assert len(run_data["study_plan"]["study_items"]) == 1

    # Toggle studied progress
    toggle_resp = client.patch(
        f"/sessions/{sid}/study-plan/study_01",
        json={"studied": True},
    )
    assert toggle_resp.status_code == 200
    assert toggle_resp.json()["study_plan"]["study_items"][0]["studied"] is True

    # Refresh study plan on demand
    refresh_resp = client.post(f"/sessions/{sid}/study-plan")
    assert refresh_resp.status_code == 200

    # Summaries & approve & download StudyPlan.md
    summaries = client.get("/sessions/summaries").json()["sessions"]
    assert any(item["session_id"] == sid for item in summaries)

    approve_resp = client.post(f"/sessions/{sid}/hitl", json={"action": "APPROVE"})
    assert approve_resp.status_code == 200
    md_dl = client.get(f"/sessions/{sid}/artifacts/StudyPlan.md")
    assert md_dl.status_code == 200
    assert "vLLM & PagedAttention" in md_dl.text

    # Delete session
    assert client.delete(f"/sessions/{sid}").status_code == 200
    assert client.get(f"/sessions/{sid}").status_code == 404
