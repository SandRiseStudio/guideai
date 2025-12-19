/**
 * Projects Page
 *
 * Lists projects and provides entry point to create a new project.
 *
 * Following `COLLAB_SAAS_REQUIREMENTS.md` (Student): fast, floaty, animated.
 */

import { useCallback, useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { WorkspaceShell } from '../workspace/WorkspaceShell';
import { ConsoleSidebar } from '../ConsoleSidebar';
import { OrgSwitcher } from '../OrgSwitcher';
import { useOrganizations, useProjects, type Project } from '../../api/dashboard';
import './ProjectsPage.css';

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

function matchesQuery(project: Project, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  return (
    project.name.toLowerCase().includes(q) ||
    project.slug.toLowerCase().includes(q) ||
    (project.description ?? '').toLowerCase().includes(q)
  );
}

export function ProjectsPage(): React.JSX.Element {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();

  const orgFromQuery = searchParams.get('org') ?? undefined;
  const [currentOrgId, setCurrentOrgId] = useState<string | undefined>(orgFromQuery);

  const { data: organizations = [] } = useOrganizations();
  const {
    data: projects = [],
    isLoading: projectsLoading,
    isFetching: projectsFetching,
    isError: projectsError,
    refetch: refetchProjects,
  } = useProjects(currentOrgId);

  const [query, setQuery] = useState('');


  const filteredProjects = useMemo(
    () => projects.filter((p) => matchesQuery(p, query)),
    [projects, query]
  );

  const handleOrgSelect = useCallback(
    (orgId?: string) => {
      setCurrentOrgId(orgId);
      const next = new URLSearchParams(searchParams);
      if (orgId) {
        next.set('org', orgId);
      } else {
        next.delete('org');
      }
      setSearchParams(next, { replace: true });
    },
    [searchParams, setSearchParams]
  );

  const handleNewProject = useCallback(() => {
    const suffix = currentOrgId ? `?org=${encodeURIComponent(currentOrgId)}` : '';
    navigate(`/projects/new${suffix}`);
  }, [currentOrgId, navigate]);

  const handleProjectsRetry = useCallback(() => {
    refetchProjects();
  }, [refetchProjects]);

  const showProjectsLoading = projectsLoading || (projectsFetching && projects.length === 0);
  const showProjectsError = projectsError && projects.length === 0;

  return (
    <WorkspaceShell
      sidebarContent={<ConsoleSidebar selectedId="projects" onNavigate={(p) => navigate(p)} />}
      documentTitle="Projects"
    >
      <div className="projects-page">
        <header className="projects-header">
          <div className="projects-header-left">
            <h1 className="projects-title animate-fade-in-up">Projects</h1>
            <p className="projects-subtitle animate-fade-in-up">
              Create a workspace where humans and agents collaborate in real time.
            </p>
          </div>

          <div className="projects-header-right">
            <OrgSwitcher organizations={organizations} currentOrgId={currentOrgId} onSelect={handleOrgSelect} />
            <button type="button" className="projects-new-button pressable" onClick={handleNewProject} data-haptic="light">
              New Project
            </button>
          </div>
        </header>

        <section className="projects-toolbar" aria-label="Project search">
          <label className="projects-search">
            <span className="projects-search-label">Search</span>
            <input
              className="projects-search-input"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Filter by name, slug, description…"
              autoComplete="off"
            />
          </label>
        </section>

        <section className="projects-grid" aria-label="Projects list">
          {showProjectsLoading ? (
            <>
              <div className="project-card skeleton animate-shimmer" />
              <div className="project-card skeleton animate-shimmer" />
              <div className="project-card skeleton animate-shimmer" />
            </>
          ) : showProjectsError ? (
            <div className="projects-empty projects-empty-error animate-fade-in-up" role="status" aria-live="polite">
              <h2 className="projects-empty-title">Syncing projects</h2>
              <p className="projects-empty-description">
                We hit a snag loading your projects. Give it a moment or retry now.
              </p>
              <button
                type="button"
                className="projects-new-button pressable"
                onClick={handleProjectsRetry}
                data-haptic="light"
              >
                Retry
              </button>
            </div>
          ) : filteredProjects.length > 0 ? (
            filteredProjects.map((project) => (
              <div
                key={project.id}
                className="project-card animate-fade-in-up"
              >
                <button
                  type="button"
                  className="project-card-main pressable"
                  onClick={() => navigate(`/projects/${project.id}`)}
                  data-haptic="light"
                  aria-label={`Open project ${project.name}`}
                >
                  <div className="project-card-header">
                    <h2 className="project-card-title">{project.name}</h2>
                    <span className={`project-visibility project-visibility-${project.visibility}`}>
                      {project.visibility}
                    </span>
                  </div>
                  {project.description && <p className="project-card-description">{project.description}</p>}
                  <div className="project-card-meta">
                    <span className="project-meta-item">Slug: {project.slug}</span>
                    <span className="project-meta-time">{getRelativeTime(project.updated_at)}</span>
                  </div>
                </button>
                <div className="project-card-actions">
                  <button
                    type="button"
                    className="project-action-button pressable"
                    onClick={(e) => {
                      e.stopPropagation();
                      navigate(`/projects/${project.id}/settings`);
                    }}
                    data-haptic="light"
                    aria-label={`Settings for ${project.name}`}
                    title="Project Settings"
                  >
                    ⚙️
                  </button>
                </div>
              </div>
            ))
          ) : (
            <div className="projects-empty animate-fade-in-up">
              <h2 className="projects-empty-title">No projects yet</h2>
              <p className="projects-empty-description">Create your first project to get started.</p>
              <button type="button" className="projects-new-button pressable" onClick={handleNewProject} data-haptic="light">
                Create Project
              </button>
            </div>
          )}
        </section>
      </div>
    </WorkspaceShell>
  );
}
