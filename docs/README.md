# GuideAI Documentation Index

## Reproducible Build Runbook

### Purpose
Maintain an auditable, replayable history of every change to the platform so any team can regenerate the current state from scratch. This runbook explains how to capture build actions, update evidence artifacts, and replay the Build Timeline end-to-end.

### Prerequisites
- GuideAI repository cloned and bootstrapped (see project root instructions).
- Python environment with the `guideai` CLI installed (`pip install -e .`). After installation, run `guideai --help` to confirm the console script is on your PATH.
- `pre-commit` and required hooks installed via `./scripts/install_hooks.sh`.
- Access to the ActionService (CLI, REST, or MCP) with scopes that permit `actions.create` and `actions.replay`.
- Behavior handbook handy (`AGENTS.md`) to cite applicable behaviors when logging actions.

### 1. Capture the action as soon as the work is complete
1. Run the smallest relevant validation (tests, lint, or smoke script) and keep the output handy.
2. Log the action using the CLI (preferred once available) or REST API. Example CLI invocation (shipping with Milestone 1 CLI update):

   ```bash
   guideai record-action \
     --artifact docs/README.md \
     --summary "Publish reproducible build runbook" \
     --behaviors behavior_update_docs_after_changes behavior_handbook_compliance_prompt
   ```

   - For REST, call `POST /v1/actions` using the schema in `ACTION_SERVICE_CONTRACT.md`.
   - MCP users can invoke the `actions.create` tool with the same payload.
3. Store the resulting `action_id`—it ties the work to audit logs, telemetry, and replay pipelines.

### 2. Update the Build Timeline
1. Append a new row to `BUILD_TIMELINE.md` detailing the artifact, description, and completion date.
2. Include the `action_id` (when available) or cross-link to evidence in `PRD_ALIGNMENT_LOG.md`.
3. Commit the change alongside the updated artifact so the timeline stays in sync with git history.

### 3. Sync the Progress Tracker
1. In `PROGRESS_TRACKER.md`, update the relevant milestone row (or add one) with status ✅ and the evidence reference.
2. If a new checklist item emerges, add it to `PRD_NEXT_STEPS.md` before marking the current task complete.
3. Record the update via `guideai record-action --artifact PROGRESS_TRACKER.md ...` to keep the audit trail intact.

### 4. Replay the Build Timeline (verification or bootstrap)
1. Choose a snapshot:
   - Entire history: `guideai replay --from build_timeline`
   - Specific milestone: `guideai replay --from build_timeline --milestone 0`
   - Range: `guideai replay --from build_timeline --since 2025-10-10`.
   *(Replay commands land with the Milestone 1 CLI parity work; until then, call `POST /v1/actions:replay` or trigger the `actions.replay` MCP tool.)*
2. The CLI fetches actions via ActionService and replays them in chronological order, restoring artifacts under a clean workspace or isolated branch.
3. After replay, run `pytest` and the dashboard build to confirm parity:

   ```bash
   pytest
   cd dashboard && npm run build && cd ..
   ```

4. Inspect the generated report (`.guideai/replay/report.json`) for mismatches. Investigate differences before promoting the replayed state.

### 5. Record verification evidence
1. Log a follow-up action summarizing the replay outcome with links to reports or dashboard captures.
2. Update `PRD_ALIGNMENT_LOG.md` or `BUILD_TIMELINE.md` if the replay uncovers new decisions, bugs, or documentation changes.
3. Notify stakeholders (Strategist → Teacher → Student) so the handbook and behaviors stay current.

### 6. Troubleshooting
- **Replay fails due to missing command**: Verify the referenced CLI command exists in `guideai/cli.py` and parity tests cover it (`tests/test_action_service_parity.py`).
- **Action not found**: Ensure the original work was logged; cross-check `actions.list` or the MCP `actions.search` tool.
- **Artifacts diverge**: Run the validation suite, then re-record the corrective action with an updated summary.
- **Secrets detected during replay**: Follow `SECRETS_MANAGEMENT_PLAN.md` and run `guideai scan-secrets --fail-on-findings` before re-attempting.

### 7. Key References
- `REPRODUCIBILITY_STRATEGY.md` – overarching principles and taxonomy.
- `BUILD_TIMELINE.md` – chronological artifact log consumed by the dashboard and replay flows.
- `PROGRESS_TRACKER.md` – milestone status table that surfaces in the dashboard.
- `PRD_ALIGNMENT_LOG.md` – narrative change log explaining how updates align with PRD goals.
- `ACTION_SERVICE_CONTRACT.md` – API/CLI payloads for action capture and replay.
- `docs/capability_matrix.md` – parity evidence that confirms action capture works across surfaces.
