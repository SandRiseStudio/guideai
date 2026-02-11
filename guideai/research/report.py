"""Report renderer for research evaluation results.

Generates standardized markdown reports from evaluation results.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from guideai.research_contracts import (
    ComprehensionResult,
    EvaluationResult,
    IngestedPaper,
    Recommendation,
    Verdict,
)


def render_report(
    paper: IngestedPaper,
    comprehension: ComprehensionResult,
    evaluation: EvaluationResult,
    recommendation: Recommendation,
) -> str:
    """Render a full markdown report from evaluation results.

    Args:
        paper: Ingested paper
        comprehension: Comprehension result
        evaluation: Evaluation result
        recommendation: Final recommendation

    Returns:
        Formatted markdown report
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    # Build claimed results table
    claimed_results_rows = ""
    for result in comprehension.claimed_results:
        claimed_results_rows += f"| {result.metric} | {result.improvement} | {result.conditions} |\n"
    if not claimed_results_rows:
        claimed_results_rows = "| N/A | N/A | N/A |\n"

    # Build scores table
    scores_table = f"""| Criterion | Score | Weight | Weighted |
|-----------|-------|--------|----------|
| Relevance | {evaluation.relevance_score}/10 | 0.25 | {evaluation.relevance_score * 0.25:.2f} |
| Feasibility | {evaluation.feasibility_score}/10 | 0.25 | {evaluation.feasibility_score * 0.25:.2f} |
| Novelty | {evaluation.novelty_score}/10 | 0.20 | {evaluation.novelty_score * 0.20:.2f} |
| ROI | {evaluation.roi_score}/10 | 0.20 | {evaluation.roi_score * 0.20:.2f} |
| Safety | {evaluation.safety_score}/10 | 0.10 | {evaluation.safety_score * 0.10:.2f} |
| **Overall** | | | **{evaluation.overall_score:.2f}/10** |"""

    # Build conflicts section
    if evaluation.conflicts_with_existing:
        conflicts_list = "\n".join(
            f"- **{c.behavior_name}**: {c.description}"
            for c in evaluation.conflicts_with_existing
        )
    else:
        conflicts_list = "No conflicts detected."

    # Build concerns and benefits lists
    concerns_list = "\n".join(f"- {c}" for c in evaluation.concerns) if evaluation.concerns else "None identified."
    risks_list = "\n".join(f"- {r}" for r in evaluation.risks) if evaluation.risks else "None identified."
    benefits_list = "\n".join(f"- {b}" for b in evaluation.potential_benefits) if evaluation.potential_benefits else "None identified."

    # Build key contributions list
    contributions_list = "\n".join(f"- {c}" for c in comprehension.key_contributions) if comprehension.key_contributions else "- Not extracted"

    # Build implementation roadmap section (only for ADOPT/ADAPT)
    roadmap_section = ""
    if recommendation.verdict in (Verdict.ADOPT, Verdict.ADAPT) and recommendation.implementation_roadmap:
        rm = recommendation.implementation_roadmap

        affected_components = "\n".join(
            f"- `{c.path}`: {c.what_changes}"
            for c in rm.affected_components
        ) if rm.affected_components else "- To be determined"

        proposed_steps = "\n".join(
            f"{s.order}. {s.description} ({s.effort})"
            for s in rm.proposed_steps
        ) if rm.proposed_steps else "1. To be determined"

        success_criteria = "\n".join(
            f"- [ ] {c}" for c in rm.success_criteria
        ) if rm.success_criteria else "- [ ] To be determined"

        adaptations = ""
        if recommendation.verdict == Verdict.ADAPT and rm.adaptations_needed:
            adaptations = "\n\n#### Adaptations Needed\n" + "\n".join(
                f"- {a}" for a in rm.adaptations_needed
            )

        roadmap_section = f"""
### Implementation Roadmap

#### Affected Components
{affected_components}

#### Proposed Steps
{proposed_steps}

#### Success Criteria
{success_criteria}

#### Estimated Effort
{rm.estimated_effort}
{adaptations}

### Handoff

| Field | Value |
|-------|-------|
| Next Agent | {recommendation.next_agent or 'Not specified'} |
| Priority | {recommendation.priority.value} |
| Blocking Dependencies | {', '.join(recommendation.blocking_dependencies) if recommendation.blocking_dependencies else 'None'} |
"""

    # Build full report
    report = f"""# Research Evaluation Report

**Paper**: {paper.metadata.title}
**Source**: {paper.source}
**Evaluated**: {now}
**Agent**: AI Research Analyst
**Model**: {comprehension.llm_model}

---

## 1. Comprehension Summary

### Core Idea
{comprehension.core_idea}

### Problem Addressed
{comprehension.problem_addressed}

### Proposed Solution
{comprehension.proposed_solution}

### Key Contributions
{contributions_list}

### Technical Approach
{comprehension.technical_approach}

### Claimed Results

| Metric | Improvement | Conditions |
|--------|-------------|------------|
{claimed_results_rows}

### Novelty Assessment
**Score**: {comprehension.novelty_score}/10
**Rationale**: {comprehension.novelty_rationale}

---

## 2. Evaluation

### Scores

{scores_table}

### Relevance
{evaluation.relevance_rationale}

### Feasibility
{evaluation.feasibility_rationale}

### Novelty
{evaluation.novelty_rationale}

### ROI
{evaluation.roi_rationale}

### Safety
{evaluation.safety_rationale}

### ⚠️ Conflicts with Existing Approach
{conflicts_list}

### Resource Assessment

| Factor | Rating | Notes |
|--------|--------|-------|
| Implementation Complexity | {evaluation.implementation_complexity.value} | |
| Maintenance Burden | {evaluation.maintenance_burden.value} | |
| Expertise Gap | {evaluation.expertise_gap.value} | |
| **Estimated Effort** | {evaluation.estimated_effort} | |

### ⚠️ Concerns
{concerns_list}

### 🚨 Risks
{risks_list}

### ✅ Potential Benefits
{benefits_list}

---

## 3. Recommendation

### Verdict: {recommendation.verdict.value}

{recommendation.verdict_rationale}
{roadmap_section}

---

## 4. Metadata

| Field | Value |
|-------|-------|
| Paper ID | {paper.id} |
| Source Type | {paper.source_type.value} |
| Word Count | {paper.word_count:,} |
| Sections | {len(paper.sections)} |
| Extraction Confidence | {paper.extraction_confidence:.0%} |
| Comprehension Confidence | {comprehension.comprehension_confidence:.0%} |

---

*Report generated by GuideAI Research Service*
"""

    return report
