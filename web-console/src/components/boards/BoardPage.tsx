/**
 * Board Page
 *
 * Fast, optimistic Kanban-style board with:
 * - Create tasks instantly per column
 * - Drag + drop between columns (plus keyboard-friendly Move control)
 *
 * Following COLLAB_SAAS_REQUIREMENTS.md (Student): optimistic updates, 60fps transforms.
 */

import React, { memo, useCallback, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { ConsoleSidebar } from '../ConsoleSidebar';
import { WorkspaceShell } from '../workspace/WorkspaceShell';
import { useProject } from '../../api/dashboard';
import {
  type BoardColumn,
  type WorkItem,
  type WorkItemType,
  useBoard,
  useCreateWorkItem,
  useMoveWorkItem,
  useWorkItems,
} from '../../api/boards';
import { WorkItemDrawer } from './WorkItemDrawer';
import './BoardPage.css';

function getColumnAccentIndex(index: number): number {
  const accentCount = 6;
  const next = index % accentCount;
  return next < 0 ? next + accentCount : next;
}

function getRelativeTime(dateString?: string): string {
  if (!dateString) return 'Unknown';
  const date = new Date(dateString);
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

function sortByPosition<T extends { position?: number; updated_at?: string }>(items: T[]): T[] {
  return [...items].sort((a, b) => {
    const posA = a.position ?? 0;
    const posB = b.position ?? 0;
    if (posA !== posB) return posA - posB;
    return (b.updated_at ?? '').localeCompare(a.updated_at ?? '');
  });
}

type DragPayload = { itemId: string };

function parseDragPayload(event: React.DragEvent): DragPayload | null {
  try {
    const raw = event.dataTransfer.getData('application/json');
    if (!raw) return null;
    const parsed = JSON.parse(raw) as { itemId?: unknown };
    if (typeof parsed.itemId === 'string' && parsed.itemId) return { itemId: parsed.itemId };
    return null;
  } catch {
    return null;
  }
}

interface WorkItemCardProps {
  item: WorkItem;
  columns: BoardColumn[];
  targetPositions: Record<string, number>;
  onMove: (itemId: string, toColumnId: string | null, position: number) => void;
  onOpen: (itemId: string) => void;
  onDragStart: (event: React.DragEvent, itemId: string) => void;
  onDragEnd: () => void;
  selected: boolean;
}

const WorkItemCard = memo(function WorkItemCard({
  item,
  columns,
  targetPositions,
  onMove,
  onOpen,
  onDragStart,
  onDragEnd,
  selected,
}: WorkItemCardProps) {
  const moveSelectId = `move-${item.item_id}`;
  const label = item.item_type === 'task' ? 'Task' : item.item_type === 'story' ? 'Story' : 'Epic';
  const draggingRef = React.useRef(false);

  const handleMoveChange = useCallback(
    (e: React.ChangeEvent<HTMLSelectElement>) => {
      const value = e.target.value;
      const toColumnId = value === '__none__' ? null : value;
      const position = toColumnId ? (targetPositions[toColumnId] ?? 0) : 0;
      onMove(item.item_id, toColumnId, position);
    },
    [item.item_id, onMove, targetPositions]
  );

  const handleOpen = useCallback(() => {
    if (draggingRef.current) return;
    onOpen(item.item_id);
  }, [item.item_id, onOpen]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        handleOpen();
      }
    },
    [handleOpen]
  );

  const handleDragStartInternal = useCallback(
    (e: React.DragEvent) => {
      draggingRef.current = true;
      onDragStart(e, item.item_id);
    },
    [item.item_id, onDragStart]
  );

  const handleDragEndInternal = useCallback(() => {
    window.setTimeout(() => {
      draggingRef.current = false;
    }, 0);
    onDragEnd();
  }, [onDragEnd]);

  return (
    <div
      className={`work-item-card work-item-card-${item.item_type} ${selected ? 'work-item-card-selected' : ''} pressable animate-fade-in-up`}
      draggable
      onDragStart={handleDragStartInternal}
      onDragEnd={handleDragEndInternal}
      onClick={handleOpen}
      onKeyDown={handleKeyDown}
      role="button"
      tabIndex={0}
      aria-label={`Open ${label}: ${item.title}`}
      aria-current={selected ? 'true' : undefined}
    >
      <div className="work-item-top">
        <span className={`work-item-type work-item-type-${item.item_type}`}>{label}</span>
        <label className="work-item-move" htmlFor={moveSelectId}>
          <span className="sr-only">Move</span>
          <select
            id={moveSelectId}
            value={item.column_id ?? '__none__'}
            onChange={handleMoveChange}
            onClick={(e) => e.stopPropagation()}
            onKeyDown={(e) => e.stopPropagation()}
          >
            <option value="__none__">Unsorted</option>
            {columns.map((c) => (
              <option key={c.column_id} value={c.column_id}>
                {c.name}
              </option>
            ))}
          </select>
        </label>
      </div>
      <div className="work-item-title">{item.title}</div>
      <div className="work-item-meta">
        <span className="work-item-id">{item.item_id.replace('task-', '#').replace('story-', '#').replace('epic-', '#')}</span>
        <span className="work-item-time">{getRelativeTime(item.updated_at)}</span>
      </div>
    </div>
  );
});

