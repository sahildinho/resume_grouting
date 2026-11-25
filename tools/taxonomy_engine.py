"""Deterministic cross-domain skill taxonomy & alias matching."""

import re
from typing import Optional

from core.schemas import KeywordMatch, SkillEdge, TaxonomyGraph, WeightedKeyword


SEED_EDGES: list[SkillEdge] = [
    # Software — exact_alias
    SkillEdge(source="K8s", target="Kubernetes", relation="exact_alias", domain="software"),
    SkillEdge(source="GCP", target="Google Cloud Platform", relation="exact_alias", domain="software"),
    SkillEdge(source="AWS", target="Amazon Web Services", relation="exact_alias", domain="software"),
    SkillEdge(source="LLMs", target="Large Language Models", relation="exact_alias", domain="software"),
    SkillEdge(source="LLM", target="Large Language Models", relation="exact_alias", domain="software"),
    SkillEdge(source="NLP", target="Natural Language Processing", relation="exact_alias", domain="software"),
    SkillEdge(source="CV", target="Computer Vision", relation="exact_alias", domain="software"),
    SkillEdge(source="RAG", target="Retrieval-Augmented Generation", relation="exact_alias", domain="software"),
    SkillEdge(source="CI/CD", target="Continuous Integration", relation="exact_alias", domain="software"),
    SkillEdge(source="JS", target="JavaScript", relation="exact_alias", domain="software"),
    SkillEdge(source="TS", target="TypeScript", relation="exact_alias", domain="software"),
    # Software — adjacent_skill
    SkillEdge(source="PyTorch", target="TensorFlow", relation="adjacent_skill", domain="software"),
    SkillEdge(source="FastAPI", target="Flask", relation="adjacent_skill", domain="software"),
    SkillEdge(source="GitHub Actions", target="Jenkins", relation="adjacent_skill", domain="software"),
    # Mechanical — exact_alias
    SkillEdge(source="FEA", target="Finite Element Analysis", relation="exact_alias", domain="mechanical"),
    SkillEdge(source="CFD", target="Computational Fluid Dynamics", relation="exact_alias", domain="mechanical"),
    SkillEdge(source="GD&T", target="Geometric Dimensioning and Tolerancing", relation="exact_alias", domain="mechanical"),
    SkillEdge(source="CAD", target="Computer-Aided Design", relation="exact_alias", domain="mechanical"),
    SkillEdge(source="BOM", target="Bill of Materials", relation="exact_alias", domain="mechanical"),
    # Mechanical — adjacent_skill
    SkillEdge(source="SolidWorks", target="CATIA", relation="adjacent_skill", domain="mechanical"),
    SkillEdge(source="SolidWorks", target="Creo", relation="adjacent_skill", domain="mechanical"),
    SkillEdge(source="ANSYS", target="Abaqus", relation="adjacent_skill", domain="mechanical"),
    # Finance — exact_alias
    SkillEdge(source="DCF", target="Discounted Cash Flow", relation="exact_alias", domain="finance"),
    SkillEdge(source="LBO", target="Leveraged Buyout", relation="exact_alias", domain="finance"),
    SkillEdge(source="P&L", target="Profit and Loss", relation="exact_alias", domain="finance"),
    SkillEdge(source="FP&A", target="Financial Planning & Analysis", relation="exact_alias", domain="finance"),
    SkillEdge(source="M&A", target="Mergers and Acquisitions", relation="exact_alias", domain="finance"),
    # Finance — adjacent_skill
    SkillEdge(source="Bloomberg Terminal", target="FactSet", relation="adjacent_skill", domain="finance"),
]


def load_taxonomy(extra_edges: Optional[list[SkillEdge]] = None) -> TaxonomyGraph:
    """Load default cross-domain seed edges plus any user-supplied edges."""
    edges = list(SEED_EDGES)
    if extra_edges:
        edges.extend(extra_edges)
    return TaxonomyGraph(edges=edges)


def _term_in_text(term: str, text: str) -> bool:
    """Case-insensitive boundary-aware search that handles punctuation like C++, C#, CI/CD, P&L."""
    cleaned = term.strip()
    if not cleaned:
        return False
    escaped = re.escape(cleaned)
    pattern = rf"(?<![A-Za-z0-9_]){escaped}(?![A-Za-z0-9_])"
    return re.search(pattern, text, flags=re.IGNORECASE) is not None


