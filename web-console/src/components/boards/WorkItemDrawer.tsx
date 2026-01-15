/**
 * Work Item Drawer
 *
 * Following COLLAB_SAAS_REQUIREMENTS.md (Student):
 * - Fast, optimistic edits
 * - 60fps transforms for motion (no layout animations)
 * - Accessible keyboard interactions (Escape to close, focus-visible)
 */

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ExecutionStatusCard,
  ExecutionTimeline,
} from '@guideai/collab-client';
import {
  type BoardColumn,
  type UpdateWorkItemRequest,
  type WorkItem,
  type WorkItemComment,
  type WorkItemCommentAuthorType,
  type WorkItemPriority,
  useAssignWorkItem,
  usePostWorkItemComment,
  useUnassignWorkItem,
  useUpdateWorkItem,
  useWorkItemComments,
  useWorkItem,
} from '../../api/boards';
import {
  useCancelWorkItemExecution,
  useExecuteWorkItem,
  useExecutionSteps,
  useExecutionStream,
  useProvideClarification,
  useWorkItemExecutionStatus,
} from '../../api/executions';
import { useAuth } from '../../contexts/AuthContext';
import './WorkItemDrawer.css';

type DrawerPhase = 'entering' | 'open' | 'closing';
type SaveState = 'idle' | 'saving' | 'saved' | 'copied' | 'error';

function labelForType(itemType: WorkItem['item_type']): string {
  if (itemType === 'task') return 'Task';
  if (itemType === 'story') return 'Story';
  return 'Epic';
}

function shortId(itemId: string): string {
  return itemId.replace('task-', '#').replace('story-', '#').replace('epic-', '#');
}

function formatRelativeTime(dateString?: string | null): string {
  if (!dateString) return 'Unknown';
  const date = new Date(dateString);
  if (Number.isNaN(date.getTime())) return 'Unknown';
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffSecs = Math.floor(diffMs / 1000);
  const diffMins = Math.floor(diffSecs / 60);
  const diffHours = Math.floor(diffMins / 60);
  const diffDays = Math.floor(diffHours / 24);

  if (diffSecs < 60) return 'just now';
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays < 7) return `${diffDays}d ago`;
  return date.toLocaleDateString();
}

function normalizeLabel(input: string): string {
  return input.trim().replace(/\s+/g, '-').toLowerCase();
}

function shortenAssigneeId(id: string): string {
  if (id.length <= 8) return id;
  return id.slice(0, 8);
}

function getInitials(label: string): string {
  const parts = label.split(/\s+/).filter(Boolean);
  if (parts.length === 0) return '?';
  const first = parts[0]?.[0] ?? '';
  const second = parts[1]?.[0] ?? '';
  const initials = `${first}${second}`.toUpperCase();
  return initials || '?';
}

function toStatusLabel(status?: string): string | null {
  if (!status) return null;
  return status.toLowerCase();
}

function useDebouncedCallback(callback: () => void, delayMs: number) {
  const timerRef = useRef<number | null>(null);

  const cancel = useCallback(() => {
    if (timerRef.current == null) return;
    window.clearTimeout(timerRef.current);
    timerRef.current = null;
  }, []);

  const schedule = useCallback(() => {
    cancel();
    timerRef.current = window.setTimeout(() => {
      timerRef.current = null;
      callback();
    }, delayMs);
  }, [callback, cancel, delayMs]);

  useEffect(() => cancel, [cancel]);

  return useMemo(() => ({ schedule, cancel }), [cancel, schedule]);
}

export interface AssigneeProfile {
  id: string;
  type: 'user' | 'agent';
  label: string;
  subtitle?: string;
  status?: string;
  avatar?: string;
}

export interface WorkItemDrawerProps {
  projectId: string;
  orgId?: string | null;
  boardId: string;
  itemId: string;
  columns: BoardColumn[];
  targetPositions: Record<string, number>;
  initialItem?: WorkItem;
  assigneeIndex: Map<string, AssigneeProfile>;
  assignableHumans: AssigneeProfile[];
  assignableAgents: AssigneeProfile[];
  assignmentHint?: string;
  onMove: (itemId: string, toColumnId: string | null, position: number) => void;
  onRequestClose: () => void;
}

