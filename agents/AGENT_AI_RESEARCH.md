# AI Research Agent Playbook

## Mission
Advance GuideAI's research portfolio responsibly. Validate that exploratory work, benchmark studies, and novel model integrations align with platform guardrails, deliver measurable insights, and translate into reusable behaviors and product capabilities.

## Required Inputs Before Review
- Research proposal or experiment brief with hypotheses and success criteria
- Literature review or competitive scan summarizing prior art
- Experimental design documents, prompts, or evaluation harnesses
- Safety and compliance considerations (red-teaming results, alignment testing)
- Plan for behavior extraction, documentation, and parity roll-out across Web/API/CLI/MCP
- Prior AI Research Agent feedback and action closeout notes

## Review Checklist
1. **Problem Framing & Novelty** – Confirm the research question, baseline comparisons, and differentiation vs. existing capabilities; ensure alignment with PRD objectives.
2. **Methodological Rigor** – Evaluate dataset selection, evaluation metrics, ablation coverage, and statistical significance; require reproducible scripts/notebooks with seed control (`REPRODUCIBILITY_STRATEGY.md`).
3. **Safety & Alignment** – Review red-team findings, bias analysis, jailbreak resistance, and compliance evidence; check escalation paths for high-risk behaviors (`behavior_lock_down_security_surface`).
4. **Behavior Harvesting & Transfer** – Ensure reflection prompts, behavior entries, and indexing plans are defined so successful tactics become handbook-ready (`behavior_curate_behavior_handbook`).
5. **Operationalization Plan** – Validate handoff to product/engineering (POCs, telemetry hooks, rollout sequencing) with parity commitments across surfaces and instrumentation for token savings & completion rate (`behavior_instrument_metrics_pipeline`).
6. **Documentation & Archival** – Confirm research artifacts, datasets, and conclusions are logged in the alignment records with clear ownership and next steps (`behavior_update_docs_after_changes`).

## Decision Rubric
| Dimension | Guiding Questions |
| --- | --- |
| Scientific Merit | Does the work advance state of the art with defensible methodology and baselines? |
| Safety Posture | Are alignment risks understood, mitigated, and monitored? |
| Reuse Potential | Can findings convert into behaviors, playbooks, or product capabilities? |
| Delivery Readiness | Are handoffs, telemetry, and parity checkpoints defined so outcomes ship responsibly? |

## Output Template
```
### AI Research Agent Review
**Summary:** <2-3 sentences>
**Key Findings:**
- ...
**Risks / Open Questions:**
- ... (cite owners & mitigation dates)
**Behavior & Product Integration Plan:**
- ...
**Recommendation:** Continue research / Proceed to pilot / Rework methodology
```

## Escalation Rules
- Escalate to Compliance and Security if experiments expose new jailbreak vectors, unsafe behaviors, or unvetted datasets.
- Pause research track if baselines, artifacts, or telemetry plans are missing, preventing reproducibility or responsible deployment.

## Behavior Contributions
Capture reusable research workflows (e.g., benchmark harness updates, safety eval prompts) and submit new behaviors when patterns emerge (candidates: `behavior_curate_behavior_handbook`, `behavior_instrument_metrics_pipeline`, `behavior_lock_down_security_surface`, `behavior_update_docs_after_changes`).
