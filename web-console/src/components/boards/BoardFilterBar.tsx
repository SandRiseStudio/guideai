/**
 * Board Filter Bar
 *
 * A sleek, glassmorphic toolbar for filtering and sorting board work items.
 * Follows the filter-pill pattern from AgentsPage — pills, search, dropdowns.
 *
 * All filter state lives in URL search params via useBoardFilters().
 */

import React, { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { RefreshCw, Settings } from 'lucide-react';
import type { WorkItemPriority, WorkItemType } from '../../api/boards';
import { ActorAvatar } from '../actors/ActorAvatar';
import type { AssigneeProfile } from './WorkItemDrawer';
import type { SortField, BoardFilterState } from './useBoardFilters';
import './BoardFilterBar.css';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const TYPE_OPTIONS: Array<{ label: string; value: WorkItemType; icon: string }> = [
  { label: 'Goal', value: 'goal', icon: '◆' },
  { label: 'Feature', value: 'feature', icon: '◇' },
  { label: 'Task', value: 'task', icon: '•' },
  { label: 'Bug', value: 'bug', icon: '🐛' },
];

const PRIORITY_OPTIONS: Array<{ label: string; value: WorkItemPriority; cssClass: string }> = [
  { label: 'Critical', value: 'critical', cssClass: 'priority-critical' },
  { label: 'High', value: 'high', cssClass: 'priority-high' },
  { label: 'Medium', value: 'medium', cssClass: 'priority-medium' },
  { label: 'Low', value: 'low', cssClass: 'priority-low' },
];

const SORT_OPTIONS: Array<{ label: string; value: SortField }> = [
  { label: 'Position', value: 'position' },
  { label: 'Priority', value: 'priority' },
  { label: 'Created', value: 'created_at' },
  { label: 'Updated', value: 'updated_at' },
  { label: 'Due Date', value: 'due_date' },
  { label: 'Title', value: 'title' },
  { label: 'Points', value: 'points' },
];

const DUE_PRESETS: Array<{ label: string; getRange: () => { after: string | null; before: string | null } }> = [
  {
    label: 'Overdue',
    getRange: () => ({ after: null, before: new Date().toISOString().slice(0, 10) }),
  },
  {
    label: 'This week',
    getRange: () => {
      const now = new Date();
      const day = now.getDay();
      const monday = new Date(now);
      monday.setDate(now.getDate() - (day === 0 ? 6 : day - 1));
      const sunday = new Date(monday);
      sunday.setDate(monday.getDate() + 6);
      return {
        after: monday.toISOString().slice(0, 10),
        before: sunday.toISOString().slice(0, 10),
      };
    },
  },
  {
    label: 'This month',
    getRange: () => {
      const now = new Date();
      const first = new Date(now.getFullYear(), now.getMonth(), 1);
      const last = new Date(now.getFullYear(), now.getMonth() + 1, 0);
      return {
        after: first.toISOString().slice(0, 10),
        before: last.toISOString().slice(0, 10),
      };
    },
  },
];

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

type ViewMode = 'board' | 'outline';

interface BoardFilterBarProps {
  filterState: BoardFilterState;
  assignableHumans: AssigneeProfile[];
  assignableAgents: AssigneeProfile[];
  allLabels: string[];
  totalCount: number;
  matchCount: number;
  collapsed?: boolean;
  onToggleExpand?: () => void;
  /* Unified-bar props (header elements folded in) */
  boardTitle: string;
  projectTitle: string;
  onBack: () => void;
  viewMode: ViewMode;
  onViewChange: (mode: ViewMode) => void;
  onSettings: () => void;
  /* Refresh props */
  onRefresh?: () => void;
  isRefreshing?: boolean;
  lastSyncedAt?: Date | null;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export const BoardFilterBar = memo(function BoardFilterBar({
  filterState,
  assignableHumans,
  assignableAgents,
  allLabels,
  totalCount,
  matchCount,
  collapsed = false,
  onToggleExpand,
  boardTitle,
  projectTitle,
  onBack,
  viewMode,
  onViewChange,
  onSettings,
  onRefresh,
  isRefreshing = false,
  lastSyncedAt,
}: BoardFilterBarProps) {
  const { filters, sort, hasActiveFilters, activeFilterCount, setFilter, setSort, toggleSort, clearFilters } = filterState;
  const searchRef = useRef<HTMLInputElement>(null);
  const [assigneeOpen, setAssigneeOpen] = useState(false);
  const [labelsOpen, setLabelsOpen] = useState(false);
  const [sortOpen, setSortOpen] = useState(false);
  const [dueOpen, setDueOpen] = useState(false);
  const assigneeRef = useRef<HTMLDivElement>(null);
  const labelsRef = useRef<HTMLDivElement>(null);
  const sortRef = useRef<HTMLDivElement>(null);
  const dueRef = useRef<HTMLDivElement>(null);
  const assigneeTriggerRef = useRef<HTMLButtonElement>(null);
  const labelsTriggerRef = useRef<HTMLButtonElement>(null);
  const sortTriggerRef = useRef<HTMLButtonElement>(null);
  const dueTriggerRef = useRef<HTMLButtonElement>(null);

  const closeAllPopovers = useCallback((focusTarget?: HTMLElement | null) => {
    setAssigneeOpen(false);
    setLabelsOpen(false);
    setSortOpen(false);
    setDueOpen(false);
    if (focusTarget) {
      window.requestAnimationFrame(() => focusTarget.focus());
    }
  }, []);

  // Close popover on outside click
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (assigneeOpen && assigneeRef.current && !assigneeRef.current.contains(e.target as Node)) {
        setAssigneeOpen(false);
      }
      if (labelsOpen && labelsRef.current && !labelsRef.current.contains(e.target as Node)) {
        setLabelsOpen(false);
      }
      if (sortOpen && sortRef.current && !sortRef.current.contains(e.target as Node)) {
        setSortOpen(false);
      }
      if (dueOpen && dueRef.current && !dueRef.current.contains(e.target as Node)) {
        setDueOpen(false);
      }
    }
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, [assigneeOpen, labelsOpen, sortOpen, dueOpen]);

  useEffect(() => {
    if (!assigneeOpen && !labelsOpen && !sortOpen && !dueOpen) return;

    const handleEscape = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      event.preventDefault();

      if (sortOpen) {
        closeAllPopovers(sortTriggerRef.current);
        return;
      }
      if (dueOpen) {
        closeAllPopovers(dueTriggerRef.current);
        return;
      }
      if (labelsOpen) {
        closeAllPopovers(labelsTriggerRef.current);
        return;
      }
      if (assigneeOpen) {
        closeAllPopovers(assigneeTriggerRef.current);
      }
    };

    document.addEventListener('keydown', handleEscape);
    return () => document.removeEventListener('keydown', handleEscape);
  }, [assigneeOpen, closeAllPopovers, dueOpen, labelsOpen, sortOpen]);

  // Cmd/Ctrl+K or / to focus search
  useEffect(() => {
    function handleKey(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        searchRef.current?.focus();
        return;
      }
      if (e.key === '/' && !isInputFocused()) {
        e.preventDefault();
        searchRef.current?.focus();
      }
    }
    document.addEventListener('keydown', handleKey);
    return () => document.removeEventListener('keydown', handleKey);
  }, []);

  const handleSearchKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Escape') {
      setFilter('query', '');
      searchRef.current?.blur();
    }
  }, [setFilter]);

  // Type toggle
  const toggleType = useCallback((type: WorkItemType) => {
    const current = filters.types;
    const next = current.includes(type)
      ? current.filter((t) => t !== type)
      : [...current, type];
    setFilter('types', next);
  }, [filters.types, setFilter]);

  // Priority toggle
  const togglePriority = useCallback((priority: WorkItemPriority) => {
    const current = filters.priorities;
    const next = current.includes(priority)
      ? current.filter((p) => p !== priority)
      : [...current, priority];
    setFilter('priorities', next);
  }, [filters.priorities, setFilter]);

  // Assignee toggle
  const toggleAssignee = useCallback((id: string) => {
    setFilter('assigneeId', filters.assigneeId === id ? null : id);
    setAssigneeOpen(false);
  }, [filters.assigneeId, setFilter]);

  // Label toggle
  const toggleLabel = useCallback((label: string) => {
    const current = filters.labels;
    const next = current.includes(label)
      ? current.filter((l) => l !== label)
      : [...current, label];
    setFilter('labels', next);
  }, [filters.labels, setFilter]);

  // Sort select
  const handleSortSelect = useCallback((field: SortField) => {
    if (sort.field === field) {
      toggleSort(field);
    } else {
      setSort(field, 'asc');
    }
    setSortOpen(false);
  }, [setSort, sort.field, toggleSort]);

  // Due date preset
  const handleDuePreset = useCallback((preset: typeof DUE_PRESETS[number]) => {
    const range = preset.getRange();
    setFilter('dueAfter', range.after);
    setFilter('dueBefore', range.before);
    setDueOpen(false);
  }, [setFilter]);

  const clearDueDates = useCallback(() => {
    setFilter('dueAfter', null);
    setFilter('dueBefore', null);
    setDueOpen(false);
  }, [setFilter]);

  // Assignee display label
  const assigneeLabel = useMemo(() => {
    if (!filters.assigneeId) return 'Assignee';
    if (filters.assigneeId === '__unassigned__') return 'Unassigned';
    const all = [...assignableHumans, ...assignableAgents];
    const match = all.find((p) => p.id === filters.assigneeId);
    return match?.label ?? 'Assignee';
  }, [filters.assigneeId, assignableHumans, assignableAgents]);

  // Active due label
  const dueLabel = useMemo(() => {
    if (filters.dueAfter && filters.dueBefore) return `${filters.dueAfter} → ${filters.dueBefore}`;
    if (filters.dueAfter) return `After ${filters.dueAfter}`;
    if (filters.dueBefore) return `Before ${filters.dueBefore}`;
    return 'Due Date';
  }, [filters.dueAfter, filters.dueBefore]);

  const hasDueFilter = Boolean(filters.dueAfter || filters.dueBefore);

  const currentSortLabel = SORT_OPTIONS.find((o) => o.value === sort.field)?.label ?? 'Position';

  return (
    <div className={`board-filter-bar animate-fade-in-up ${collapsed ? 'board-filter-bar-collapsed' : ''}`} role="toolbar" aria-label="Board toolbar">
      {/* ── Row 1: chrome — navigation + title + density + settings ────── */}
      <div className="board-toolbar-chrome">
        <div className="board-toolbar-left">
          <button
            type="button"
            className="board-back pressable"
            onClick={onBack}
            data-haptic="light"
          >
            ← {projectTitle}
          </button>
          <h1 className="board-title">{boardTitle}</h1>
        </div>

        <div className="board-toolbar-right">
          <div
            className="board-view-segmented"
            role="group"
            aria-label="View mode"
            title="Switch view"
          >
            <button
              type="button"
              className={`board-view-option pressable ${viewMode === 'board' ? 'active' : ''}`}
              onClick={() => onViewChange('board')}
              data-haptic="light"
              aria-pressed={viewMode === 'board'}
              title="Board view"
            >
              <span className="board-view-option-icon" aria-hidden="true">▦</span>
              <span className="board-view-option-label">Board</span>
            </button>
            <button
              type="button"
              className={`board-view-option pressable ${viewMode === 'outline' ? 'active' : ''}`}
              onClick={() => onViewChange('outline')}
              data-haptic="light"
              aria-pressed={viewMode === 'outline'}
              title="Outline view"
            >
              <span className="board-view-option-icon" aria-hidden="true">☰</span>
              <span className="board-view-option-label">Outline</span>
            </button>
          </div>
          {onRefresh && (
            <button
              type="button"
              className={`board-refresh pressable ${isRefreshing ? 'refreshing' : ''}`}
              onClick={onRefresh}
              disabled={isRefreshing}
              data-haptic="light"
              aria-label={isRefreshing ? 'Refreshing…' : 'Refresh board'}
              title={lastSyncedAt ? `Last synced ${formatRelativeTime(lastSyncedAt)}` : 'Refresh board'}
            >
              <RefreshCw
                className="board-refresh-icon"
                size={15}
                strokeWidth={2.2}
                absoluteStrokeWidth
                aria-hidden="true"
              />
            </button>
          )}
          <button
            type="button"
            className="board-settings pressable"
            onClick={onSettings}
            data-haptic="light"
            aria-label="Open project settings"
            title="Open project settings"
          >
            <Settings className="board-settings-icon" size={16} strokeWidth={2.1} absoluteStrokeWidth aria-hidden="true" />
          </button>
        </div>
      </div>

      {/* ── Row 2: filters — search + pills + dropdowns + sort ─────────── */}
      <div className="board-toolbar-filters">
      {/* Search */}
      <label className="board-filter-search-wrapper">
        <span className="board-filter-search-icon" aria-hidden="true">⌕</span>
        <input
          ref={searchRef}
          className="board-filter-search"
          value={filters.query}
          onChange={(e) => setFilter('query', e.target.value)}
          onKeyDown={handleSearchKeyDown}
          placeholder="Search…"
          autoComplete="off"
          spellCheck={false}
          aria-label="Search work items"
        />
        {!filters.query && (
          <span className="board-filter-search-shortcut" aria-hidden="true">⌘K</span>
        )}
        {filters.query && (
          <button
            type="button"
            className="board-filter-search-clear pressable"
            onClick={() => setFilter('query', '')}
            aria-label="Clear search"
          >
            ×
          </button>
        )}
      </label>

      {/* Collapsed: show toggle + active count */}
      {collapsed && (
        <button
          type="button"
          className={`board-filter-expand-trigger pressable ${hasActiveFilters ? 'active' : ''}`}
          onClick={onToggleExpand}
          data-haptic="light"
          aria-label={`Show all filters${activeFilterCount > 0 ? ` (${activeFilterCount} active)` : ''}`}
        >
          Filters
          {activeFilterCount > 0 && (
            <span className="board-filter-expand-badge">{activeFilterCount}</span>
          )}
          <span className="board-filter-dropdown-arrow" aria-hidden="true">▾</span>
        </button>
      )}

      {/* Advanced filters — hidden when collapsed */}
      <div className={`board-filter-advanced ${collapsed ? 'board-filter-advanced-hidden' : ''}`}>
      {/* Type pills */}
      <div className="board-filter-group" role="group" aria-label="Filter by type">
        <span className="board-filter-label">Type</span>
        <div className="board-filter-pills">
          {TYPE_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              type="button"
              className={`board-filter-pill pressable ${filters.types.includes(opt.value) ? 'active' : ''}`}
              onClick={() => toggleType(opt.value)}
              data-haptic="light"
              aria-pressed={filters.types.includes(opt.value)}
            >
              <span className="board-filter-pill-icon" aria-hidden="true">{opt.icon}</span>
              {opt.label}
            </button>
          ))}
        </div>
      </div>

      {/* Priority pills */}
      <div className="board-filter-group" role="group" aria-label="Filter by priority">
        <span className="board-filter-label">Priority</span>
        <div className="board-filter-pills">
          {PRIORITY_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              type="button"
              className={`board-filter-pill pressable ${filters.priorities.includes(opt.value) ? 'active' : ''} ${opt.cssClass}`}
              onClick={() => togglePriority(opt.value)}
              data-haptic="light"
              aria-pressed={filters.priorities.includes(opt.value)}
            >
              <span className={`board-filter-priority-dot ${opt.cssClass}`} aria-hidden="true" />
              {opt.label}
            </button>
          ))}
        </div>
      </div>

      {/* Assignee dropdown */}
      <div className="board-filter-dropdown-wrapper" ref={assigneeRef}>
        <button
          ref={assigneeTriggerRef}
          type="button"
          className={`board-filter-dropdown-trigger pressable ${filters.assigneeId ? 'active' : ''}`}
          onClick={() => setAssigneeOpen((p) => !p)}
          data-haptic="light"
          aria-expanded={assigneeOpen}
          aria-haspopup="listbox"
        >
          {assigneeLabel}
          <span className="board-filter-dropdown-arrow" aria-hidden="true">{assigneeOpen ? '▴' : '▾'}</span>
        </button>
        {assigneeOpen && (
          <div className="board-filter-popover" role="listbox" aria-label="Assignee options">
            <button
              type="button"
              className={`board-filter-popover-option pressable ${filters.assigneeId === '__unassigned__' ? 'selected' : ''}`}
              onClick={() => toggleAssignee('__unassigned__')}
            >
              <span className="board-filter-popover-avatar">—</span>
              <span>Unassigned</span>
            </button>
            {assignableHumans.length > 0 && (
              <div className="board-filter-popover-section-label">People</div>
            )}
            {assignableHumans.map((person) => (
              <button
                key={person.id}
                type="button"
                className={`board-filter-popover-option pressable ${filters.assigneeId === person.id ? 'selected' : ''}`}
                onClick={() => toggleAssignee(person.id)}
              >
                <span className="board-filter-popover-avatar">
                  {person.actor ? (
                    <ActorAvatar actor={person.actor} size="sm" surfaceType="chip" decorative />
                  ) : (
                    person.avatar
                  )}
                </span>
                <span className="board-filter-popover-name">
                  {person.label}
                  {person.subtitle ? <span className="board-filter-popover-subtitle">{person.subtitle}</span> : null}
                </span>
              </button>
            ))}
            {assignableAgents.length > 0 && (
              <div className="board-filter-popover-section-label">Agents</div>
            )}
            {assignableAgents.map((agent) => (
              <button
                key={agent.id}
                type="button"
                className={`board-filter-popover-option pressable ${filters.assigneeId === agent.id ? 'selected' : ''}`}
                onClick={() => toggleAssignee(agent.id)}
              >
                <span className="board-filter-popover-avatar">
                  {agent.actor ? (
                    <ActorAvatar actor={agent.actor} size="sm" surfaceType="chip" decorative />
                  ) : (
                    agent.avatar
                  )}
                </span>
                <span className="board-filter-popover-name">
                  {agent.label}
                  {agent.subtitle ? <span className="board-filter-popover-subtitle">{agent.subtitle}</span> : null}
                </span>
              </button>
            ))}
            {filters.assigneeId && (
              <button
                type="button"
                className="board-filter-popover-clear pressable"
                onClick={() => { setFilter('assigneeId', null); setAssigneeOpen(false); }}
              >
                Clear assignee filter
              </button>
            )}
          </div>
        )}
      </div>

      {/* Labels dropdown */}
      {allLabels.length > 0 && (
        <div className="board-filter-dropdown-wrapper" ref={labelsRef}>
          <button
            ref={labelsTriggerRef}
            type="button"
            className={`board-filter-dropdown-trigger pressable ${filters.labels.length > 0 ? 'active' : ''}`}
            onClick={() => setLabelsOpen((p) => !p)}
            data-haptic="light"
            aria-expanded={labelsOpen}
            aria-haspopup="listbox"
          >
            {filters.labels.length > 0 ? `Labels (${filters.labels.length})` : 'Labels'}
            <span className="board-filter-dropdown-arrow" aria-hidden="true">{labelsOpen ? '▴' : '▾'}</span>
          </button>
          {labelsOpen && (
            <div className="board-filter-popover" role="listbox" aria-label="Label options">
              {allLabels.map((label) => (
                <button
                  key={label}
                  type="button"
                  className={`board-filter-popover-option pressable ${filters.labels.includes(label) ? 'selected' : ''}`}
                  onClick={() => toggleLabel(label)}
                >
                  <span className="board-filter-check" aria-hidden="true">
                    {filters.labels.includes(label) ? '✓' : ''}
                  </span>
                  <span>{label}</span>
                </button>
              ))}
              {filters.labels.length > 0 && (
                <button
                  type="button"
                  className="board-filter-popover-clear pressable"
                  onClick={() => { setFilter('labels', []); setLabelsOpen(false); }}
                >
                  Clear label filters
                </button>
              )}
            </div>
          )}
        </div>
      )}

      {/* Due date dropdown */}
      <div className="board-filter-dropdown-wrapper" ref={dueRef}>
        <button
          ref={dueTriggerRef}
          type="button"
          className={`board-filter-dropdown-trigger pressable ${hasDueFilter ? 'active' : ''}`}
          onClick={() => setDueOpen((p) => !p)}
          data-haptic="light"
          aria-expanded={dueOpen}
          aria-haspopup="dialog"
        >
          {dueLabel}
          <span className="board-filter-dropdown-arrow" aria-hidden="true">{dueOpen ? '▴' : '▾'}</span>
        </button>
        {dueOpen && (
          <div className="board-filter-popover board-filter-due-popover" role="dialog" aria-label="Due date filter">
            <div className="board-filter-due-presets">
              {DUE_PRESETS.map((preset) => (
                <button
                  key={preset.label}
                  type="button"
                  className="board-filter-due-preset pressable"
                  onClick={() => handleDuePreset(preset)}
                  data-haptic="light"
                >
                  {preset.label}
                </button>
              ))}
            </div>
            <div className="board-filter-due-inputs">
              <label className="board-filter-due-field">
                <span className="board-filter-label">After</span>
                <input
                  type="date"
                  className="board-filter-date-input"
                  value={filters.dueAfter ?? ''}
                  onChange={(e) => setFilter('dueAfter', e.target.value || null)}
                />
              </label>
              <label className="board-filter-due-field">
                <span className="board-filter-label">Before</span>
                <input
                  type="date"
                  className="board-filter-date-input"
                  value={filters.dueBefore ?? ''}
                  onChange={(e) => setFilter('dueBefore', e.target.value || null)}
                />
              </label>
            </div>
            {hasDueFilter && (
              <button
                type="button"
                className="board-filter-popover-clear pressable"
                onClick={clearDueDates}
              >
                Clear date filter
              </button>
            )}
          </div>
        )}
      </div>

      {/* Sort control */}
      <div className="board-filter-sort-wrapper" ref={sortRef}>
        <button
          ref={sortTriggerRef}
          type="button"
          className={`board-filter-sort-trigger pressable ${sort.field !== 'position' ? 'active' : ''}`}
          onClick={() => setSortOpen((p) => !p)}
          data-haptic="light"
          aria-expanded={sortOpen}
          aria-haspopup="listbox"
        >
          <span className="board-filter-sort-label">Sort: {currentSortLabel}</span>
          <span
            className={`board-filter-sort-direction ${sort.order}`}
            aria-label={sort.order === 'asc' ? 'Ascending' : 'Descending'}
            onClick={(e) => { e.stopPropagation(); toggleSort(sort.field); }}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                e.stopPropagation();
                toggleSort(sort.field);
              }
            }}
            role="button"
            tabIndex={0}
          >
            {sort.order === 'asc' ? '↑' : '↓'}
          </span>
        </button>
        {sortOpen && (
          <div className="board-filter-popover board-filter-sort-popover" role="listbox" aria-label="Sort options">
            {SORT_OPTIONS.map((opt) => (
              <button
                key={opt.value}
                type="button"
                className={`board-filter-popover-option pressable ${sort.field === opt.value ? 'selected' : ''}`}
                onClick={() => handleSortSelect(opt.value)}
              >
                <span className="board-filter-check" aria-hidden="true">
                  {sort.field === opt.value ? '✓' : ''}
                </span>
                {opt.label}
                {sort.field === opt.value && (
                  <span className="board-filter-sort-indicator">{sort.order === 'asc' ? '↑' : '↓'}</span>
                )}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Active filter summary + clear */}
      {hasActiveFilters && (
        <div className="board-filter-summary" aria-live="polite">
          <span className="board-filter-count-badge">{activeFilterCount}</span>
          <span className="board-filter-match-text">
            {matchCount} of {totalCount}
          </span>
          <button
            type="button"
            className="board-filter-clear-all pressable"
            onClick={clearFilters}
            data-haptic="light"
          >
            Clear all
          </button>
        </div>
      )}
      </div>{/* end board-filter-advanced */}
      </div>{/* end board-toolbar-filters */}
    </div>
  );
});

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function isInputFocused(): boolean {
  const el = document.activeElement;
  if (!el) return false;
  const tag = el.tagName.toLowerCase();
  return tag === 'input' || tag === 'textarea' || tag === 'select' || (el as HTMLElement).isContentEditable;
}

function formatRelativeTime(date: Date): string {
  const now = Date.now();
  const diffMs = now - date.getTime();
  const diffSecs = Math.floor(diffMs / 1000);
  const diffMins = Math.floor(diffSecs / 60);

  if (diffSecs < 10) return 'just now';
  if (diffSecs < 60) return `${diffSecs}s ago`;
  if (diffMins < 60) return `${diffMins}m ago`;
  return date.toLocaleTimeString();
}
