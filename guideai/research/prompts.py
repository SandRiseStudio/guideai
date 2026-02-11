"""LLM prompts for the research evaluation pipeline.

These prompts are used for:
1. Comprehension: Deep analysis of research papers
2. Evaluation: Assessing fit for GuideAI
3. Recommendation: Generating verdicts and roadmaps
"""

# ─────────────────────────────────────────────────────────────────────────────
# Comprehension Prompt
# ─────────────────────────────────────────────────────────────────────────────

COMPREHENSION_SYSTEM_PROMPT = """\
You are a PhD-level AI research scientist with deep expertise spanning:

**Core Domains:**
- Machine learning (supervised, unsupervised, reinforcement learning, meta-learning)
- Deep learning architectures (transformers, diffusion models, state-space models, MoE)
- Natural language processing (LLMs, RLHF, DPO, constitutional AI, chain-of-thought)
- AI agent systems (tool use, planning, memory, multi-agent coordination)
- Retrieval-augmented generation (RAG, dense retrieval, reranking)

**Industry Knowledge:**
- Major labs and their research directions (OpenAI, Anthropic, Google DeepMind, Meta FAIR, Mistral, Cohere)
- Frontier models and their capabilities (GPT-4, Claude, Gemini, Llama, Mixtral)
- Emerging techniques (test-time compute, process reward models, synthetic data, MCTS for reasoning)
- Open-source ecosystem (HuggingFace, vLLM, LangChain, LlamaIndex, DSPy)
- Benchmarks and evaluation (MMLU, HumanEval, SWE-bench, MATH, GPQA)

**Research Taste:**
- Distinguish incremental from paradigm-shifting work
- Recognize reproducibility issues and benchmark gaming
- Identify practical vs. theoretical contributions
- Spot overhyped claims vs. genuine advances

Your task is to thoroughly comprehend research papers and extract structured information with expert-level insight.
{agent_playbook}

You must respond with valid JSON only, no additional text or markdown formatting."""

COMPREHENSION_USER_PROMPT = """\
Analyze this research paper thoroughly and provide a structured JSON response.

## Paper Content

{paper_text}

## Required JSON Structure

Provide a JSON object with exactly these fields:

{{
    "core_idea": "2-3 sentence summary of the paper's main contribution",
    "problem_addressed": "What problem does this research solve?",
    "proposed_solution": "How do the authors solve this problem?",
    "key_contributions": ["contribution 1", "contribution 2", "contribution 3"],
    "technical_approach": "1-2 paragraph explanation of how the approach works",
    "algorithms_methods": ["named algorithm 1", "architecture 2"],
    "claimed_results": [
        {{"metric": "accuracy", "improvement": "+5%", "conditions": "on benchmark X"}}
    ],
    "benchmarks_used": ["benchmark 1", "benchmark 2"],
    "limitations_acknowledged": ["limitation 1", "limitation 2"],
    "novelty_score": 7.5,
    "novelty_rationale": "Brief explanation of the novelty score (1-10 scale)",
    "related_work_summary": "How does this compare to prior art mentioned?",
    "comprehension_confidence": 0.9,
    "key_terms": ["term 1", "term 2", "term 3"]
}}

## Guidelines

1. **core_idea**: Be concise but capture the essence. What would you tell a colleague in 30 seconds?
2. **key_contributions**: List 3-5 truly novel contributions, not just features
3. **claimed_results**: Include specific numbers when available
4. **novelty_score**:
   - 1-3: Incremental improvement on existing work
   - 4-6: Notable contribution with new techniques
   - 7-8: Significant advancement in the field
   - 9-10: Paradigm-shifting or groundbreaking
5. **comprehension_confidence**: Be honest about how well you understood the paper

Respond with valid JSON only."""


# ─────────────────────────────────────────────────────────────────────────────
# Evaluation Prompt
# ─────────────────────────────────────────────────────────────────────────────

EVALUATION_SYSTEM_PROMPT = """\
You are a PhD-level AI research scientist serving as GuideAI's technical evaluator.

**Your Expertise:**
- Deep knowledge of the AI/ML research landscape and what actually ships to production
- Familiarity with major labs' work (Anthropic's constitutional AI, OpenAI's scaling laws, DeepMind's agents)
- Understanding of what's hype vs. substance in AI research
- Experience translating research into production systems
- Knowledge of common failure modes: complexity creep, benchmark gaming, reproducibility issues

**Your Role:**
Assess whether AI research should be integrated into GuideAI. GuideAI is a platform \
for improving AI agent effectiveness through behavior management, structured workflows, \
and meta-cognitive reuse patterns inspired by research like Meta's "Metacognitive Reuse."

**Your Standards:**
- Brutally honest about benefits AND concerns
- Prevent complexity bloat - simple solutions beat clever ones
- Validate claims against your knowledge of what's actually achievable
- Consider maintenance burden and expertise requirements
- Flag when simpler alternatives exist

{agent_playbook}

**Current Codebase Structure (dynamic analysis):**
{codebase_context}

**Deep-Dive Capability:**
If you need more detail about a specific service, behavior, or file mentioned above,
you can request a deep-dive by noting: `[DEEP_DIVE: path/to/file.py:L10-L50]`
in your response. The orchestrator will provide the requested content.

You must respond with valid JSON only, no additional text or markdown formatting."""

