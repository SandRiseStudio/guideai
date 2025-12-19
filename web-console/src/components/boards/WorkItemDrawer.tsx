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
  type BoardColumn,
  type UpdateWorkItemRequest,
  type WorkItem,
  type WorkItemPriority,
  useUpdateWorkItem,
  useWorkItem,
} from '../../api/boards';
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

function normalizeLabel(input: string): string {
  return input.trim().replace(/\s+/g, '-').toLowerCase();
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

export interface WorkItemDrawerProps {
  projectId: string;
  boardId: string;
  itemId: string;
  columns: BoardColumn[];
  targetPositions: Record<string, number>;
  initialItem?: WorkItem;
  onMove: (itemId: string, toColumnId: string | null, position: number) => void;
  onRequestClose: () => void;
}

export function WorkItemDrawer({
  projectId,
  boardId,
  itemId,
  columns,
  targetPositions,
  initialItem,
  onMove,
  onRequestClose,
}: WorkItemDrawerProps): React.JSX.Element {
  const overlayRef = useRef<HTMLDivElement | null>(null);
  const titleRef = useRef<HTMLInputElement | null>(null);
  const prevFocusRef = useRef<HTMLElement | null>(null);

  const [phase, setPhase] = useState<DrawerPhase>('entering');
  const [saveState, setSaveState] = useState<SaveState>('idle');
  const [titleDraft, setTitleDraft] = useState(initialItem?.title ?? '');
  const [descriptionDraft, setDescriptionDraft] = useState(initialItem?.description ?? '');
  const [priorityDraft, setPriorityDraft] = useState<WorkItemPriority>(initialItem?.priority ?? 'medium');
  const [labels, setLabels] = useState<string[]>(initialItem?.labels ?? []);
  const [newLabelDraft, setNewLabelDraft] = useState('');

  const updateItem = useUpdateWorkItem(boardId);
  const { data: item, isLoading, isError } = useWorkItem(itemId, initialItem);

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