def _build_neighbor_map(graph: TaxonomyGraph) -> dict[str, list[tuple[str, str]]]:
    """Map lowercase term -> list of (neighbor_term, relation)."""
    neighbors: dict[str, list[tuple[str, str]]] = {}
    for edge in graph.edges:
        src_l = edge.source.lower()
        tgt_l = edge.target.lower()
        neighbors.setdefault(src_l, []).append((edge.target, edge.relation))
        neighbors.setdefault(tgt_l, []).append((edge.source, edge.relation))
    return neighbors


_PAREN_RE = re.compile(r"^(.+?)\s*\(([^)]+)\)\s*$")


def _expand_term_variants(term: str) -> list[str]:
    """Split parenthetical terms like 'Natural Language Processing (NLP)' into lookup variants."""
    cleaned = term.strip()
    variants = [cleaned]
    m = _PAREN_RE.match(cleaned)
    if m:
        outer, inner = m.group(1).strip(), m.group(2).strip()
        if outer:
            variants.append(outer)
        if inner:
            variants.append(inner)
    return variants


def match_keywords(
    text: str,
    jd_keywords: list[WeightedKeyword],
    graph: TaxonomyGraph,
) -> list[KeywordMatch]:
    """Match JD keywords against text using exact match, exact_alias, and adjacent_skill edges."""
    neighbors = _build_neighbor_map(graph)
    results: list[KeywordMatch] = []

    for kw in jd_keywords:
        variants = _expand_term_variants(kw.term)

        exact_hit = next((v for v in variants if _term_in_text(v, text)), None)
        if exact_hit:
            results.append(
                KeywordMatch(
                    keyword=kw.term,
                    tier=kw.tier,
                    status="exact_match",
                    matched_via=exact_hit if exact_hit != kw.term else None,
                )
            )
            continue

        matched_alias: Optional[str] = None
        matched_adjacent: Optional[str] = None
        for variant in variants:
            for neighbor, relation in neighbors.get(variant.lower(), []):
                if _term_in_text(neighbor, text):
                    if relation == "exact_alias" and matched_alias is None:
                        matched_alias = neighbor
                        break
                    if relation == "adjacent_skill" and matched_adjacent is None:
                        matched_adjacent = neighbor
            if matched_alias:
                break

        if matched_alias:
            results.append(
                KeywordMatch(
                    keyword=kw.term,
                    tier=kw.tier,
                    status="alias_match",
                    matched_via=matched_alias,
                )
            )
        elif matched_adjacent:
            results.append(
                KeywordMatch(
                    keyword=kw.term,
                    tier=kw.tier,
                    status="adjacent_match",
                    matched_via=matched_adjacent,
                )
            )
        else:
            results.append(
                KeywordMatch(keyword=kw.term, tier=kw.tier, status="missing", matched_via=None)
            )

    return results


def compute_keyword_scores(
    matches: list[KeywordMatch],
    jd_keywords: list[WeightedKeyword],
) -> dict[str, float]:
    """Compute deterministic weighted keyword_score, tier1_coverage_pct, and tier2_coverage_pct."""
    weight_by_kw = {kw.term.lower(): kw.weight for kw in jd_keywords}
    total_weight = 0.0
    earned_weight = 0.0

    tier1_total = 0
    tier1_hit = 0.0
    tier2_total = 0
    tier2_hit = 0.0

    credit_map = {
        "exact_match": 1.0,
        "alias_match": 1.0,
        "adjacent_match": 0.5,
        "missing": 0.0,
    }

    for m in matches:
        w = weight_by_kw.get(m.keyword.lower(), 1.0)
        credit = credit_map[m.status]
        total_weight += w
        earned_weight += w * credit

        if m.tier == "must_have":
            tier1_total += 1
            tier1_hit += credit
        elif m.tier == "preferred":
            tier2_total += 1
            tier2_hit += credit

    keyword_score = (earned_weight / total_weight * 100.0) if total_weight > 0 else 100.0
    tier1_pct = (tier1_hit / tier1_total * 100.0) if tier1_total > 0 else 100.0
    tier2_pct = (tier2_hit / tier2_total * 100.0) if tier2_total > 0 else 100.0

    return {
        "keyword_score": round(keyword_score, 2),
        "tier1_coverage_pct": round(tier1_pct, 2),
        "tier2_coverage_pct": round(tier2_pct, 2),
    }