export function WorkItemDrawer({
  projectId,
  orgId,
  boardId,
  itemId,
  columns,
  targetPositions,
  initialItem,
  assigneeIndex,
  assignableHumans,
  assignableAgents,
  assignmentHint,
  onMove,
  onRequestClose,
}: WorkItemDrawerProps): React.JSX.Element {
  const overlayRef = useRef<HTMLDivElement | null>(null);
  const titleRef = useRef<HTMLInputElement | null>(null);
  const prevFocusRef = useRef<HTMLElement | null>(null);
  const commentEndRef = useRef<HTMLDivElement | null>(null);

  const { actor } = useAuth();

  const [phase, setPhase] = useState<DrawerPhase>('entering');
  const [saveState, setSaveState] = useState<SaveState>('idle');
  const [titleDraft, setTitleDraft] = useState(initialItem?.title ?? '');
  const [descriptionDraft, setDescriptionDraft] = useState(initialItem?.description ?? '');
  const [priorityDraft, setPriorityDraft] = useState<WorkItemPriority>(initialItem?.priority ?? 'medium');
  const [labels, setLabels] = useState<string[]>(initialItem?.labels ?? []);
  const [newLabelDraft, setNewLabelDraft] = useState('');
  const [assigneeSearch, setAssigneeSearch] = useState('');
  const [clarificationDraftsByItem, setClarificationDraftsByItem] = useState<Record<string, Record<string, string>>>({});
  const [commentDraft, setCommentDraft] = useState('');
  const [commentFilter, setCommentFilter] = useState<'all' | 'humans' | 'agents'>('all');

  const updateItem = useUpdateWorkItem(boardId);
  const assignItem = useAssignWorkItem(boardId);
  const unassignItem = useUnassignWorkItem(boardId);
  const { data: item, isLoading, isError } = useWorkItem(itemId, initialItem);
  const commentsQuery = useWorkItemComments(itemId, { limit: 200 });
  const postComment = usePostWorkItemComment(itemId);
  const executeWorkItem = useExecuteWorkItem();
  const cancelExecution = useCancelWorkItemExecution();
  const provideClarification = useProvideClarification();

  const executionStatusQuery = useWorkItemExecutionStatus(itemId, orgId, projectId);
  const executionStatus = executionStatusQuery.data ?? null;
  const executionState = executionStatus?.state ? String(executionStatus.state).toLowerCase() : null;
  const activeExecution = executionState === 'running' || executionState === 'paused' || executionState === 'pending';
  const executionStream = useExecutionStream({
    runId: executionStatus?.runId ?? null,
    orgId: orgId ?? null,
    projectId,
    enabled: Boolean(orgId && projectId),
  });
  const executionStepsQuery = useExecutionSteps(executionStatus?.runId ?? null, orgId, projectId, {
    enabled: Boolean(executionStatus?.runId),
    refetchInterval: executionStream.isConnected ? false : activeExecution ? 2000 : false,
  });
  const executionSteps = executionStepsQuery.data?.steps ?? [];

  const isOpen = phase === 'open' || phase === 'entering';
  const typeLabel = useMemo(() => (item ? labelForType(item.item_type) : 'Work item'), [item]);

  useEffect(() => {
    prevFocusRef.current = document.activeElement as HTMLElement | null;
    const id = window.requestAnimationFrame(() => setPhase('open'));
    return () => window.cancelAnimationFrame(id);
  }, [itemId]);

  useEffect(() => {
    if (!isOpen) return;
    const id = window.requestAnimationFrame(() => {
      titleRef.current?.focus();
      titleRef.current?.select();
    });
    return () => window.cancelAnimationFrame(id);
  }, [isOpen]);

  useEffect(() => {
    return () => {
      prevFocusRef.current?.focus?.();
    };
  }, []);

  useEffect(() => {
    if (!item) return;
    setTitleDraft(item.title);
    setDescriptionDraft(item.description ?? '');
    setPriorityDraft(item.priority);
    setLabels(item.labels ?? []);
    setSaveState('idle');
  }, [item?.item_id]);

  useEffect(() => {
    setAssigneeSearch('');
    setCommentDraft('');
    setCommentFilter('all');
  }, [itemId]);


  const requestClose = useCallback(() => {
    if (phase === 'closing') return;
    setPhase('closing');
    window.setTimeout(() => onRequestClose(), 260);
  }, [onRequestClose, phase]);

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        requestClose();
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [requestClose]);

  const doPatch = useCallback(
    (patch: UpdateWorkItemRequest) => {
      if (!itemId) return;
      setSaveState('saving');
      updateItem.mutate(
        { itemId, patch },
        {
          onSuccess: () => {
            setSaveState('saved');
            window.setTimeout(() => setSaveState('idle'), 1100);
          },
          onError: () => setSaveState('error'),
        }
      );
    },
    [itemId, updateItem]
  );

  const debouncedSave = useDebouncedCallback(() => {
    if (!item) return;
    const nextTitle = titleDraft.trim();
    if (!nextTitle) return;

    const patch: UpdateWorkItemRequest = {};
    if (nextTitle !== item.title) patch.title = nextTitle;
    if ((descriptionDraft ?? '') !== (item.description ?? '')) patch.description = descriptionDraft;
    if (priorityDraft !== item.priority) patch.priority = priorityDraft;
    if (JSON.stringify(labels) !== JSON.stringify(item.labels ?? [])) patch.labels = labels;

    if (Object.keys(patch).length > 0) doPatch(patch);
  }, 350);

  const handleOverlayMouseDown = useCallback(
    (e: React.MouseEvent<HTMLDivElement>) => {
      if (e.target === overlayRef.current) {
        requestClose();
      }
    },
    [requestClose]
  );

  const handleColumnChange = useCallback(
    (e: React.ChangeEvent<HTMLSelectElement>) => {
      const value = e.target.value;
      const toColumnId = value === '__none__' ? null : value;
      const position = toColumnId ? (targetPositions[toColumnId] ?? 0) : 0;
      onMove(itemId, toColumnId, position);
    },
    [itemId, onMove, targetPositions]
  );

  const handlePriorityChange = useCallback(
    (e: React.ChangeEvent<HTMLSelectElement>) => {
      const next = e.target.value as WorkItemPriority;
      setPriorityDraft(next);
      doPatch({ priority: next });
    },
    [doPatch]
  );

  const handleTitleChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      setTitleDraft(e.target.value);
      debouncedSave.schedule();
    },
    [debouncedSave]
  );

  const handleDescriptionChange = useCallback(
    (e: React.ChangeEvent<HTMLTextAreaElement>) => {
      setDescriptionDraft(e.target.value);
      debouncedSave.schedule();
    },
    [debouncedSave]
  );

  const handleLabelsRemove = useCallback(
    (label: string) => {
      setLabels((current) => {
        const next = current.filter((l) => l !== label);
        doPatch({ labels: next });
        return next;
      });
    },
    [doPatch]
  );

  const handleNewLabelCommit = useCallback(() => {
    const normalized = normalizeLabel(newLabelDraft);
    if (!normalized) return;
    if (labels.includes(normalized)) {
      setNewLabelDraft('');
      return;
    }
    const next = [...labels, normalized];
    setLabels(next);
    setNewLabelDraft('');
    doPatch({ labels: next });
  }, [doPatch, labels, newLabelDraft]);

  const handleNewLabelKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLInputElement>) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        handleNewLabelCommit();
      }
    },
    [handleNewLabelCommit]
  );

  const canCopy = typeof navigator !== 'undefined' && Boolean(navigator.clipboard);
  const itemUrl = useMemo(() => {
    return `${window.location.origin}/projects/${encodeURIComponent(projectId)}/boards/${encodeURIComponent(boardId)}/items/${encodeURIComponent(itemId)}`;
  }, [boardId, itemId, projectId]);

  const assigneeKey = item?.assignee_id && item?.assignee_type ? `${item.assignee_type}:${item.assignee_id}` : null;
  const currentAssignee = useMemo(() => {
    if (!assigneeKey) return null;
    return assigneeIndex.get(assigneeKey) ?? null;
  }, [assigneeIndex, assigneeKey]);

  const fallbackAssignee = useMemo(() => {
    if (!item?.assignee_id || !item.assignee_type || currentAssignee) return null;
    const label = item.assignee_type === 'agent'
      ? `Agent ${shortenAssigneeId(item.assignee_id)}`
      : `Member ${shortenAssigneeId(item.assignee_id)}`;
    return {
      id: item.assignee_id,
      type: item.assignee_type,
      label,
      subtitle: item.assignee_type === 'agent' ? 'Agent' : 'Human',
      avatar: getInitials(label),
    } satisfies AssigneeProfile;
  }, [currentAssignee, item?.assignee_id, item?.assignee_type]);

  const assignmentProfile = currentAssignee ?? fallbackAssignee;
  const assigneeSearchValue = assigneeSearch.trim().toLowerCase();
  const filteredHumans = useMemo(() => {
    if (!assigneeSearchValue) return assignableHumans;
    return assignableHumans.filter((profile) => {
      const haystack = `${profile.label} ${profile.subtitle ?? ''} ${profile.id}`.toLowerCase();
      return haystack.includes(assigneeSearchValue);
    });
  }, [assignableHumans, assigneeSearchValue]);

  const filteredAgents = useMemo(() => {
    if (!assigneeSearchValue) return assignableAgents;
    return assignableAgents.filter((profile) => {
      const haystack = `${profile.label} ${profile.subtitle ?? ''} ${profile.id}`.toLowerCase();
      return haystack.includes(assigneeSearchValue);
    });
  }, [assignableAgents, assigneeSearchValue]);

  const handleCopyLink = useCallback(async () => {
    if (!canCopy) return;
    try {
      await navigator.clipboard.writeText(itemUrl);
      setSaveState('copied');
      window.setTimeout(() => setSaveState('idle'), 900);
    } catch {
      setSaveState('error');
    }
  }, [canCopy, itemUrl]);

  const saveLabel = useMemo(() => {
    if (saveState === 'saving') return 'Saving…';
    if (saveState === 'saved') return 'Saved';
    if (saveState === 'copied') return 'Copied';
    if (saveState === 'error') return 'Couldn’t save';
    return '';
  }, [saveState]);

  const assignmentBusy = assignItem.isPending || unassignItem.isPending;
  const hasAgentAssignment = Boolean(item?.assignee_id && item?.assignee_type === 'agent');
  // Orphaned assignment: work item references an agent that no longer exists in the org
  const isOrphanedAssignment = hasAgentAssignment && !currentAssignee;
  const canStartExecution = hasAgentAssignment && !activeExecution && !isOrphanedAssignment;
  const canCancelExecution = Boolean(activeExecution);
  const startLabel = executionStatus?.hasExecution ? 'Run again' : 'Start execution';
  const executionHint = isOrphanedAssignment
    ? 'Assigned agent no longer exists. Please re-assign.'
    : !hasAgentAssignment
      ? 'Assign an agent to enable execution.'
      : 'Runs update in real time.';
  const clarificationDrafts = useMemo(
    () => clarificationDraftsByItem[itemId] ?? {},
    [clarificationDraftsByItem, itemId]
  );

  const clarificationRequests = useMemo(() => {
    const raw = executionStatus?.pendingClarifications ?? [];
    return raw
      .map((entry, index) => {
        if (!entry || typeof entry !== 'object') return null;
        const record = entry as Record<string, unknown>;
        const id =
          String(record.clarification_id ?? record.id ?? record.request_id ?? `clarification-${index}`);
        const prompt =
          String(record.prompt ?? record.question ?? record.message ?? record.reason ?? '');
        if (!id) return null;
        return {
          id,
          prompt: prompt || 'Clarification requested',
        };
      })
      .filter((entry): entry is { id: string; prompt: string } => Boolean(entry));
  }, [executionStatus?.pendingClarifications]);

  const commentAuthorType = useMemo<WorkItemCommentAuthorType | null>(() => {
    if (!actor?.type) return null;
    return actor.type === 'human' ? 'user' : 'agent';
  }, [actor?.type]);

  const comments = commentsQuery.data ?? [];
  const filteredComments = useMemo(() => {
    if (commentFilter === 'all') return comments;
    const target = commentFilter === 'humans' ? 'user' : 'agent';
    return comments.filter((comment) => comment.author_type === target);
  }, [commentFilter, comments]);

  const resolveCommentProfile = useCallback(
    (comment: WorkItemComment) => {
      const isYou = actor?.id === comment.author_id;
      const key = `${comment.author_type}:${comment.author_id}`;
      const profile = assigneeIndex.get(key);
      if (profile) {
        const avatarLabel = profile.label;
        return {
          label: isYou ? 'You' : profile.label,
          avatar: profile.avatar ?? getInitials(avatarLabel),
          isYou,
        };
      }
      if (isYou) {
        const avatarLabel = actor?.displayName ?? 'You';
        return {
          label: 'You',
          avatar: getInitials(avatarLabel),
          isYou,
        };
      }
      const fallbackLabel =
        comment.author_type === 'agent'
          ? `Agent ${shortenAssigneeId(comment.author_id)}`
          : `Member ${shortenAssigneeId(comment.author_id)}`;
      return {
        label: fallbackLabel,
        avatar: getInitials(fallbackLabel),
        isYou: false,
      };
    },
    [actor?.displayName, actor?.id, assigneeIndex]
  );

  const commentDraftValue = commentDraft.trim();
  const canPostComment =
    Boolean(commentDraftValue) && Boolean(actor?.id) && Boolean(commentAuthorType) && !postComment.isPending;
  const commentCountLabel = comments.length === 1 ? '1 comment' : `${comments.length} comments`;
  const commentFilterLabel =
    commentFilter === 'all'
      ? commentCountLabel
      : `${filteredComments.length} of ${commentCountLabel}`;
  const commentHint = actor?.id ? 'Cmd+Enter to send' : 'Sign in to comment.';
  const commentPlaceholder = actor?.id
    ? 'Share context for humans + agents...'
    : 'Sign in to leave a comment.';

  const handleCommentSend = useCallback(() => {
    if (!itemId || !actor?.id || !commentAuthorType || !commentDraftValue) return;
    postComment.mutate(
      {
        body: commentDraftValue,
        authorId: actor.id,
        authorType: commentAuthorType,
        metadata: { source: 'web-console' },
      },
      {
        onSuccess: () => {
          setCommentDraft('');
          window.requestAnimationFrame(() => {
            commentEndRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
          });
        },
      }
    );
  }, [actor?.id, commentAuthorType, commentDraftValue, itemId, postComment]);

  const handleCommentKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') {
        event.preventDefault();
        handleCommentSend();
      }
    },
    [handleCommentSend]
  );

  const handleStartExecution = useCallback(() => {
    if (!itemId || !projectId || !canStartExecution) return;
    executeWorkItem.mutate({ itemId, orgId: orgId ?? null, projectId });
  }, [canStartExecution, executeWorkItem, itemId, orgId, projectId]);

  const handleCancelExecution = useCallback(() => {
    if (!itemId || !projectId || !canCancelExecution) return;
    cancelExecution.mutate({ itemId, orgId: orgId ?? null, projectId, reason: 'User requested cancellation' });
  }, [cancelExecution, canCancelExecution, itemId, orgId, projectId]);

  const handleClarificationChange = useCallback(
    (id: string, value: string) => {
      if (!itemId) return;
      setClarificationDraftsByItem((current) => {
        const next = { ...current };
        const itemDrafts = { ...(next[itemId] ?? {}) };
        itemDrafts[id] = value;
        next[itemId] = itemDrafts;
        return next;
      });
    },
    [itemId]
  );

  const handleClarificationSend = useCallback(
    (clarificationId: string) => {
      if (!itemId || !projectId) return;
      const response = clarificationDrafts[clarificationId]?.trim();
      if (!response) return;
      provideClarification.mutate({ itemId, orgId: orgId ?? null, projectId, clarificationId, response });
    },
    [clarificationDrafts, itemId, orgId, projectId, provideClarification]
  );

  const handleRefreshExecution = useCallback(() => {
    executionStatusQuery.refetch();
    if (executionStatus?.runId) {
      executionStepsQuery.refetch();
    }
  }, [executionStatus?.runId, executionStatusQuery, executionStepsQuery]);

  const handleAssign = useCallback(
    (profile: AssigneeProfile) => {
      if (!itemId) return;
      if (item?.assignee_id === profile.id && item?.assignee_type === profile.type) return;
      setSaveState('saving');
      assignItem.mutate(
        {
          itemId,
          assigneeId: profile.id,
          assigneeType: profile.type,
        },
        {
          onSuccess: () => {
            setSaveState('saved');
            setAssigneeSearch('');
            window.setTimeout(() => setSaveState('idle'), 1100);
          },
          onError: () => setSaveState('error'),
        }
      );
    },
    [assignItem, item?.assignee_id, item?.assignee_type, itemId]
  );

  const handleUnassign = useCallback(() => {
    if (!itemId || !item?.assignee_id) return;
    setSaveState('saving');
    unassignItem.mutate(
      { itemId },
      {
        onSuccess: () => {
          setSaveState('saved');
          window.setTimeout(() => setSaveState('idle'), 1100);
        },
        onError: () => setSaveState('error'),
      }
    );
  }, [item?.assignee_id, itemId, unassignItem]);

  return (
    <div
      ref={overlayRef}
      className={`work-item-drawer-overlay ${phase === 'open' ? 'open' : ''} ${phase === 'closing' ? 'closing' : ''}`}
      onMouseDown={handleOverlayMouseDown}
      role="dialog"
      aria-modal="true"
      aria-label={`${typeLabel} details`}
    >
      <aside className="work-item-drawer" onMouseDown={(e) => e.stopPropagation()}>
        <header className="work-item-drawer-header">
          <div className="work-item-drawer-header-left">
            <div className="work-item-drawer-type">{typeLabel}</div>
            {item?.item_id && <div className="work-item-drawer-id">{shortId(item.item_id)}</div>}
            {saveLabel && <div className="work-item-drawer-save">{saveLabel}</div>}
          </div>
          <div className="work-item-drawer-header-right">
            <button
              type="button"
              className="work-item-drawer-action pressable"
              onClick={handleCopyLink}
              disabled={!canCopy}
              aria-label="Copy link"
              title={canCopy ? 'Copy link' : 'Clipboard unavailable'}
            >
              ↗
            </button>
            <button
              type="button"
              className="work-item-drawer-action pressable"
              onClick={requestClose}
              aria-label="Close"
              title="Close"
            >
              ✕
            </button>
          </div>
        </header>

        <div className="work-item-drawer-body">
          {isLoading && (
            <div className="work-item-drawer-skeleton" aria-label="Loading work item">
              <div className="skeleton-line animate-shimmer" />
              <div className="skeleton-line animate-shimmer" />
              <div className="skeleton-block animate-shimmer" />
            </div>
          )}

          {isError && (
            <div className="work-item-drawer-error animate-fade-in-up" role="status">
              Couldn’t load this work item.
            </div>
          )}

          {!isLoading && item && (
            <div className="work-item-drawer-form">
              <div className="drawer-row">
                <label className="drawer-label" htmlFor="work-item-title">
                  Title
                </label>
                <input
                  id="work-item-title"
                  ref={titleRef}
                  className="drawer-input"
                  value={titleDraft}
                  onChange={handleTitleChange}
                  onBlur={() => debouncedSave.schedule()}
                  placeholder="What needs to happen?"
                  autoComplete="off"
                />
              </div>

              <div className="drawer-row drawer-row-inline">
                <div className="drawer-inline-field">
                  <label className="drawer-label" htmlFor="work-item-column">
                    Column
                  </label>
                  <select
                    id="work-item-column"
                    className="drawer-select"
                    value={item.column_id ?? '__none__'}
                    onChange={handleColumnChange}
                  >
                    <option value="__none__">Unsorted</option>
                    {columns.map((c) => (
                      <option key={c.column_id} value={c.column_id}>
                        {c.name}
                      </option>
                    ))}
                  </select>
                </div>

                <div className="drawer-inline-field">
                  <label className="drawer-label" htmlFor="work-item-priority">
                    Priority
                  </label>
                  <select
                    id="work-item-priority"
                    className="drawer-select"
                    value={priorityDraft}
                    onChange={handlePriorityChange}
                  >
                    <option value="critical">Critical</option>
                    <option value="high">High</option>
                    <option value="medium">Medium</option>
                    <option value="low">Low</option>
                  </select>
                </div>
              </div>

              <div className="drawer-row">
                <div className="drawer-label-row">
                  <label className="drawer-label">Assignee</label>
                  <span className="drawer-assignee-hint">{assignmentHint ?? 'Humans + agents'}</span>
                </div>
                <div className="assignee-panel">
                  <div className="assignee-current">
                    <div
                      className={`assignee-chip ${
                        assignmentProfile ? `assignee-${assignmentProfile.type}` : 'assignee-unassigned'
                      }${isOrphanedAssignment ? ' assignee-orphaned' : ''}`}
                      aria-label={assignmentProfile ? `Assigned to ${assignmentProfile.label}` : 'Unassigned'}
                      title={isOrphanedAssignment ? 'Agent no longer exists. Please re-assign.' : undefined}
                    >
                      <span className="assignee-avatar">
                        {assignmentProfile?.avatar ?? (assignmentProfile ? getInitials(assignmentProfile.label) : '+')}
                      </span>
                      <span className="assignee-name">
                        {assignmentProfile?.label ?? 'Unassigned'}
                      </span>
                      <span className="assignee-type-label">
                        {isOrphanedAssignment ? '⚠ Missing' : assignmentProfile?.type === 'agent' ? 'Agent' : assignmentProfile?.type === 'user' ? 'Human' : 'Unassigned'}
                      </span>
                    </div>
                    {item?.assignee_id && (
                      <button
                        type="button"
                        className="assignee-unassign pressable"
                        onClick={handleUnassign}
                        disabled={assignmentBusy}
                        data-haptic="light"
                      >
                        Unassign
                      </button>
                    )}
                  </div>

                  <input
                    className="drawer-input assignee-search-input"
                    value={assigneeSearch}
                    onChange={(e) => setAssigneeSearch(e.target.value)}
                    placeholder="Search people or agents"
                    aria-label="Search assignees"
                    autoComplete="off"
                  />

                  <div className="assignee-grid">
                    <div className="assignee-group">
                      <div className="assignee-group-title">People</div>
                      <div className="assignee-options">
                        {filteredHumans.map((profile) => {
                          const isSelected = item?.assignee_id === profile.id && item?.assignee_type === profile.type;
                          return (
                            <button
                              key={`user-${profile.id}`}
                              type="button"
                              className={`assignee-option pressable ${isSelected ? 'assignee-option-selected' : ''}`}
                              onClick={() => handleAssign(profile)}
                              disabled={assignmentBusy}
                              aria-pressed={isSelected}
                              aria-label={`Assign to ${profile.label}`}
                              data-haptic="light"
                            >
                              <span className="assignee-option-meta">
                                <span className="assignee-avatar">{profile.avatar ?? getInitials(profile.label)}</span>
                                <span className="assignee-text">
                                  <span className="assignee-name">{profile.label}</span>
                                  <span className="assignee-subtitle">{profile.subtitle ?? 'Human'}</span>
                                </span>
                              </span>
                              <span className="assignee-status">Human</span>
                            </button>
                          );
                        })}
                        {!filteredHumans.length && (
                          <div className="assignee-empty">
                            {assigneeSearchValue ? 'No people match this search.' : 'No people available yet.'}
                          </div>
                        )}
                      </div>
                    </div>

                    <div className="assignee-group">
                      <div className="assignee-group-title">Agents</div>
                      <div className="assignee-options">
                        {filteredAgents.map((profile) => {
                          const isSelected = item?.assignee_id === profile.id && item?.assignee_type === profile.type;
                          const statusLabel = toStatusLabel(profile.status);
                          return (
                            <button
                              key={`agent-${profile.id}`}
                              type="button"
                              className={`assignee-option pressable ${isSelected ? 'assignee-option-selected' : ''}`}
                              onClick={() => handleAssign(profile)}
                              disabled={assignmentBusy}
                              aria-pressed={isSelected}
                              aria-label={`Assign to ${profile.label}`}
                              data-haptic="light"
                            >
                              <span className="assignee-option-meta">
                                <span className="assignee-avatar">{profile.avatar ?? getInitials(profile.label)}</span>
                                <span className="assignee-text">
                                  <span className="assignee-name">{profile.label}</span>
                                  <span className="assignee-subtitle">{profile.subtitle ?? 'Agent'}</span>
                                </span>
                              </span>
                              <span
                                className={`assignee-status ${statusLabel ? `assignee-status-${statusLabel}` : ''}`}
                              >
                                {statusLabel ?? 'Agent'}
                              </span>
                            </button>
                          );
                        })}
                        {!filteredAgents.length && (
                          <div className="assignee-empty">
                            {assigneeSearchValue ? 'No agents match this search.' : 'No agents available yet.'}
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                </div>
              </div>

              <div className="drawer-row drawer-row-execution">
                <div className="drawer-label-row">
                  <label className="drawer-label">Execution</label>
                  <span className="drawer-assignee-hint">Agent run controls</span>
                </div>
                <div className="execution-stack">
                  <ExecutionStatusCard
                    status={executionStatus}
                    isLoading={executionStatusQuery.isLoading}
                    subtitle={executionHint}
                    actions={
                      <>
                        <button
                          type="button"
                          className="execution-action-button pressable"
                          onClick={handleStartExecution}
                          disabled={!canStartExecution || executeWorkItem.isPending}
                          title={canStartExecution ? startLabel : executionHint}
                          data-haptic="light"
                        >
                          {executeWorkItem.isPending ? 'Starting...' : startLabel}
                        </button>
                        <button
                          type="button"
                          className="execution-action-button execution-action-secondary pressable"
                          onClick={handleCancelExecution}
                          disabled={!canCancelExecution || cancelExecution.isPending}
                          data-haptic="light"
                        >
                          {cancelExecution.isPending ? 'Cancelling...' : 'Cancel'}
                        </button>
                        <button
                          type="button"
                          className="execution-action-button execution-action-ghost pressable"
                          onClick={handleRefreshExecution}
                          disabled={executionStatusQuery.isFetching}
                        >
                          {executionStatusQuery.isFetching ? 'Refreshing...' : 'Refresh'}
                        </button>
                      </>
                    }
                  />

                  {clarificationRequests.length > 0 && (
                    <div className="execution-clarifications">
                      <div className="execution-clarifications-title">Clarifications</div>
                      {clarificationRequests.map((request) => (
                        <div key={request.id} className="execution-clarification-card">
                          <div className="execution-clarification-prompt">{request.prompt}</div>
                          <textarea
                            className="execution-clarification-input"
                            rows={3}
                            value={clarificationDrafts[request.id] ?? ''}
                            onChange={(event) => handleClarificationChange(request.id, event.target.value)}
                            placeholder="Share context or a decision..."
                          />
                          <div className="execution-clarification-actions">
                            <button
                              type="button"
                              className="execution-action-button pressable"
                              onClick={() => handleClarificationSend(request.id)}
                              disabled={provideClarification.isPending || !(clarificationDrafts[request.id]?.trim())}
                              data-haptic="light"
                            >
                              {provideClarification.isPending ? 'Sending...' : 'Send response'}
                            </button>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}

                  {clarificationRequests.length === 0 && executionState === 'paused' && (
                    <div className="execution-clarification-empty">
                      Execution paused and awaiting input.
                    </div>
                  )}

                  <ExecutionTimeline
                    steps={executionSteps}
                    activePhase={executionStatus?.phase ?? null}
                    isLoading={executionStepsQuery.isLoading}
                    emptyLabel={executionStatus?.hasExecution ? 'No execution steps yet.' : 'Run to see step-by-step execution.'}
                  />
                </div>
              </div>

              <div className="drawer-row">
                <label className="drawer-label" htmlFor="work-item-description">
                  Description
                </label>
                <textarea
                  id="work-item-description"
                  className="drawer-textarea"
                  value={descriptionDraft}
                  onChange={handleDescriptionChange}
                  onBlur={() => debouncedSave.schedule()}
                  placeholder="Add context, links, and acceptance criteria…"
                  rows={8}
                />
              </div>

              <div className="drawer-row">
                <div className="drawer-label-row">
                  <label className="drawer-label">Comments</label>
                  <span className="comment-count">{commentFilterLabel}</span>
                </div>
                <div className="comments-panel">
                  <div className="comments-header">
                    <div className="comment-filters" role="tablist" aria-label="Filter comments">
                      <button
                        type="button"
                        className={`comment-filter ${commentFilter === 'all' ? 'comment-filter-active' : ''}`}
                        onClick={() => setCommentFilter('all')}
                        aria-pressed={commentFilter === 'all'}
                        data-haptic="light"
                      >
                        All
                      </button>
                      <button
                        type="button"
                        className={`comment-filter ${commentFilter === 'humans' ? 'comment-filter-active' : ''}`}
                        onClick={() => setCommentFilter('humans')}
                        aria-pressed={commentFilter === 'humans'}
                        data-haptic="light"
                      >
                        Humans
                      </button>
                      <button
                        type="button"
                        className={`comment-filter ${commentFilter === 'agents' ? 'comment-filter-active' : ''}`}
                        onClick={() => setCommentFilter('agents')}
                        aria-pressed={commentFilter === 'agents'}
                        data-haptic="light"
                      >
                        Agents
                      </button>
                    </div>
                    <button
                      type="button"
                      className="comment-refresh pressable"
                      onClick={() => commentsQuery.refetch()}
                      disabled={commentsQuery.isFetching}
                    >
                      {commentsQuery.isFetching ? 'Refreshing...' : 'Refresh'}
                    </button>
                  </div>

                  <div className="comment-compose">
                    <textarea
                      className="comment-compose-input"
                      rows={3}
                      value={commentDraft}
                      onChange={(event) => setCommentDraft(event.target.value)}
                      onKeyDown={handleCommentKeyDown}
                      placeholder={commentPlaceholder}
                      disabled={!actor?.id}
                    />
                    <div className="comment-compose-actions">
                      <span className="comment-compose-hint">{commentHint}</span>
                      <button
                        type="button"
                        className="comment-send-button pressable"
                        onClick={handleCommentSend}
                        disabled={!canPostComment}
                        data-haptic="light"
                      >
                        {postComment.isPending ? 'Sending...' : 'Send comment'}
                      </button>
                    </div>
                    {postComment.isError && (
                      <div className="comment-error" role="status">
                        Couldn’t post this comment.
                      </div>
                    )}
                  </div>

                  <div className="comment-list" role="list">
                    {commentsQuery.isLoading && (
                      <div className="comment-loading" role="status">
                        Loading comments...
                      </div>
                    )}
                    {commentsQuery.isError && !commentsQuery.isLoading && (
                      <div className="comment-error" role="status">
                        Couldn’t load comments.
                      </div>
                    )}
                    {!commentsQuery.isLoading && !commentsQuery.isError && filteredComments.length === 0 && (
                      <div className="comment-empty" role="status">
                        No comments yet. Start the thread.
                      </div>
                    )}
                    {filteredComments.map((comment) => {
                      const profile = resolveCommentProfile(comment);
                      const timeLabel = formatRelativeTime(comment.created_at ?? null);
                      const wasEdited =
                        Boolean(comment.updated_at) && comment.updated_at !== comment.created_at;
                      const authorTag = comment.author_type === 'agent' ? 'Agent' : 'Human';
                      return (
                        <div key={comment.comment_id} className="comment-card animate-fade-in-up" role="listitem">
                          <div className="comment-avatar">{profile.avatar}</div>
                          <div className="comment-body">
                            <div className="comment-meta">
                              <span className="comment-author">{profile.label}</span>
                              <span
                                className={`comment-author-tag ${
                                  comment.author_type === 'agent' ? 'comment-author-agent' : 'comment-author-user'
                                }`}
                              >
                                {authorTag}
                              </span>
                              {wasEdited && <span className="comment-edited">Edited</span>}
                              <span className="comment-time">{timeLabel}</span>
                              {comment.run_id && (
                                <span className="comment-run">Run {shortenAssigneeId(comment.run_id)}</span>
                              )}
                            </div>
                            <div className="comment-content">{comment.content}</div>
                          </div>
                        </div>
                      );
                    })}
                    <div ref={commentEndRef} />
                  </div>
                </div>
              </div>

              <div className="drawer-row">
                <label className="drawer-label">Labels</label>
                <div className="drawer-labels">
                  <div className="drawer-label-chips" aria-label="Labels">
                    {labels.map((label) => (
                      <button
                        key={label}
                        type="button"
                        className="drawer-chip pressable"
                        onClick={() => handleLabelsRemove(label)}
                        aria-label={`Remove label ${label}`}
                        title="Remove"
                      >
                        <span className="drawer-chip-text">{label}</span>
                        <span className="drawer-chip-x">✕</span>
                      </button>
                    ))}
                  </div>
                  <input
                    className="drawer-input drawer-input-label"
                    value={newLabelDraft}
                    onChange={(e) => setNewLabelDraft(e.target.value)}
                    onKeyDown={handleNewLabelKeyDown}
                    placeholder="Add label and press Enter"
                    autoComplete="off"
                  />
                </div>
              </div>
            </div>
          )}
        </div>
      </aside>
    </div>
  );
}
