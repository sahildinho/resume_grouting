"""Zero-DB local JSON session store for PipelineState and exported artifacts."""

import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from core.schemas import PipelineState, StudyPlan, ToLearnItem


def render_study_plan_markdown(plan: StudyPlan) -> str:
    """Format a StudyPlan into a clean, readable Markdown checklist and interview prep sheet."""
    lines: list[str] = [
        f"# Study & Interview Prep Roadmap — {plan.target_role}",
        "",
        f"- **Mode:** `{plan.mode}`",
        f"- **Total Topics:** {len(plan.study_items)}",
        f"- **Estimated Total Prep Time:** {plan.estimated_total_hours:.1f} hours",
        "",
        "## Shortlist Strategy Summary",
        plan.shortlist_boost_summary,
        "",
    ]

    if plan.hypothetical_deltas:
        lines.append("## Resume Additions & Stretches to Own")
        lines.append("")
        for delta in plan.hypothetical_deltas:
            lines.append(
                f"- **[{delta.target_type.upper()}] {delta.location}** — Bridges `{delta.gap_addressed}`"
            )
            lines.append(f"  - *Claim:* {delta.added_or_upgraded_claim}")
            lines.append(f"  - *Why it boosts shortlisting:* {delta.rationale}")
        lines.append("")

    lines.append("## Prioritized Study Checklist")
    lines.append("")
    for idx, item in enumerate(plan.study_items, start=1):
        check = "x" if item.studied else " "
        lines.append(
            f"### {idx}. [{check}] {item.topic} (`{item.priority.upper()}` · {item.estimated_hours:.1f}h · `{item.category}`)"
        )
        lines.append(f"- **Where on Resume:** {item.where_it_appears}")
        lines.append(f"- **Claim to Defend:** \"{item.resume_claim_to_defend}\"")
        if item.subtopics_to_study:
            lines.append("- **What to Study:**")
            for sub in item.subtopics_to_study:
                lines.append(f"  - [ ] {sub}")
        lines.append(f"- **Hands-On Exercise:** {item.hands_on_exercise}")
        if item.likely_interview_questions:
            lines.append("- **Likely Interview Questions:**")
            for q in item.likely_interview_questions:
                lines.append(f"  - {q}")
        if item.recommended_resources:
            lines.append(f"- **Resources / Search Terms:** {', '.join(item.recommended_resources)}")
        lines.append("")

    return "\n".join(lines).strip() + "\n"


class SessionStore:
    """Persists PipelineState and final output artifacts under runs/<session_id>/."""

    def __init__(self, base_dir: str | Path = "runs"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def new_session_id(self) -> str:
        return uuid.uuid4().hex[:12]

    def session_dir(self, session_id: str) -> Path:
        safe_id = Path(session_id).name
        path = self.base_dir / safe_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def state_path(self, session_id: str) -> Path:
        return self.session_dir(session_id) / "state.json"

    def save_state(self, state: PipelineState) -> Path:
        if not state.session_id:
            state.session_id = self.new_session_id()
        path = self.state_path(state.session_id)
        path.write_text(state.model_dump_json(indent=2), encoding="utf-8")
        return path

    def load_state(self, session_id: str) -> PipelineState:
        safe_id = Path(session_id).name
        path = self.base_dir / safe_id / "state.json"
        if not path.exists():
            raise FileNotFoundError(f"Session '{session_id}' not found.")
        return PipelineState.model_validate_json(path.read_text(encoding="utf-8"))

    def delete_session(self, session_id: str) -> None:
        safe_id = Path(session_id).name
        path = self.base_dir / safe_id
        if not path.exists():
            raise FileNotFoundError(f"Session '{session_id}' not found.")
        shutil.rmtree(path)

    def list_sessions(self) -> list[str]:
        if not self.base_dir.exists():
            return []
        return sorted(
            p.name for p in self.base_dir.iterdir() if p.is_dir() and (p / "state.json").exists()
        )

    def list_session_summaries(self) -> list[dict[str, Any]]:
        if not self.base_dir.exists():
            return []
        summaries: list[tuple[float, dict[str, Any]]] = []
        for p in self.base_dir.iterdir():
            state_file = p / "state.json"
            if not (p.is_dir() and state_file.exists()):
                continue
            try:
                raw = json.loads(state_file.read_text(encoding="utf-8"))
                mtime = state_file.stat().st_mtime
                updated_at = datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()
                scorecard = raw.get("ats_scorecard") or {}
                critic = raw.get("critic_report") or {}
                study_plan = raw.get("study_plan") or {}
                summaries.append(
                    (
                        mtime,
                        {
                            "session_id": raw.get("session_id") or p.name,
                            "candidate_name": (raw.get("base_experience") or {}).get(
                                "candidate_name", "Candidate"
                            ),
                            "role_title": (raw.get("parsed_jd") or {}).get("role_title", "Target Role"),
                            "domain": (raw.get("parsed_jd") or {}).get("domain", "general"),
                            "status": raw.get("status", "READY"),
                            "tailoring_mode": raw.get("tailoring_mode", "grounded"),
                            "iteration": raw.get("iteration", 1),
                            "overall_score": scorecard.get("overall_score"),
                            "unsupported_count": critic.get("unsupported_count"),
                            "study_items_count": len(study_plan.get("study_items", [])),
                            "approved": bool(raw.get("approved", False)),
                            "updated_at": updated_at,
                        },
                    )
                )
            except Exception:
                continue
        summaries.sort(key=lambda pair: pair[0], reverse=True)
        return [item for _, item in summaries]

    def save_text_artifact(self, session_id: str, filename: str, content: str) -> Path:
        path = self.session_dir(session_id) / Path(filename).name
        path.write_text(content, encoding="utf-8")
        return path

    def save_to_learn_queue(self, session_id: str, items: list[ToLearnItem]) -> Path:
        payload = [item.model_dump() for item in items]
        return self.save_text_artifact(
            session_id,
            "ToLearnQueue.json",
            json.dumps(payload, indent=2, ensure_ascii=False),
        )

    def save_study_plan(self, session_id: str, plan: StudyPlan) -> dict[str, Path]:
        json_path = self.save_text_artifact(
            session_id,
            "StudyPlan.json",
            plan.model_dump_json(indent=2),
        )
        md_path = self.save_text_artifact(
            session_id,
            "StudyPlan.md",
            render_study_plan_markdown(plan),
        )
        return {"study_plan_json_path": json_path, "study_plan_md_path": md_path}

    def get_artifact_path(self, session_id: str, filename: str) -> Optional[Path]:
        safe_id = Path(session_id).name
        safe_name = Path(filename).name
        path = self.base_dir / safe_id / safe_name
        return path if path.exists() and path.is_file() else None
