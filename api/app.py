"""FastAPI backend for Resume Copilot with zero-DB JSON session persistence & static web UI."""

import os
import queue
import shutil
import threading
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from core import orchestrator
from core.schemas import (
    BaseExperience,
    HITLDecision,
    OrchestratorEvent,
    PipelineState,
    TailoringMode,
)
from core.session_store import SessionStore
from tools.llm_router import LLMRouter, LLMRouterConfig

ROOT_DIR = Path(__file__).resolve().parent.parent
WEB_DIR = ROOT_DIR / "web"
DATASET_DIR = ROOT_DIR / "dataset"


class StudyTogglePayload(BaseModel):
    studied: bool


def _sample_catalog() -> dict[str, dict]:
    samples: dict[str, dict] = {}
    sw_pdf = DATASET_DIR / "software" / "Resume_Sahil_Choudhari.pdf"
    sw_jd = DATASET_DIR / "software" / "JD.txt"
    sw_tex = DATASET_DIR / "software" / "template.tex"
    if sw_pdf.exists() and sw_jd.exists() and sw_tex.exists():
        samples["software_llm"] = {
            "id": "software_llm",
            "label": "Software · LLM Architect (Sahil)",
            "domain": "software",
            "resume_path": sw_pdf,
            "jd_path": sw_jd,
            "template_path": sw_tex,
            "jd_preview": sw_jd.read_text(encoding="utf-8"),
        }

    mech_pdf = DATASET_DIR / "mechanical" / "Mayur Khade Resume -9 June 2024.pdf"
    if mech_pdf.exists() and sw_tex.exists():
        mech_jd_text = (
            "Senior Mechanical Design & CAE Engineer\n"
            "Requirements:\n"
            "- Must-have: SolidWorks or CATIA, GD&T (ASME Y14.5), FEA (ANSYS Mechanical), Sheet Metal & DFM.\n"
            "- Must-have: Tolerance stack-up analysis, BOM cost optimization, root-cause failure analysis.\n"
            "- Preferred: Python scripting for CAE automation, thermal/CFD simulation, supplier PPAP qualification."
        )
        samples["mechanical_cae"] = {
            "id": "mechanical_cae",
            "label": "Mechanical · Senior Design & CAE (Mayur)",
            "domain": "mechanical",
            "resume_path": mech_pdf,
            "jd_text": mech_jd_text,
            "template_path": sw_tex,
            "jd_preview": mech_jd_text,
        }
    return samples