interface ColumnLaneProps {
  column: BoardColumn;
  accentIndex: number;
  items: WorkItem[];
  columns: BoardColumn[];
  targetPositions: Record<string, number>;
  onCreate: (columnId: string, title: string, itemType: WorkItemType) => void;
  onMove: (itemId: string, toColumnId: string | null, position: number) => void;
  onOpen: (itemId: string) => void;
  onDropToColumn: (columnId: string, itemId: string) => void;
  onDragStart: (event: React.DragEvent, itemId: string) => void;
  onDragEnd: () => void;
  selectedItemId?: string;
}

const ColumnLane = memo(function ColumnLane({
  column,
  accentIndex,
  items,
  columns,
  targetPositions,
  onCreate,
  onMove,
  onOpen,
  onDropToColumn,
  onDragStart,
  onDragEnd,
  selectedItemId,
}: ColumnLaneProps) {
  const [draft, setDraft] = useState('');
  const [itemType, setItemType] = useState<WorkItemType>('task');
  const [isOver, setIsOver] = useState(false);

  const handleSubmit = useCallback(() => {
    const title = draft.trim();
    if (!title) return;
    onCreate(column.column_id, title, itemType);
    setDraft('');
  }, [column.column_id, draft, itemType, onCreate]);

  const onKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        handleSubmit();
      }
    },
    [handleSubmit]
  );

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    setIsOver(true);
  }, []);

  const handleDragLeave = useCallback(() => setIsOver(false), []);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setIsOver(false);
      const payload = parseDragPayload(e);
      if (!payload) return;
      onDropToColumn(column.column_id, payload.itemId);
    },
    [column.column_id, onDropToColumn]
  );

  return (
    <section
      className={`board-column board-column-accent-${accentIndex} ${isOver ? 'drop-target' : ''}`}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
      aria-label={`Column ${column.name}`}
    >
      <header className="board-column-header">
        <div className="board-column-title-row">
          <h2 className="board-column-title">{column.name}</h2>
          <span className="board-column-count" aria-label={`${items.length} items`}>
            {items.length}
          </span>
        </div>
        <div className="board-column-compose" onKeyDown={onKeyDown}>
          <div className="board-compose-row">
            <select
              className="board-compose-type"
              value={itemType}
              onChange={(e) => setItemType(e.target.value as WorkItemType)}
              aria-label="Work item type"
            >
              <option value="task">Task</option>
              <option value="story">Story</option>
              <option value="epic">Epic</option>
            </select>
            <input
              className="board-compose-input"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              placeholder="Add…"
              aria-label={`Add item to ${column.name}`}
              autoComplete="off"
            />
            <button
              type="button"
              className="board-compose-add pressable"
              onClick={handleSubmit}
              disabled={!draft.trim()}
              data-haptic="light"
              aria-label={`Create in ${column.name}`}
            >
              +
            </button>
          </div>
          <div className="board-compose-hint">⌘/Ctrl + Enter</div>
        </div>
      </header>

      <div className="board-column-items" role="list">
        {items.map((item) => (
          <WorkItemCard
            key={item.item_id}
            item={item}
            columns={columns}
            targetPositions={targetPositions}
            onMove={onMove}
            onOpen={onOpen}
            onDragStart={onDragStart}
            onDragEnd={onDragEnd}
            selected={item.item_id === selectedItemId}
          />
        ))}
      </div>
    </section>
  );
});

