"""Unit tests for tools/taxonomy_engine.py."""

from core.schemas import SkillEdge, WeightedKeyword
from tools.taxonomy_engine import (
    compute_keyword_scores,
    load_taxonomy,
    match_keywords,
)


def test_cross_domain_exact_alias_and_adjacent_matching():
    graph = load_taxonomy(
        extra_edges=[
            SkillEdge(source="vLLM", target="TensorRT-LLM", relation="adjacent_skill", domain="software")
        ]
    )
    resume_text = (
        "Deployed Kubernetes clusters on GCP. Built Finite Element Analysis and GD&T workflows. "
        "Performed Discounted Cash Flow (DCF) and Profit and Loss analysis using PyTorch and SolidWorks."
    )
    jd_keywords = [
        WeightedKeyword(term="K8s", tier="must_have", category="tool", weight=3.0),
        WeightedKeyword(term="FEA", tier="must_have", category="domain_concept", weight=2.5),
        WeightedKeyword(term="P&L", tier="must_have", category="domain_concept", weight=2.0),
        WeightedKeyword(term="TensorFlow", tier="preferred", category="tool", weight=1.5),
        WeightedKeyword(term="CATIA", tier="preferred", category="tool", weight=1.0),
        WeightedKeyword(term="Rust", tier="must_have", category="tool", weight=2.0),
    ]

    matches = match_keywords(resume_text, jd_keywords, graph)
    status_by_kw = {m.keyword: (m.status, m.matched_via) for m in matches}

    assert status_by_kw["K8s"] == ("alias_match", "Kubernetes")
    assert status_by_kw["FEA"] == ("alias_match", "Finite Element Analysis")
    assert status_by_kw["P&L"] == ("alias_match", "Profit and Loss")
    assert status_by_kw["TensorFlow"] == ("adjacent_match", "PyTorch")
    assert status_by_kw["CATIA"] == ("adjacent_match", "SolidWorks")
    assert status_by_kw["Rust"] == ("missing", None)


def test_compute_keyword_scores_deterministic():
    graph = load_taxonomy()
    jd_keywords = [
        WeightedKeyword(term="Python", tier="must_have", category="tool", weight=2.0),
        WeightedKeyword(term="K8s", tier="must_have", category="tool", weight=2.0),
        WeightedKeyword(term="TensorFlow", tier="preferred", category="tool", weight=1.0),
    ]
    text = "Proficient in Python, Kubernetes, and PyTorch."
    matches = match_keywords(text, jd_keywords, graph)
    scores = compute_keyword_scores(matches, jd_keywords)

    # Python (2.0 * 1.0) + K8s/Kubernetes (2.0 * 1.0) + TensorFlow/PyTorch (1.0 * 0.5) = 4.5 / 5.0 = 90.0
    assert scores["keyword_score"] == 90.0
    assert scores["tier1_coverage_pct"] == 100.0
    assert scores["tier2_coverage_pct"] == 50.0


def test_parenthetical_acronym_expansion_matches_alias():
    graph = load_taxonomy()
    jd_keywords = [
        WeightedKeyword(
            term="Natural Language Processing (NLP)",
            tier="must_have",
            category="domain_concept",
            weight=2.5,
        ),
        WeightedKeyword(
            term="Large Language Models (LLMs)",
            tier="must_have",
            category="domain_concept",
            weight=3.0,
        ),
    ]
    text = "Built NLP classification pipelines and deployed LLM agents."
    matches = match_keywords(text, jd_keywords, graph)
    assert matches[0].status == "exact_match"
    assert matches[0].matched_via == "NLP"
    assert matches[1].status == "alias_match"
    assert matches[1].matched_via == "LLM"