def create_app(
    runs_dir: str | Path = "runs",
    default_router: Optional[LLMRouter] = None,
) -> FastAPI:
    app = FastAPI(
        title="Resume Copilot API",
        version="0.2.0",
        description="Modular, strictly grounded & hypothetical AI resume tailoring, NLI verification, and study roadmap engine.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    if WEB_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")

    store = SessionStore(base_dir=runs_dir)

    def get_store() -> SessionStore:
        return store

    def _build_router(
        provider: Optional[str] = None,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
    ) -> LLMRouter:
        if default_router is not None:
            return default_router
        cfg = LLMRouterConfig()
        if provider:
            cfg.provider = provider  # type: ignore[assignment]
        if model:
            cfg.model = model
        if api_key and api_key.strip():
            cfg.api_key = api_key.strip()
        return LLMRouter(cfg)

    @app.get("/", response_class=HTMLResponse)
    def serve_ui() -> HTMLResponse:
        index_path = WEB_DIR / "index.html"
        if not index_path.exists():
            return HTMLResponse(
                "<h1>Resume Copilot API</h1><p>Frontend assets not found in web/index.html.</p>"
            )
        return HTMLResponse(index_path.read_text(encoding="utf-8"))

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/config")
    def api_config() -> dict:
        has_gemini = bool(
            os.getenv("GEMINI_API_KEY")
            or os.getenv('"GEMINI_API_KEY"')
            or os.getenv("GOOGLE_API_KEY")
            or os.getenv('"GOOGLE_API_KEY"')
        )
        has_claude = bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv('"ANTHROPIC_API_KEY"'))
        pdf_compiler = shutil.which("tectonic") or shutil.which("pdflatex")
        return {
            "has_gemini_key": has_gemini,
            "has_claude_key": has_claude,
            "default_provider": "gemini" if has_gemini or not has_claude else "claude",
            "default_models": {
                "gemini": "gemini-3.8-flash",
                "claude": "claude-3-5-haiku-latest",
                "ollama": "llama3.1",
            },
            "pdf_compiler": Path(pdf_compiler).name if pdf_compiler else None,
        }

    @app.get("/api/samples")
    def api_samples() -> dict:
        catalog = _sample_catalog()
        return {
            "samples": [
                {
                    "id": item["id"],
                    "label": item["label"],
                    "domain": item["domain"],
                    "resume_filename": item["resume_path"].name,
                    "template_filename": item["template_path"].name,
                    "jd_preview": item["jd_preview"],
                }
                for item in catalog.values()
            ],
            "default_template_available": (DATASET_DIR / "software" / "template.tex").exists(),
        }

    @app.get("/sessions")
    def list_sessions(s: SessionStore = Depends(get_store)) -> dict[str, list[str]]:
        return {"sessions": s.list_sessions()}

    @app.get("/sessions/summaries")
    def list_session_summaries(s: SessionStore = Depends(get_store)) -> dict[str, list[dict]]:
        return {"sessions": s.list_session_summaries()}

    @app.post("/sessions", response_model=PipelineState)
    async def create_session(
        tex_template: Optional[UploadFile] = File(None, description="Strictly required .tex resume template"),
        jd_text: Optional[str] = Form(None),
        jd_file: Optional[UploadFile] = File(None),
        resume_file: Optional[UploadFile] = File(None),
        resume_text: Optional[str] = Form(None),
        base_experience_json: Optional[str] = Form(None),
        sample_preset: Optional[str] = Form(None),
        use_sample_template: bool = Form(False),
        tailoring_mode: TailoringMode = Form("grounded"),
        provider: Optional[str] = Form(None),
        model: Optional[str] = Form(None),
        max_iterations: int = Form(5),
        x_api_key: Optional[str] = Header(default=None),
        s: SessionStore = Depends(get_store),
    ) -> PipelineState:
        session_id = s.new_session_id()
        s_dir = s.session_dir(session_id)

        samples = _sample_catalog()
        preset = samples.get(sample_preset) if sample_preset else None
        if sample_preset and preset is None:
            raise HTTPException(status_code=400, detail=f"Unknown sample_preset '{sample_preset}'.")

        # Save or resolve .tex template into session dir (strict gate)
        if tex_template is not None:
            tex_name = Path(tex_template.filename or "template.tex").name
            template_path = s_dir / tex_name
            template_path.write_bytes(await tex_template.read())
        elif preset is not None or use_sample_template:
            src_tpl = (preset["template_path"] if preset else DATASET_DIR / "software" / "template.tex")
            if not src_tpl.exists():
                raise HTTPException(status_code=400, detail="Default sample template.tex not found.")
            template_path = s_dir / "template.tex"
            template_path.write_bytes(src_tpl.read_bytes())
        else:
            raise HTTPException(status_code=400, detail="Provide a .tex template file.")

        # Resolve JD input (file or text/URL or preset)
        resolved_jd_input: str
        if jd_file is not None:
            jd_name = Path(jd_file.filename or "jd.txt").name
            jd_path = s_dir / jd_name
            jd_path.write_bytes(await jd_file.read())
            resolved_jd_input = str(jd_path)
        elif jd_text and jd_text.strip():
            resolved_jd_input = jd_text.strip()
        elif preset is not None:
            resolved_jd_input = preset["jd_preview"]
        else:
            raise HTTPException(status_code=400, detail="Provide either jd_text or jd_file.")

        # Resolve BaseExperience input
        parsed_base: Optional[BaseExperience] = None
        resume_path: Optional[Path] = None
        if base_experience_json and base_experience_json.strip():
            try:
                parsed_base = BaseExperience.model_validate_json(base_experience_json)
            except Exception as exc:
                raise HTTPException(status_code=400, detail=f"Invalid base_experience_json: {exc}") from exc
        elif resume_file is not None:
            r_name = Path(resume_file.filename or "resume.txt").name
            resume_path = s_dir / r_name
            resume_path.write_bytes(await resume_file.read())
        elif resume_text and resume_text.strip():
            pass
        elif preset is not None:
            src_res = preset["resume_path"]
            resume_path = s_dir / src_res.name
            resume_path.write_bytes(src_res.read_bytes())
        else:
            raise HTTPException(
                status_code=400,
                detail="Provide base_experience_json, resume_file, or resume_text.",
            )

        router = _build_router(provider=provider, model=model, api_key=x_api_key)
        try:
            state = orchestrator.init_pipeline(
                template_path=template_path,
                jd_input=resolved_jd_input,
                router=router,
                resume_path=resume_path,
                raw_resume_text=resume_text,
                base_experience=parsed_base,
                max_iterations=max_iterations,
                session_id=session_id,
                tailoring_mode=tailoring_mode,
            )
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        s.save_state(state)
        return state

    @app.get("/sessions/{session_id}", response_model=PipelineState)
    def get_session(session_id: str, s: SessionStore = Depends(get_store)) -> PipelineState:
        try:
            return s.load_state(session_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.delete("/sessions/{session_id}")
    def delete_session(session_id: str, s: SessionStore = Depends(get_store)) -> dict[str, str]:
        try:
            s.delete_session(session_id)
            return {"deleted": session_id}
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/sessions/{session_id}/run", response_model=PipelineState)
    def run_session_iteration(
        session_id: str,
        tailoring_mode: Optional[TailoringMode] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        x_api_key: Optional[str] = Header(default=None),
        s: SessionStore = Depends(get_store),
    ) -> PipelineState:
        try:
            state = s.load_state(session_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        router = _build_router(provider=provider, model=model, api_key=x_api_key)
        return orchestrator.run_iteration(
            state=state,
            router=router,
            store=s,
            auto_repair=False,
            tailoring_mode=tailoring_mode,
        )

    @app.get("/sessions/{session_id}/stream")
    def stream_session_iteration(
        session_id: str,
        tailoring_mode: Optional[TailoringMode] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        x_api_key: Optional[str] = Header(default=None),
        s: SessionStore = Depends(get_store),
    ) -> StreamingResponse:
        try:
            state = s.load_state(session_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        router = _build_router(provider=provider, model=model, api_key=x_api_key)
        event_queue: queue.Queue[Optional[str]] = queue.Queue()

        def on_event(evt: OrchestratorEvent) -> None:
            event_queue.put(f"event: {evt.event_type}\ndata: {evt.model_dump_json()}\n\n")

        def worker() -> None:
            try:
                updated = orchestrator.run_iteration(
                    state=state,
                    router=router,
                    store=s,
                    auto_repair=False,
                    on_event=on_event,
                    tailoring_mode=tailoring_mode,
                )
                event_queue.put(f"event: state\ndata: {updated.model_dump_json()}\n\n")
            except Exception as exc:
                err = OrchestratorEvent(
                    event_type="error",
                    stage="orchestrator",
                    message=str(exc),
                    iteration=state.iteration,
                )
                event_queue.put(f"event: error\ndata: {err.model_dump_json()}\n\n")
            finally:
                event_queue.put(None)

        threading.Thread(target=worker, daemon=True).start()

        def event_generator():
            while True:
                item = event_queue.get()
                if item is None:
                    break
                yield item

        return StreamingResponse(event_generator(), media_type="text/event-stream")

    @app.post("/sessions/{session_id}/study-plan", response_model=PipelineState)
    def generate_study_plan_endpoint(
        session_id: str,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        x_api_key: Optional[str] = Header(default=None),
        s: SessionStore = Depends(get_store),
    ) -> PipelineState:
        try:
            state = s.load_state(session_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        router = _build_router(provider=provider, model=model, api_key=x_api_key)
        try:
            return orchestrator.generate_study_plan(state=state, router=router, store=s)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.patch("/sessions/{session_id}/study-plan/{item_id}", response_model=PipelineState)
    def toggle_study_item_endpoint(
        session_id: str,
        item_id: str,
        payload: StudyTogglePayload,
        s: SessionStore = Depends(get_store),
    ) -> PipelineState:
        try:
            state = s.load_state(session_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        try:
            return orchestrator.toggle_study_item(
                state=state, item_id=item_id, studied=payload.studied, store=s
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/sessions/{session_id}/hitl", response_model=PipelineState)
    def hitl_action(
        session_id: str,
        decision: HITLDecision,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        x_api_key: Optional[str] = Header(default=None),
        s: SessionStore = Depends(get_store),
    ) -> PipelineState:
        try:
            state = s.load_state(session_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        router = _build_router(provider=provider, model=model, api_key=x_api_key)
        try:
            return orchestrator.apply_hitl_decision(
                state=state,
                decision=decision,
                router=router,
                store=s,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/sessions/{session_id}/artifacts/{filename}")
    def download_artifact(
        session_id: str,
        filename: str,
        s: SessionStore = Depends(get_store),
    ) -> FileResponse:
        path = s.get_artifact_path(session_id, filename)
        if path is None:
            raise HTTPException(status_code=404, detail=f"Artifact '{filename}' not found.")
        return FileResponse(path=str(path), filename=path.name)

    return app


app = create_app()
