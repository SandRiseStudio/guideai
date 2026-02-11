# Research Evaluation Report

**Paper**: Agentic Rubrics as Contextual Verifiers for SWE Agents
**Source**: /Users/nick/guideai/Agentic Rubrics as Contextual Verifiers for SWE Agents.pdf
**Evaluated**: 2026-01-20 18:07
**Agent**: AI Research Analyst
**Model**: claude-opus-4-20250514

---

## 1. Comprehension Summary

### Core Idea
Agentic Rubrics introduce a context-grounded verification method for software engineering agents where an expert agent explores the repository to create specific rubric criteria, enabling scalable patch verification without code execution. This approach achieves 54.2% on SWE-Bench Verified, outperforming execution-based and execution-free baselines by providing interpretable, repository-specific verification signals.

### Problem Addressed
Verification of SWE agent patches is critical but faces a dilemma: execution-based methods (running tests) are environment-aware but costly and can yield sparse signals, while execution-free methods (patch classifiers, LLM judges) are lightweight but less reliable and context-specific. As SWE agents expand to open-ended tasks, verifiers need to be both scalable and codebase-specific.

### Proposed Solution
The authors propose a two-phase approach: (1) A rubric generation phase where an expert agent interacts with the repository using tools to understand the codebase and generate context-specific rubric criteria organized along four axes (File Change, Spec Alignment, Integrity, Runtime), and (2) A verification phase where candidate patches are scored against these rubrics without executing code, enabling scalable verification while maintaining repository-specific grounding.

### Key Contributions
- Introduction of Agentic Rubrics paradigm that combines repository exploration with execution-free scoring for patch verification
- Demonstration that context-grounded rubrics consistently outperform both test-based and execution-free verifiers under parallel test-time scaling
- Analysis showing rubrics surface diagnostic concerns (unnecessary edits, missing edge cases) even when tests pass
- Evidence that agentic rubric generation can be distilled into smaller open-weight models for scalable deployment

### Technical Approach
The system uses a modified SWE-Agent scaffold where a rubric agent explores the repository through file inspection, search, and shell commands to gather context. It then generates a structured rubrics.yaml file containing 16-26 criteria organized into four axes: File Change (edit scope/locality), Spec Alignment (meeting requirements), Integrity (no test weakening/cheating), and Runtime (intended behavior). Each criterion has a text description and importance weight (1-3). During verification, an LLM judge scores candidate patches against each rubric item binarily, aggregating scores as a weighted average. The approach leverages repository interaction during rubric generation to create specific, unambiguous criteria (e.g., 'Modifies KeyboardTransform class in transforms.py' rather than generic 'touches the right code path'), making subsequent scoring more reliable and consistent.

### Claimed Results

| Metric | Improvement | Conditions |
|--------|-------------|------------|
| Best@16 accuracy | 54.2% | SWE-Bench Verified with Qwen3-Coder-30B-A3B |
| Best@16 accuracy | 40.6% | SWE-Bench Verified with Qwen3-32B |
| Performance gain | +3.5 to +4.6 percentage points | Over strongest baselines in comparison set |
| Rubric-test alignment | ROC-AUC 0.886, PR-AUC 0.722 | Predicting ground-truth test pass/fail |
| High-utility rubric judgments | 78% when aligned with tests, 54% when stricter | Manual utility analysis |


### Novelty Assessment
**Score**: 7.0/10
**Rationale**: This work makes a significant advancement by introducing the concept of agentic, context-grounded rubric generation for SWE verification. While rubric-based evaluation exists, the key innovation is using repository exploration to create codebase-specific criteria that provide interpretable, execution-free verification. The approach elegantly bridges the gap between costly execution-based and unreliable execution-free methods, with strong empirical results and practical applicability.

---

## 2. Evaluation

### Scores

| Criterion | Score | Weight | Weighted |
|-----------|-------|--------|----------|
| Relevance | 8.5/10 | 0.25 | 2.12 |
| Feasibility | 7.0/10 | 0.25 | 1.75 |
| Novelty | 7.5/10 | 0.20 | 1.50 |
| ROI | 8.0/10 | 0.20 | 1.60 |
| Safety | 8.5/10 | 0.10 | 0.85 |
| **Overall** | | | **7.82/10** |

### Relevance
Agentic Rubrics directly addresses GuideAI's core mission of improving AI agent effectiveness through structured verification. The approach aligns perfectly with our behavior management philosophy - rubrics are essentially verification behaviors that can be stored, retrieved, and reused. This would enhance our existing BCI pipeline by providing context-specific validation criteria for agent outputs, particularly valuable for our Student/Teacher/Strategist roles when validating generated code or architectural decisions. The 54.2% accuracy on SWE-Bench demonstrates real-world applicability to the software engineering tasks our platform targets.

### Feasibility
Implementation is feasible given our existing architecture. We already have: 1) BehaviorService for storing/retrieving rubrics as specialized behaviors, 2) WorkflowService that could orchestrate rubric generation and verification phases, 3) MCP tools for repository interaction (similar to SWE-Agent), 4) Telemetry pipeline to track rubric effectiveness. Main effort would be: integrating repository exploration tools, implementing the rubric generation agent logic, and adding rubric-based scoring to our validation pipeline. The structured YAML format maps cleanly to our behavior schema. However, we'd need to extend our retrieval system to handle rubric-specific queries and add new MCP tools for code repository interaction.

