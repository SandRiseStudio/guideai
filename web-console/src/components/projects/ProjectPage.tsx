/**
 * Project Page (Boards)
 *
 * Fast path:
 * Projects → Project → Create board / Open board
 *
 * Following COLLAB_SAAS_REQUIREMENTS.md (Student): optimistic, animated, 60fps.
 */

import { useCallback, useMemo, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { ConsoleSidebar } from '../ConsoleSidebar';
import { WorkspaceShell } from '../workspace/WorkspaceShell';
import { useProject } from '../../api/dashboard';
import { useBoards, useCreateBoard } from '../../api/boards';
import './ProjectPage.css';

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

/**
 * Map technical API errors to user-friendly messages
 */
function getUserFriendlyMessage(rawMessage: string): string {
  const lower = rawMessage.toLowerCase();

  if (lower.includes('service unavailable') || lower.includes('503')) {
    return 'The service is temporarily unavailable. Please try again in a moment.';
  }
  if (lower.includes('foreign key') || lower.includes('not present in table')) {
    return 'Unable to create board. Please refresh the page and try again.';
  }
  if (lower.includes('validation') || lower.includes('pattern')) {
    return 'Please check your input and try again.';
  }
  if (lower.includes('timeout') || lower.includes('timed out')) {
    return 'The request took too long. Please try again.';
  }
  if (lower.includes('unauthorized') || lower.includes('401')) {
    return 'Your session has expired. Please sign in again.';
  }
  if (lower.includes('forbidden') || lower.includes('403')) {
    return "You don't have permission to create boards in this project.";
  }
  if (lower.includes('not found') || lower.includes('404')) {
    return 'The project could not be found. Please refresh and try again.';
  }

  // Default: return a generic user-friendly message
  return 'Something went wrong while creating the board. Please try again.';
}

export function ProjectPage(): React.JSX.Element {
  const navigate = useNavigate();
  const { projectId } = useParams();

  const { data: project, isLoading: projectLoading } = useProject(projectId);
  const { data: boards = [], isLoading: boardsLoading } = useBoards(projectId);
  const createBoard = useCreateBoard();

  const [createOpen, setCreateOpen] = useState(false);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [createDefaultColumns, setCreateDefaultColumns] = useState(true);
  const [createError, setCreateError] = useState<string | null>(null);

  const nameInputRef = useRef<HTMLInputElement | null>(null);

  const sortedBoards = useMemo(() => {
    return [...boards].sort((a, b) => {
      if (a.is_default !== b.is_default) return a.is_default ? -1 : 1;
      return (b.updated_at ?? '').localeCompare(a.updated_at ?? '');
    });
  }, [boards]);

  const primaryBoardId = useMemo(() => sortedBoards[0]?.board_id, [sortedBoards]);

  const openCreate = useCallback(() => {
    setName('');
    setDescription('');
    setCreateDefaultColumns(true);
    setCreateError(null);
    setCreateOpen(true);
    requestAnimationFrame(() => nameInputRef.current?.focus());
  }, []);

  const closeCreate = useCallback(() => {
    setCreateOpen(false);
  }, []);

  const onCreate = useCallback(async () => {
    if (!projectId) return;
    const trimmed = name.trim();
    if (!trimmed) return;

    try {
      setCreateError(null);
      const created = await createBoard.mutateAsync({
        project_id: projectId,
        name: trimmed,
        description: description.trim() ? description.trim() : undefined,
        create_default_columns: createDefaultColumns,
      });
      navigate(`/projects/${projectId}/boards/${created.board_id}`);
    } catch (error: unknown) {
      // Network/CORS errors
      if (error instanceof Error && error.name === 'TypeError' && /Failed to fetch/i.test(error.message)) {
        setCreateError('Unable to connect to the server. Please check your connection and try again.');
        return;
      }

      // Map technical API errors to user-friendly messages
      const rawMessage = error instanceof Error ? error.message : String(error);
      setCreateError(getUserFriendlyMessage(rawMessage));
    }
  }, [createBoard, createDefaultColumns, description, navigate, name, projectId]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation();
        closeCreate();
      }
      if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        void onCreate();
      }
    },
    [closeCreate, onCreate]
  );

  const title = useMemo(() => {
    if (projectLoading) return 'Project';
    return project?.name ? project.name : 'Project';
  }, [project?.name, projectLoading]);

  if (!projectId) {
    return (
      <WorkspaceShell
        sidebarContent={<ConsoleSidebar selectedId="projects" onNavigate={(p) => navigate(p)} />}
        documentTitle="Project"
      >
        <div className="project-page">
          <div className="project-error animate-fade-in-up">Missing project ID.</div>
        </div>
      </WorkspaceShell>
    );
  }

  return (
    <WorkspaceShell
      sidebarContent={<ConsoleSidebar selectedId="projects" onNavigate={(p) => navigate(p)} />}
      documentTitle={title}
    >
      <div className="project-page" onKeyDown={handleKeyDown}>
        <header className="project-header">
          <div className="project-header-left">
            <button
              type="button"
              className="project-back pressable"
              onClick={() => navigate('/projects')}
              data-haptic="light"
            >
              ← Projects
            </button>
            <div>
              <h1 className="project-title animate-fade-in-up">{title}</h1>
              <p className="project-subtitle animate-fade-in-up">
                {project?.description ? project.description : 'Boards are where humans and agents coordinate work.'}
              </p>
            </div>
          </div>

          <div className="project-header-right">
            {primaryBoardId && (
              <button
                type="button"
                className="project-primary pressable"
                onClick={() => navigate(`/projects/${projectId}/boards/${primaryBoardId}`)}
                data-haptic="medium"
              >
                Continue
              </button>
            )}
            <button
              type="button"
              className="project-new-board pressable"
              onClick={openCreate}
              data-haptic="light"
            >
              New Board
            </button>
            <button
              type="button"
              className="project-settings pressable"
              onClick={() => navigate(`/projects/${projectId}/settings`)}
              data-haptic="light"
              aria-label="Project settings"
              title="Project settings"
            >
              ⚙️
            </button>
          </div>
        </header>

        <section className="project-boards" aria-label="Boards">
          <div className="project-boards-header">
            <h2 className="project-boards-title">Boards</h2>
            <p className="project-boards-hint">
              Tip: drag cards between columns, or use the Move menu for keyboard-friendly control.
            </p>
          </div>

          <div className="boards-grid" role="list">
            {boardsLoading ? (
              <>
                <div className="board-card skeleton animate-shimmer" />
                <div className="board-card skeleton animate-shimmer" />
                <div className="board-card skeleton animate-shimmer" />
              </>
            ) : sortedBoards.length > 0 ? (
              sortedBoards.map((board) => (
                <button
                  key={board.board_id}
                  type="button"
                  className="board-card pressable animate-fade-in-up"
                  onClick={() => navigate(`/projects/${projectId}/boards/${board.board_id}`)}
                  data-haptic="light"
                  role="listitem"
                  aria-label={`Open board ${board.name}`}
                >
                  <div className="board-card-top">
                    <h3 className="board-card-title">{board.name}</h3>
                    {board.is_default && <span className="board-pill">Default</span>}
                  </div>
                  {board.description && <p className="board-card-description">{board.description}</p>}
                  <div className="board-card-meta">
                    <span className="board-meta">Updated {getRelativeTime(board.updated_at)}</span>
                    <span className="board-meta-id">{board.board_id.replace('brd-', '#')}</span>
                  </div>
                </button>
              ))
            ) : (
              <div className="boards-empty animate-fade-in-up" role="listitem">
                <h3 className="boards-empty-title">No boards yet</h3>
                <p className="boards-empty-description">
                  Create a board in one click. Default columns come ready for sprint flow.
                </p>
                <button
                  type="button"
                  className="project-new-board pressable"
                  onClick={openCreate}
                  data-haptic="medium"
                >
                  Create your first board
                </button>
              </div>
            )}
          </div>
        </section>

        {createOpen && (
          <div className="modal-overlay" role="presentation" onClick={closeCreate}>
            <div
              className="modal-card animate-scale-in"
              role="dialog"
              aria-modal="true"
              aria-label="Create board"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="modal-header">
                <div>
                  <h2 className="modal-title">New board</h2>
                  <p className="modal-subtitle">⌘/Ctrl + Enter to create instantly</p>
                </div>
                <button type="button" className="modal-close pressable" onClick={closeCreate} aria-label="Close">
                  ✕
                </button>
              </div>

              <div className="modal-body">
                {createError && (
                  <div className="modal-error animate-fade-in-up" role="alert">
                    {createError}
                  </div>
                )}
                <label className="field">
                  <span className="field-label">Name</span>
                  <input
                    ref={nameInputRef}
                    className="field-input"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder="e.g. Sprint 1 · Execution"
                    autoComplete="off"
                  />
                </label>

                <label className="field">
                  <span className="field-label">Description (optional)</span>
                  <textarea
                    className="field-textarea"
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                    placeholder="What’s this board for?"
                    rows={3}
                  />
                </label>

                <label className="toggle">
                  <input
                    type="checkbox"
                    checked={createDefaultColumns}
                    onChange={(e) => setCreateDefaultColumns(e.target.checked)}
                  />
                  <span className="toggle-label">Create default columns</span>
                  <span className="toggle-hint">Backlog → To Do → In Progress → Review → Done</span>
                </label>
              </div>

              <div className="modal-footer">
                <button type="button" className="modal-secondary pressable" onClick={closeCreate} data-haptic="light">
                  Cancel
                </button>
                <button
                  type="button"
                  className="modal-primary pressable"
                  onClick={() => void onCreate()}
                  disabled={!name.trim() || createBoard.isPending}
                  data-haptic="medium"
                >
                  {createBoard.isPending ? 'Creating…' : 'Create board'}
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </WorkspaceShell>
  );
}