export function BoardPage(): React.JSX.Element {
  const navigate = useNavigate();
  const { projectId, boardId, itemId } = useParams();

  const { data: project } = useProject(projectId);
  const { data: board, isLoading: boardLoading } = useBoard(boardId);
  const { data: items = [], isLoading: itemsLoading } = useWorkItems(boardId);

  const createItem = useCreateWorkItem();
  const moveItem = useMoveWorkItem(boardId);

  const columns = useMemo(() => {
    const cols = board?.columns ?? [];
    return sortByPosition(cols);
  }, [board?.columns]);

  const itemsByColumnId = useMemo(() => {
    const next: Record<string, WorkItem[]> = {};
    for (const item of items) {
      const columnKey = item.column_id ?? '__none__';
      if (!next[columnKey]) next[columnKey] = [];
      next[columnKey].push(item);
    }
    for (const k of Object.keys(next)) {
      next[k] = sortByPosition(next[k]);
    }
    return next;
  }, [items]);

  const targetPositions = useMemo(() => {
    const positions: Record<string, number> = {};
    for (const c of columns) {
      positions[c.column_id] = (itemsByColumnId[c.column_id]?.length ?? 0) + 1;
    }
    return positions;
  }, [columns, itemsByColumnId]);

  const onDragStart = useCallback((event: React.DragEvent, itemId: string) => {
    event.dataTransfer.effectAllowed = 'move';
    event.dataTransfer.setData('application/json', JSON.stringify({ itemId }));
  }, []);

  const onDragEnd = useCallback(() => {
    // Intentionally empty: reserved for future drag affordances.
  }, []);

  const onDropToColumn = useCallback(
    (columnId: string, itemId: string) => {
      const position = (itemsByColumnId[columnId]?.length ?? 0) + 1;
      moveItem.mutate({
        itemId,
        move: {
          column_id: columnId,
          position,
          expected_from_column_updated_at: null,
          expected_to_column_updated_at: null,
        },
      });
    },
    [itemsByColumnId, moveItem]
  );

  const onMove = useCallback(
    (itemId: string, toColumnId: string | null, position: number) => {
      moveItem.mutate({
        itemId,
        move: {
          column_id: toColumnId,
          position,
          expected_from_column_updated_at: null,
          expected_to_column_updated_at: null,
        },
      });
    },
    [moveItem]
  );

  const onOpen = useCallback(
    (openItemId: string) => {
      if (!projectId || !boardId) return;
      navigate(`/projects/${projectId}/boards/${boardId}/items/${openItemId}`);
    },
    [boardId, navigate, projectId]
  );

  const onCloseDrawer = useCallback(() => {
    if (!projectId || !boardId) return;
    navigate(`/projects/${projectId}/boards/${boardId}`);
  }, [boardId, navigate, projectId]);

  const selectedItem = useMemo(() => {
    if (!itemId) return undefined;
    return items.find((i) => i.item_id === itemId);
  }, [itemId, items]);

  const onCreate = useCallback(
    (columnId: string, title: string, itemType: WorkItemType) => {
      if (!projectId || !boardId) return;
      createItem.mutate({
        item_type: itemType,
        project_id: projectId,
        board_id: boardId,
        column_id: columnId,
        title,
        priority: 'medium',
      });
    },
    [boardId, createItem, projectId]
  );

  const pageTitle = useMemo(() => {
    if (boardLoading) return 'Board';
    return board?.name ? board.name : 'Board';
  }, [board, boardLoading]);

  const projectTitle = useMemo(() => project?.name ?? 'Project', [project?.name]);

  if (!projectId || !boardId) {
    return (
      <WorkspaceShell
        sidebarContent={<ConsoleSidebar selectedId="projects" onNavigate={(p) => navigate(p)} />}
        documentTitle="Board"
      >
        <div className="board-page">
          <div className="board-error animate-fade-in-up">Missing project or board ID.</div>
        </div>
      </WorkspaceShell>
    );
  }

  return (
    <WorkspaceShell
      sidebarContent={<ConsoleSidebar selectedId="projects" onNavigate={(p) => navigate(p)} />}
      documentTitle={pageTitle}
    >
      <div className="board-page">
        <header className="board-header">
          <div className="board-header-left">
            <button
              type="button"
              className="board-back pressable"
              onClick={() => navigate(`/projects/${projectId}`)}
              data-haptic="light"
            >
              ← {projectTitle}
            </button>
            <div>
              <h1 className="board-title animate-fade-in-up">{pageTitle}</h1>
              <p className="board-subtitle animate-fade-in-up">
                Drag items between columns or use Move for precise control.
              </p>
            </div>
          </div>

          <div className="board-header-right">
            <button
              type="button"
              className="board-settings pressable"
              onClick={() => navigate(`/projects/${projectId}/settings`)}
              data-haptic="light"
              aria-label="Project settings"
              title="Project settings"
            >
              ⚙️
            </button>
          </div>
        </header>

        {(boardLoading || itemsLoading) && (
          <div className="board-loading animate-fade-in-up" role="status" aria-label="Loading board">
            Loading board…
          </div>
        )}

        {!boardLoading && board && columns.length === 0 && (
          <div className="board-empty animate-fade-in-up" role="status">
            <h2 className="board-empty-title">No columns</h2>
            <p className="board-empty-description">Create the board with default columns to get the full flow.</p>
            <button type="button" className="board-empty-action pressable" onClick={() => navigate(`/projects/${projectId}`)} data-haptic="light">
              Back to project
            </button>
          </div>
        )}

        {!boardLoading && board && columns.length > 0 && (
          <div className="board-columns" aria-label="Board columns">
            {columns.map((col, index) => (
              <ColumnLane
                key={col.column_id}
                column={col}
                accentIndex={getColumnAccentIndex(index)}
                items={itemsByColumnId[col.column_id] ?? []}
                columns={columns}
                targetPositions={targetPositions}
                onCreate={onCreate}
                onMove={onMove}
                onOpen={onOpen}
                onDropToColumn={onDropToColumn}
                onDragStart={onDragStart}
                onDragEnd={onDragEnd}
                selectedItemId={itemId}
              />
            ))}
          </div>
        )}

        {itemId && (
          <WorkItemDrawer
            projectId={projectId}
            boardId={boardId}
            itemId={itemId}
            columns={columns}
            targetPositions={targetPositions}
            initialItem={selectedItem}
            onMove={onMove}
            onRequestClose={onCloseDrawer}
          />
        )}
      </div>
    </WorkspaceShell>
  );
}