### Novelty
While we have behavior management and validation checklists, we lack context-specific, automatically generated verification criteria. Current validation is either generic (compliance checklists) or requires manual behavior creation. Agentic Rubrics introduces automated, repository-aware criteria generation that would be genuinely new to GuideAI. The four-axis organization (File Change, Spec Alignment, Integrity, Runtime) provides a structured approach we don't currently have. This would complement our existing behaviors by adding a verification layer that adapts to each codebase rather than relying on generic patterns.

### ROI
High ROI potential: 1) Reduces manual verification effort for engineering agents, 2) Provides interpretable validation signals that align with our emphasis on explainability, 3) Rubrics become reusable assets stored as behaviors, compounding value over time, 4) Enables scaling verification without execution infrastructure (important for sandboxed environments), 5) The 54.2% accuracy suggests we could catch real issues our current approach misses. Implementation cost is moderate (2-3 weeks) but the reusable nature means ongoing value. Token savings from avoiding repeated verification logic align with our BCI goals.

### Safety
Agentic Rubrics actually enhances safety by providing structured verification without code execution, reducing attack surface. The interpretable rubric criteria align with our compliance requirements for auditability. Main safety considerations: 1) Need to sanitize repository exploration to prevent path traversal or command injection, 2) Rubric generation must be constrained to prevent overly permissive criteria, 3) Should integrate with our existing compliance checklists to ensure security requirements are included. The execution-free nature is inherently safer than running untrusted code. No significant alignment concerns as this improves verification rigor.

### ⚠️ Conflicts with Existing Approach
- **behavior_validate_code_changes**: Current behavior uses static analysis only; would need to extend to support rubric-based validation
- **behavior_run_tests**: Rubrics provide alternative to test execution; need clear guidance on when to use each approach

### Resource Assessment

| Factor | Rating | Notes |
|--------|--------|-------|
| Implementation Complexity | MEDIUM | |
| Maintenance Burden | LOW | |
| Expertise Gap | MEDIUM | |
| **Estimated Effort** | M - Requires 2-3 weeks of focused development | |

### ⚠️ Concerns
- Concern 1: Rubric quality variance - the paper acknowledges 22% of rubrics fall into low-utility modes (over-specification, redundancy). Need quality scoring and human-in-the-loop refinement.
- Concern 2: Repository exploration overhead - generating rubrics requires significant API calls to explore codebases. Need to cache rubrics and implement rate limiting.
- Concern 3: Integration with existing test infrastructure - teams may resist replacing test execution with rubric validation. Position as complementary, not replacement.

### 🚨 Risks
- Risk 1: Over-reliance on rubrics could miss runtime issues that only tests catch. Mitigation: Use rubrics for pre-screening, not final validation.
- Risk 2: Rubric generation could become a bottleneck if not properly cached and indexed. Mitigation: Store rubrics as behaviors with TTL and invalidation logic.
- Risk 3: Open-weight model distillation (mentioned in paper) requires training infrastructure we don't have. Mitigation: Start with API-based generation, consider distillation later.

### ✅ Potential Benefits
- Benefit 1: Enable verification in environments where code execution is restricted or expensive, expanding GuideAI's applicability
- Benefit 2: Provide interpretable validation signals that can be reviewed and refined by human experts, improving trust
- Benefit 3: Create a library of reusable verification behaviors specific to common frameworks and patterns
- Benefit 4: Reduce verification latency from minutes (test execution) to seconds (rubric scoring), enabling faster iteration

---

## 3. Recommendation

### Verdict: ADOPT

Score of 7.82 indicates strong potential, but the 22% low-utility rubric rate and repository exploration overhead require adaptations. The approach aligns well with GuideAI's need for interpretable, execution-free verification, but must be implemented with quality controls and caching to be production-ready.

### Implementation Roadmap

#### Affected Components
- `guideai/verification/rubric_generator.py`: New module for context-aware rubric generation with repository exploration
- `guideai/verification/rubric_scorer.py`: Scoring engine that evaluates patches against generated rubrics
- `guideai/behaviors/behavior_validate_code_changes.py`: Extend to support rubric-based validation as alternative to static analysis
- `guideai/cache/rubric_cache.py`: Caching layer for generated rubrics with TTL and invalidation logic
- `guideai/verification/quality_scorer.py`: ML-based rubric quality assessment to filter low-utility rubrics

#### Proposed Steps
1. Implement rubric generation with repository exploration using existing LLM infrastructure (M)
2. Build rubric quality scorer to detect over-specification and redundancy patterns (S)
3. Create caching layer with framework-specific rubric templates (S)
4. Integrate rubric scoring into behavior_validate_code_changes as opt-in feature (S)
5. Implement human-in-the-loop refinement UI for rubric improvement (M)
6. Create rubric library for common frameworks (Django, React, FastAPI) (M)

#### Success Criteria
- [ ] 50%+ reduction in verification time compared to test execution for supported repositories
- [ ] Less than 15% low-utility rubric generation rate after quality filtering
- [ ] 90%+ cache hit rate for common framework patterns
- [ ] Positive user feedback on rubric interpretability in 80%+ of cases

#### Estimated Effort
L - 4-6 weeks including quality controls and caching infrastructure


### Handoff

| Field | Value |
|-------|-------|
| Next Agent | architect |
| Priority | P2 |
| Blocking Dependencies | None |


---

## 4. Metadata

| Field | Value |
|-------|-------|
| Paper ID | paper_2355bb45de5c |
| Source Type | pdf |
| Word Count | 14,148 |
| Sections | 16 |
| Extraction Confidence | 100% |
| Comprehension Confidence | 95% |

---

*Report generated by GuideAI Research Service*