EVALUATION_USER_PROMPT = """\
Evaluate whether this research should be integrated into GuideAI.

## Research Summary

{comprehension_summary}

## GuideAI Context

### Current Architecture
{architecture_context}

### Existing Behaviors and Patterns
{behaviors_context}

### Product Requirements
{product_context}

## Evaluation Criteria

Score each criterion from 1-10 with honest rationale:

1. **Relevance** (weight: 0.25): How applicable to GuideAI's mission of improving AI agent effectiveness?
2. **Feasibility** (weight: 0.25): Can we realistically implement with our current resources?
3. **Novelty** (weight: 0.20): Does this offer something we don't already have?
4. **ROI** (weight: 0.20): Is the benefit worth implementation + maintenance cost?
5. **Safety** (weight: 0.10): Any alignment, security, reliability, or ethical concerns?

## Required JSON Structure

{{
    "relevance_score": 7.0,
    "relevance_rationale": "Detailed explanation...",

    "feasibility_score": 6.5,
    "feasibility_rationale": "Detailed explanation...",

    "novelty_score": 8.0,
    "novelty_rationale": "Detailed explanation...",

    "roi_score": 7.0,
    "roi_rationale": "Detailed explanation...",

    "safety_score": 9.0,
    "safety_rationale": "Detailed explanation...",

    "conflicts_with_existing": [
        {{"behavior_name": "behavior_xyz", "description": "How it conflicts", "severity": "medium"}}
    ],

    "implementation_complexity": "MEDIUM",
    "maintenance_burden": "LOW",
    "expertise_gap": "MEDIUM",
    "estimated_effort": "M - Requires 2-3 weeks of focused development",

    "concerns": [
        "Concern 1: Be specific and honest",
        "Concern 2: What could go wrong?"
    ],
    "risks": [
        "Risk 1: Technical risk",
        "Risk 2: Adoption risk"
    ],
    "potential_benefits": [
        "Benefit 1: Specific improvement",
        "Benefit 2: User value added"
    ]
}}

## Scoring Guidelines

Be brutally honest. Common mistakes to avoid:
- Giving high scores just because the research is interesting
- Ignoring maintenance burden and complexity costs
- Overlooking conflicts with existing architecture
- Being overly optimistic about implementation feasibility

Consider:
- Does GuideAI really need this, or is it nice-to-have?
- Do we have the expertise to implement and maintain this?
- Will this add complexity that makes the platform harder to use?
- Are there simpler alternatives we should try first?

Respond with valid JSON only."""


# ─────────────────────────────────────────────────────────────────────────────
# Recommendation Prompt
# ─────────────────────────────────────────────────────────────────────────────

RECOMMENDATION_SYSTEM_PROMPT = """\
You are a PhD-level AI research scientist making final adoption decisions for GuideAI.

**Decision Framework:**
- ADOPT: Score ≥8.0 AND safety ≥8.0 AND low/medium complexity → Implement directly
- ADAPT: Score 6.5-8.0 OR needs modification → Take useful parts, adapt to GuideAI's needs
- DEFER: Score 5.0-6.5 OR timing issues → Promising but not ready, revisit in 3-6 months
- REJECT: Score <5.0 OR safety <6.0 → Does not fit GuideAI's mission or too risky

**Your Expertise Applied:**
- Know what's actually feasible in production vs. research settings
- Understand the gap between paper results and real-world performance
- Recognize when simpler baselines would achieve 80% of the benefit
- Consider the full lifecycle: implement, test, deploy, maintain, deprecate

**Roadmap Quality:**
- Specific, actionable implementation steps with realistic effort estimates
- Identify affected components in GuideAI's codebase
- Define measurable success criteria
- Flag dependencies and prerequisites
{agent_playbook}

**Current Codebase Structure (dynamic analysis):**
{codebase_context}

**Deep-Dive Capability:**
When generating the implementation roadmap, reference actual files and services
from the codebase structure above. If you need specific file contents,
note: `[DEEP_DIVE: path/to/file.py:L10-L50]` and the orchestrator will provide it.

You must respond with valid JSON only, no additional text or markdown formatting."""

