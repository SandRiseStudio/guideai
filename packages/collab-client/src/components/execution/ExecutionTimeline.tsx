import React, { useEffect, useMemo, useState } from 'react';
import type { ExecutionStep } from '../../types.js';
import { ensureExecutionStyles } from './executionStyles.js';
import { formatDuration, formatPhaseLabel, formatTimestamp } from './executionUtils.js';

const STEP_LABELS: Record<string, string> = {
  phase_start: 'Phase start',
  phase_end: 'Phase end',
  llm_request: 'LLM request',
  llm_response: 'LLM response',
  tool_call: 'Tool call',
  tool_result: 'Tool result',
  clarification_sent: 'Clarification sent',
  clarification_received: 'Clarification received',
  file_change: 'File change',
  pr_created: 'PR created',
  error: 'Error',
  gate_waiting: 'Gate waiting',
  gate_approved: 'Gate approved',
  model_switch: 'Model switch',
};

function formatStepLabel(stepType: string): string {
  if (!stepType) return 'Step';
  return STEP_LABELS[stepType] ?? stepType.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

interface PhaseGroup {
  phase: string;
  steps: ExecutionStep[];
}

export interface ExecutionTimelineProps {
  steps?: ExecutionStep[];
  activePhase?: string | null;
  isLoading?: boolean;
  emptyLabel?: string;
  className?: string;
}

export function ExecutionTimeline({
  steps = [],
  activePhase,
  isLoading = false,
  emptyLabel = 'No execution steps yet.',
  className,
}: ExecutionTimelineProps): React.JSX.Element {
  useEffect(() => {
    ensureExecutionStyles();
  }, []);

  const phases = useMemo<PhaseGroup[]>(() => {
    const order: string[] = [];
    const buckets = new Map<string, ExecutionStep[]>();
    steps.forEach((step) => {
      const phase = step.phase || 'Unknown';
      if (!buckets.has(phase)) {
        buckets.set(phase, []);
        order.push(phase);
      }
      buckets.get(phase)?.push(step);
    });
    return order.map((phase) => ({ phase, steps: buckets.get(phase) ?? [] }));
  }, [steps]);

  const phaseOptions = useMemo(() => ['all', ...new Set(phases.map((group) => group.phase))], [phases]);
  const stepTypeOptions = useMemo(() => {
    const unique = new Set(steps.map((step) => step.stepType).filter(Boolean));
    return ['all', ...Array.from(unique)];
  }, [steps]);

  const [phaseFilter, setPhaseFilter] = useState('all');
  const [stepTypeFilter, setStepTypeFilter] = useState('all');
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});

  const filteredPhases = useMemo(() => {
    return phases
      .filter((group) => phaseFilter === 'all' || group.phase === phaseFilter)
      .map((group) => ({
        ...group,
        steps: group.steps.filter(
          (step) => stepTypeFilter === 'all' || step.stepType === stepTypeFilter
        ),
      }))
      .filter((group) => group.steps.length > 0);
  }, [phaseFilter, phases, stepTypeFilter]);

  const togglePhase = (phase: string) => {
    setCollapsed((prev) => ({
      ...prev,
      [phase]: !prev[phase],
    }));
  };

  if (isLoading) {
    return (
      <div className={`ga-exec-panel ${className ?? ''}`.trim()} aria-label="Loading execution timeline">
        <div className="ga-exec-empty">Loading execution timeline...</div>
      </div>
    );
  }

  if (!steps.length) {
    return (
      <div className={`ga-exec-panel ${className ?? ''}`.trim()} aria-label="Execution timeline">
        <div className="ga-exec-empty">{emptyLabel}</div>
      </div>
    );
  }

  return (
    <div className={`ga-exec-timeline ${className ?? ''}`.trim()}>
      <div className="ga-exec-filter-row">
        <select
          className="ga-exec-filter-select"
          value={phaseFilter}
          onChange={(event) => setPhaseFilter(event.target.value)}
          aria-label="Filter by phase"
        >
          {phaseOptions.map((phase) => (
            <option key={phase} value={phase}>
              {phase === 'all' ? 'All phases' : formatPhaseLabel(phase)}
            </option>
          ))}
        </select>
        <select
          className="ga-exec-filter-select"
          value={stepTypeFilter}
          onChange={(event) => setStepTypeFilter(event.target.value)}
          aria-label="Filter by step type"
        >
          {stepTypeOptions.map((stepType) => (
            <option key={stepType} value={stepType}>
              {stepType === 'all' ? 'All step types' : formatStepLabel(stepType)}
            </option>
          ))}
        </select>
      </div>

      {filteredPhases.map((group) => {
        const isCollapsed = collapsed[group.phase] && group.phase !== activePhase;
        const phaseId = `phase-${group.phase.replace(/[^a-z0-9-]/gi, '-')}`;
        return (
          <div key={group.phase} className="ga-exec-phase-group">
            <button
              type="button"
              className="ga-exec-phase-header"
              onClick={() => togglePhase(group.phase)}
              aria-expanded={!isCollapsed}
              aria-controls={phaseId}
            >
              <span className="ga-exec-phase-title">{formatPhaseLabel(group.phase)}</span>
              <span className="ga-exec-phase-meta">
                {group.steps.length} steps
                {group.phase === activePhase ? ' (active)' : ''}
              </span>
            </button>
            {!isCollapsed && (
              <div id={phaseId} className="ga-exec-step-list">
                {group.steps.map((step) => (
                  <div key={step.stepId} className="ga-exec-step" data-step-type={step.stepType}>
                    <span className="ga-exec-step-dot" aria-hidden="true" />
                    <div className="ga-exec-step-card">
                      <div className="ga-exec-step-header">
                        <span className="ga-exec-step-type">{formatStepLabel(step.stepType)}</span>
                        <span className="ga-exec-step-time">
                          {formatTimestamp(step.startedAt)}
                          {formatDuration(step.startedAt, step.completedAt)
                            ? ` · ${formatDuration(step.startedAt, step.completedAt)}`
                            : ''}
                        </span>
                      </div>
                      <div className="ga-exec-step-meta">
                        <span>Input {step.inputTokens ?? 0} tokens</span>
                        <span>Output {step.outputTokens ?? 0} tokens</span>
                        <span>Tool calls {step.toolCalls ?? 0}</span>
                      </div>
                      {step.contentPreview && (
                        <div className="ga-exec-step-preview">{step.contentPreview}</div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
