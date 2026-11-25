"""Small live smoke test for the 5 modular agents using dataset/software fixtures."""

import os
from pathlib import Path

from dotenv import load_dotenv

from agents import ats_simulator, auto_atomizer, jd_profiler, nli_critic, resume_tailor
from core.schemas import TemplateSlot
from tools.ats_hygiene import check_tex_hygiene
from tools.document_parser import parse_jd_input
from tools.llm_router import LLMRouter, LLMRouterConfig
from tools.taxonomy_engine import load_taxonomy, match_keywords


def main() -> None:
    load_dotenv()
    has_gemini = any(
        os.getenv(k) for k in ("GEMINI_API_KEY", '"GEMINI_API_KEY"', "GOOGLE_API_KEY", '"GOOGLE_API_KEY"')
    )
    has_claude = any(os.getenv(k) for k in ("ANTHROPIC_API_KEY", '"ANTHROPIC_API_KEY"'))
    if not has_gemini and not has_claude:
        raise SystemExit(
            "Set GEMINI_API_KEY (or ANTHROPIC_API_KEY) in .env before running the live smoke test."
        )
    provider = "gemini" if has_gemini else "claude"

    model = "gemini-3.8-flash" if provider == "gemini" else "claude-3-5-haiku-latest"
    router = LLMRouter(LLMRouterConfig(provider=provider, model=model))

    root = Path(__file__).resolve().parent.parent
    raw_jd = parse_jd_input(str(root / "dataset" / "software" / "JD.txt"))
    mini_resume = (
        "Sahil Choudhari | choudhari.1@alumni.iitj.ac.in\n"
        "AI & ML Engineer (4+ years). M.Tech from IIT Jodhpur.\n"
        "Mahindra AI (2022 - Present): Built production LLM/RAG systems and YOLOv8 computer vision "
        "pipelines using Python, PyTorch, and Docker, reducing inspection latency by 32%."
    )

    print("1) Running auto_atomizer...")
    base = auto_atomizer.run(mini_resume, router)
    print(f"   Extracted {len(base.experiences)} experience(s).")

    print("2) Running jd_profiler...")
    parsed_jd = jd_profiler.run(raw_jd, router)
    print(f"   Domain={parsed_jd.domain}, Keywords={len(parsed_jd.keywords)}")

    print("3) Running resume_tailor...")
    slots = [TemplateSlot(section_name="Experience", placeholder_key="{{EXPERIENCE_BLOCK}}", max_items=2)]
    taxonomy = load_taxonomy()
    tailored = resume_tailor.run(base, parsed_jd, slots, taxonomy=taxonomy, router=router)
    print(f"   Generated {len(tailored.experience_entries)} tailored entry(ies).")

    print("4) Running ats_simulator...")
    plain_text = " ".join(b.text for e in tailored.experience_entries for b in e.bullets)
    heatmap = match_keywords(plain_text, parsed_jd.keywords, taxonomy)
    hygiene = check_tex_hygiene(r"\section{Experience}" + "\n" + plain_text)
    scorecard = ats_simulator.run(tailored, parsed_jd, heatmap, hygiene, base, router)
    print(f"   ATS overall_score={scorecard.overall_score}, tier1={scorecard.tier1_coverage_pct}%")

    print("5) Running nli_critic (blind to JD)...")
    critic = nli_critic.run(base, tailored, router)
    print(f"   Audits={len(critic.audits)}, unsupported={critic.unsupported_count}, stretched={critic.stretched_count}")


if __name__ == "__main__":
    main()