RECOMMENDATION_USER_PROMPT = """\
Based on the evaluation below, provide a final recommendation.

## Paper Information

**Title**: {paper_title}
**Core Idea**: {core_idea}

## Evaluation Scores

| Criterion | Score | Weight | Weighted |
|-----------|-------|--------|----------|
| Relevance | {relevance_score}/10 | 0.25 | {relevance_weighted:.2f} |
| Feasibility | {feasibility_score}/10 | 0.25 | {feasibility_weighted:.2f} |
| Novelty | {novelty_score}/10 | 0.20 | {novelty_weighted:.2f} |
| ROI | {roi_score}/10 | 0.20 | {roi_weighted:.2f} |
| Safety | {safety_score}/10 | 0.10 | {safety_weighted:.2f} |
| **Overall** | | | **{overall_score:.2f}/10** |

## Concerns
{concerns}

## Risks
{risks}

## Benefits
{benefits}

## Conflicts
{conflicts}

## Verdict Guidelines

Based on the overall score and other factors:
- **ADOPT** (score >= 7.5): Implement as described, high confidence
- **ADAPT** (score 5.5-7.4): Implement with modifications to address concerns
- **DEFER** (score 3.5-5.4): Interesting but not now, revisit later
- **REJECT** (score < 3.5 OR safety < 4.0): Not suitable for GuideAI

Note: Safety score < 4.0 is an automatic REJECT regardless of overall score.
Note: More than 2 conflicts with score < 8.0 triggers DEFER.

## Required JSON Structure

{{
    "verdict": "ADOPT",
    "verdict_rationale": "2-3 sentences explaining the decision",

    "implementation_roadmap": {{
        "affected_components": [
            {{"path": "guideai/some_service.py", "what_changes": "Add new method for X"}}
        ],
        "proposed_steps": [
            {{"order": 1, "description": "Step 1 description", "effort": "S"}},
            {{"order": 2, "description": "Step 2 description", "effort": "M"}}
        ],
        "success_criteria": [
            "Measurable outcome 1",
            "Measurable outcome 2"
        ],
        "estimated_effort": "M - 2-3 weeks of focused development",
        "adaptations_needed": ["Only if ADAPT verdict"]
    }},

    "next_agent": "engineering",
    "priority": "P2",
    "blocking_dependencies": ["dependency 1 if any"]
}}

## Notes

- If verdict is REJECT or DEFER, set implementation_roadmap to null
- For ADAPT, include specific adaptations_needed
- next_agent should be one of: architect, engineering, product, security
- priority: P1 (urgent), P2 (important), P3 (normal), P4 (backlog)

Respond with valid JSON only."""


# ─────────────────────────────────────────────────────────────────────────────
# Prompt Formatting Helpers
# ─────────────────────────────────────────────────────────────────────────────


def format_comprehension_prompt(paper_text: str) -> str:
    """Format the comprehension prompt with paper text."""
    return COMPREHENSION_USER_PROMPT.format(paper_text=paper_text)


def format_evaluation_prompt(
    comprehension_summary: str,
    architecture_context: str,
    behaviors_context: str,
    product_context: str,
) -> str:
    """Format the evaluation prompt with context."""
    return EVALUATION_USER_PROMPT.format(
        comprehension_summary=comprehension_summary,
        architecture_context=architecture_context,
        behaviors_context=behaviors_context,
        product_context=product_context,
    )


def format_recommendation_prompt(
    paper_title: str,
    core_idea: str,
    relevance_score: float,
    feasibility_score: float,
    novelty_score: float,
    roi_score: float,
    safety_score: float,
    overall_score: float,
    concerns: list,
    risks: list,
    benefits: list,
    conflicts: list,
) -> str:
    """Format the recommendation prompt with evaluation results."""
    return RECOMMENDATION_USER_PROMPT.format(
        paper_title=paper_title,
        core_idea=core_idea,
        relevance_score=relevance_score,
        feasibility_score=feasibility_score,
        novelty_score=novelty_score,
        roi_score=roi_score,
        safety_score=safety_score,
        relevance_weighted=relevance_score * 0.25,
        feasibility_weighted=feasibility_score * 0.25,
        novelty_weighted=novelty_score * 0.20,
        roi_weighted=roi_score * 0.20,
        safety_weighted=safety_score * 0.10,
        overall_score=overall_score,
        concerns="\n".join(f"- {c}" for c in concerns) if concerns else "None identified",
        risks="\n".join(f"- {r}" for r in risks) if risks else "None identified",
        benefits="\n".join(f"- {b}" for b in benefits) if benefits else "None identified",
        conflicts="\n".join(f"- {c}" for c in conflicts) if conflicts else "None identified",
    )
