"""Research evaluation pipeline for GuideAI.

This module provides a standardized pipeline for evaluating AI research papers
and articles for potential integration into GuideAI.

Pipeline Phases:
1. Ingest: Accept research from URL, markdown, PDF
2. Comprehend: LLM-driven deep analysis
3. Evaluate: Assess fit, feasibility, and value
4. Recommend: Generate verdict and implementation roadmap

Usage:
    from guideai.research import ResearchService

    service = ResearchService()
    result = await service.evaluate_paper(
        EvaluatePaperRequest(source="path/to/paper.md")
    )
    print(result.recommendation.verdict)
"""

from guideai.research.prompts import (
    COMPREHENSION_SYSTEM_PROMPT,
    COMPREHENSION_USER_PROMPT,
    EVALUATION_SYSTEM_PROMPT,
    EVALUATION_USER_PROMPT,
    RECOMMENDATION_SYSTEM_PROMPT,
    RECOMMENDATION_USER_PROMPT,
    format_comprehension_prompt,
    format_evaluation_prompt,
    format_recommendation_prompt,
)
from guideai.research.codebase_analyzer import (
    CodebaseAnalyzer,
    CodebaseSnapshot,
    get_codebase_context,
    TOKEN_BUDGETS,
)

__all__ = [
    # Prompts
    "COMPREHENSION_SYSTEM_PROMPT",
    "COMPREHENSION_USER_PROMPT",
    "EVALUATION_SYSTEM_PROMPT",
    "EVALUATION_USER_PROMPT",
    "RECOMMENDATION_SYSTEM_PROMPT",
    "RECOMMENDATION_USER_PROMPT",
    "format_comprehension_prompt",
    "format_evaluation_prompt",
    "format_recommendation_prompt",
    # Codebase Analysis
    "CodebaseAnalyzer",
    "CodebaseSnapshot",
    "get_codebase_context",
    "TOKEN_BUDGETS",
]
