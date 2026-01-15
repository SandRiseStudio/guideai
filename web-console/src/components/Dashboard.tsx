/**
 * Dashboard Component
 *
 * Landing page after login showing:
 * - Quick stats row (agents, runs, behaviors)
 * - Projects grid
 * - Active agents with status indicators
 * - Recent activity timeline
 * - Quick actions
 *
 * Uses WorkspaceShell for collaborative features.
 * Follows COLLAB_SAAS_REQUIREMENTS.md for UX: fast, floaty, smooth, animated.
 *
 * Following:
 * - behavior_validate_accessibility (Student)
 * - behavior_update_docs_after_changes (Student)
 */

import { memo, useCallback, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { WorkspaceShell } from './workspace/WorkspaceShell';
import { ConsoleSidebar } from './ConsoleSidebar';
import { orgContextStore, useOrgContext } from '../store/orgContextStore';
import {
  useDashboardStats,
  useOrganizations,
  useProjects,
  useAgents,
  useRecentRuns,
  type Project,
  type Agent,
  type Run,
  type AgentStatus,
} from '../api/dashboard';
import './Dashboard.css';

// ---------------------------------------------------------------------------
// Icons (inline for performance, GPU-friendly)
// ---------------------------------------------------------------------------

const ProjectIcon = () => (
  <svg className="stat-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
    <path d="M3 7a2 2 0 012-2h14a2 2 0 012 2v10a2 2 0 01-2 2H5a2 2 0 01-2-2V7z" />
    <path d="M3 7l9 6 9-6" />
  </svg>
);

const AgentIcon = () => (
  <svg className="stat-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
    <circle cx="12" cy="8" r="4" />
    <path d="M4 20c0-4.418 3.582-8 8-8s8 3.582 8 8" strokeLinecap="round" />
  </svg>
);

const RunIcon = () => (
  <svg className="stat-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
    <path d="M5 3l14 9-14 9V3z" strokeLinejoin="round" />
  </svg>
);

const BehaviorIcon = () => (
  <svg className="stat-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
    <path d="M12 2L2 7l10 5 10-5-10-5z" />
    <path d="M2 17l10 5 10-5" />
    <path d="M2 12l10 5 10-5" />
  </svg>
);

const PlusIcon = () => (
  <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
    <path d="M8 3v10M3 8h10" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
  </svg>
);

const ArrowRightIcon = () => (
  <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
    <path d="M3 7h8M8 4l3 3-3 3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

// ---------------------------------------------------------------------------
// Stat Card Component
// ---------------------------------------------------------------------------

interface StatCardProps {
  icon: React.ReactNode;
  label: string;
  value: number | string;
  subValue?: string;
  trend?: 'up' | 'down' | 'neutral';
  onClick?: () => void;
  isLoading?: boolean;
}

const StatCard = memo(function StatCard({
  icon,
  label,
  value,
  subValue,
  onClick,
  isLoading,
}: StatCardProps) {
  return (
    <button
      className={`stat-card pressable ${isLoading ? 'loading' : ''}`}
      onClick={onClick}
      disabled={!onClick}
      data-haptic="light"
    >
      <div className="stat-card-icon">{icon}</div>
      <div className="stat-card-content">
        <span className="stat-card-value">
          {isLoading ? <span className="skeleton-text animate-shimmer" /> : value}
        </span>
        <span className="stat-card-label">{label}</span>
        {subValue && <span className="stat-card-subvalue">{subValue}</span>}
      </div>
    </button>
  );
});

// ---------------------------------------------------------------------------
// Workspace Card Component
// ---------------------------------------------------------------------------

interface WorkspaceCardProps {
  title: string;
  subtitle: string;
  meta?: string;
  active?: boolean;
  variant?: 'personal' | 'org' | 'create';
  onClick: () => void;
}

const WorkspaceCard = memo(function WorkspaceCard({
  title,
  subtitle,
  meta,
  active,
  variant = 'org',
  onClick,
}: WorkspaceCardProps) {
  return (
    <button
      className={`workspace-card pressable ${active ? 'active' : ''} variant-${variant} animate-fade-in-up`}
      onClick={onClick}
      aria-pressed={active}
      data-haptic="light"
    >
      <div className="workspace-card-header">
        <span className="workspace-card-title">{title}</span>
        <span className="workspace-badge">
          {variant === 'personal' ? 'Personal' : variant === 'create' ? 'Create' : 'Org'}
        </span>
      </div>
      <span className="workspace-card-subtitle">{subtitle}</span>
      {meta && <span className="workspace-card-meta">{meta}</span>}
    </button>
  );
});

// ---------------------------------------------------------------------------
// Project Card Component
// ---------------------------------------------------------------------------

interface ProjectCardProps {
  project: Project;
  onClick: () => void;
}

const ProjectCard = memo(function ProjectCard({ project, onClick }: ProjectCardProps) {
  const relativeTime = getRelativeTime(project.updated_at);

  return (
    <button className="project-card pressable animate-fade-in-up" onClick={onClick} data-haptic="light">
      <div className="project-card-header">
        <h3 className="project-card-title">{project.name}</h3>
        <span className={`project-visibility project-visibility-${project.visibility}`}>
          {project.visibility}
        </span>
      </div>
      {project.description && (
        <p className="project-card-description">{project.description}</p>
      )}
      <div className="project-card-meta">
        <span className="project-meta-item">
          <AgentIcon />
          {project.agent_count ?? 0} agents
        </span>
        <span className="project-meta-item">
          <RunIcon />
          {project.run_count ?? 0} runs
        </span>
        <span className="project-meta-time">Updated {relativeTime}</span>
      </div>
    </button>
  );
});

// ---------------------------------------------------------------------------
// Agent Status Badge
// ---------------------------------------------------------------------------

const agentStatusConfig: Record<AgentStatus, { label: string; className: string }> = {
  active: { label: 'Active', className: 'status-active' },
  busy: { label: 'Busy', className: 'status-busy' },
  idle: { label: 'Idle', className: 'status-idle' },
  paused: { label: 'Paused', className: 'status-paused' },
  disabled: { label: 'Disabled', className: 'status-disabled' },
  archived: { label: 'Archived', className: 'status-archived' },
};

interface AgentRowProps {
  agent: Agent;
  onClick: () => void;
}

const AgentRow = memo(function AgentRow({ agent, onClick }: AgentRowProps) {
  const config = agentStatusConfig[agent.status] ?? agentStatusConfig.idle;
  const lastActive = agent.last_active_at ? getRelativeTime(agent.last_active_at) : 'Never';

  return (
    <button className="agent-row pressable" onClick={onClick} data-haptic="light">
      <div className="agent-row-avatar">
        {agent.name.charAt(0).toUpperCase()}
      </div>
      <div className="agent-row-info">
        <span className="agent-row-name">{agent.name}</span>
        <span className="agent-row-type">{agent.agent_type}</span>
      </div>
      <div className="agent-row-status">
        <span className={`status-badge ${config.className}`}>
          <span className="status-dot" />
          {config.label}
        </span>
      </div>
      <span className="agent-row-last-active">Last active {lastActive}</span>
    </button>
  );
});

// ---------------------------------------------------------------------------
// Run Status Badge
// ---------------------------------------------------------------------------

// Config for both uppercase (backend) and lowercase status values
const runStatusConfig: Record<string, { label: string; className: string }> = {
  PENDING: { label: 'Pending', className: 'run-status-pending' },
  RUNNING: { label: 'Running', className: 'run-status-running' },
  COMPLETED: { label: 'Completed', className: 'run-status-completed' },
  FAILED: { label: 'Failed', className: 'run-status-failed' },
  CANCELLED: { label: 'Cancelled', className: 'run-status-cancelled' },
  // Lowercase fallbacks for compatibility
  pending: { label: 'Pending', className: 'run-status-pending' },
  running: { label: 'Running', className: 'run-status-running' },
  completed: { label: 'Completed', className: 'run-status-completed' },
  failed: { label: 'Failed', className: 'run-status-failed' },
  cancelled: { label: 'Cancelled', className: 'run-status-cancelled' },
};

interface RunRowProps {
  run: Run;
  onClick: () => void;
}

const RunRow = memo(function RunRow({ run, onClick }: RunRowProps) {
  const config = runStatusConfig[run.status] ?? runStatusConfig.PENDING;
  const startedAt = getRelativeTime(run.started_at);
  const duration = run.duration_ms ? formatDuration(run.duration_ms) : null;

  return (
    <button className="run-row pressable" onClick={onClick} data-haptic="light">
      <div className={`run-row-status ${config.className}`}>
        <span className="status-indicator" />
      </div>
      <div className="run-row-info">
        <span className="run-row-name">{run.workflow_name ?? run.run_id.slice(0, 8)}</span>
        <span className="run-row-agent">{run.actor?.id ?? 'Unknown Actor'}</span>
      </div>
      <div className="run-row-meta">
        <span className="run-row-time">{startedAt}</span>
        {duration && <span className="run-row-duration">{duration}</span>}
      </div>
    </button>
  );
});

// ---------------------------------------------------------------------------
// Quick Action Button
// ---------------------------------------------------------------------------

interface QuickActionProps {
  icon: React.ReactNode;
  label: string;
  description: string;
  onClick: () => void;
}

const QuickAction = memo(function QuickAction({ icon, label, description, onClick }: QuickActionProps) {
  return (
    <button className="quick-action pressable animate-fade-in-up" onClick={onClick} data-haptic="medium">
      <div className="quick-action-icon">{icon}</div>
      <div className="quick-action-content">
        <span className="quick-action-label">{label}</span>
        <span className="quick-action-description">{description}</span>
      </div>
      <ArrowRightIcon />
    </button>
  );
});

// ---------------------------------------------------------------------------
// Empty State Component
// ---------------------------------------------------------------------------

interface EmptyStateProps {
  title: string;
  description: string;
  actionLabel?: string;
  onAction?: () => void;
}

const EmptyState = memo(function EmptyState({
  title,
  description,
  actionLabel,
  onAction,
}: EmptyStateProps) {
  return (
    <div className="empty-state animate-fade-in-up">
      <h3 className="empty-state-title">{title}</h3>
      <p className="empty-state-description">{description}</p>
      {actionLabel && onAction && (
        <button className="empty-state-action pressable" onClick={onAction} data-haptic="medium">
          <PlusIcon />
          {actionLabel}
        </button>
      )}
    </div>
  );
});

// ---------------------------------------------------------------------------
// Skeleton Loading Components
// ---------------------------------------------------------------------------

const StatCardSkeleton = () => (
  <div className="stat-card skeleton">
    <div className="skeleton-icon animate-shimmer" />
    <div className="stat-card-content">
      <span className="skeleton-text skeleton-value animate-shimmer" />
      <span className="skeleton-text skeleton-label animate-shimmer" />
    </div>
  </div>
);

const ProjectCardSkeleton = () => (
  <div className="project-card skeleton">
    <div className="project-card-header">
      <span className="skeleton-text skeleton-title animate-shimmer" />
    </div>
    <span className="skeleton-text skeleton-description animate-shimmer" />
    <span className="skeleton-text skeleton-meta animate-shimmer" />
  </div>
);

// ---------------------------------------------------------------------------
// Utility Functions
// ---------------------------------------------------------------------------

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

function formatDuration(ms: number): string {
  const secs = Math.floor(ms / 1000);
  const mins = Math.floor(secs / 60);
  const hours = Math.floor(mins / 60);

  if (hours > 0) return `${hours}h ${mins % 60}m`;
  if (mins > 0) return `${mins}m ${secs % 60}s`;
  return `${secs}s`;
}

// ---------------------------------------------------------------------------
// Dashboard Sidebar Content
// ---------------------------------------------------------------------------

const DashboardSidebar = memo(function DashboardSidebar({ onNavigate }: { onNavigate: (path: string) => void }) {
  return <ConsoleSidebar selectedId="dashboard" onNavigate={onNavigate} />;
});

// ---------------------------------------------------------------------------
// Main Dashboard Component
// ---------------------------------------------------------------------------

export function Dashboard() {
  const navigate = useNavigate();
  const { currentOrgId } = useOrgContext();

  // API hooks
  const { data: stats, isLoading: statsLoading } = useDashboardStats();
  const { data: organizations = [] } = useOrganizations();
  const {
    data: projects = [],
    isLoading: projectsLoading,
    isFetching: projectsFetching,
    isError: projectsError,
    refetch: refetchProjects,
  } = useProjects(currentOrgId ?? undefined);
  const {
    data: agents = [],
    isLoading: agentsLoading,
    isFetching: agentsFetching,
    isError: agentsError,
  } = useAgents(currentOrgId ?? undefined);
  const {
    data: recentRuns = [],
    isLoading: runsLoading,
    isFetching: runsFetching,
    isError: runsError,
  } = useRecentRuns(5);
  const sortedOrganizations = useMemo(
    () => [...organizations].sort((a, b) => a.name.localeCompare(b.name)),
    [organizations]
  );

  // Navigation handlers
  const handleNavigate = useCallback((path: string) => {
    navigate(path);
  }, [navigate]);

  const newProjectPath = useMemo(() => {
    return currentOrgId ? `/projects/new?org=${encodeURIComponent(currentOrgId)}` : '/projects/new';
  }, [currentOrgId]);

  const scopedProjects = useMemo(
    () => (currentOrgId ? projects : projects.filter((project) => !project.org_id)),
    [currentOrgId, projects]
  );
  const scopedAgents = useMemo(
    () => (currentOrgId ? agents : agents.filter((agent) => !agent.org_id)),
    [currentOrgId, agents]
  );
  const scopedStats = useMemo(() => {
    if (!stats) return undefined;
    const activeAgents = scopedAgents.filter((agent) => agent.status === 'active').length;
    const busyAgents = scopedAgents.filter((agent) => agent.status === 'busy').length;
    return {
      ...stats,
      total_projects: scopedProjects.length,
      total_agents: scopedAgents.length,
      active_agents: activeAgents,
      busy_agents: busyAgents,
    };
  }, [scopedAgents, scopedProjects, stats]);

  const handleProjectClick = useCallback((project: Project) => {
    navigate(`/projects/${project.id}`);
  }, [navigate]);

  const handleAgentClick = useCallback((agent: Agent) => {
    const config = (agent.config ?? {}) as Record<string, unknown>;
    const registryAgentId = typeof config.registry_agent_id === 'string' ? config.registry_agent_id : null;
    navigate(registryAgentId ? `/agents/${registryAgentId}` : '/agents');
  }, [navigate]);

  const handleRunClick = useCallback((run: Run) => {
    // TODO: Wire run detail page when /runs routes land.
    navigate(`/runs/${run.run_id}`);
  }, [navigate]);

  // Limit displayed items
  const displayedProjects = scopedProjects.slice(0, 6);
  const displayedAgents = scopedAgents.slice(0, 5);
  const showProjectsLoading = projectsLoading
    || (projectsFetching && scopedProjects.length === 0)
    || (projectsError && scopedProjects.length === 0);
  const showAgentsLoading = agentsLoading
    || (agentsFetching && scopedAgents.length === 0)
    || (agentsError && scopedAgents.length === 0);
  const showRunsLoading = runsLoading
    || (runsFetching && recentRuns.length === 0)
    || (runsError && recentRuns.length === 0);
  const projectsBannerTitle = projectsError ? 'Reconnecting to projects' : 'Syncing workspace';
  const projectsBannerDescription = projectsError
    ? 'We hit a bump loading projects. Retrying now.'
    : 'Pulling your projects into focus.';
  const projectsBannerClassName = projectsError
    ? 'projects-loading-banner is-error animate-fade-in-up'
    : 'projects-loading-banner animate-fade-in-up';

  const handleProjectsRetry = useCallback(() => {
    refetchProjects();
  }, [refetchProjects]);

  return (
    <WorkspaceShell
      sidebarContent={<DashboardSidebar onNavigate={handleNavigate} />}
      documentTitle="Dashboard"
    >
      <div className="dashboard">
        {/* Header */}
        <header className="dashboard-header">
          <div className="dashboard-header-left">
            <h1 className="dashboard-title animate-fade-in-up">Dashboard</h1>
          </div>
        </header>

        {/* Workspaces */}
        <section className="dashboard-section dashboard-workspaces" aria-label="Workspaces">
          <div className="section-header">
            <h2 className="section-title">Workspaces</h2>
            <button
              className="section-action pressable"
              onClick={() => handleNavigate('/orgs')}
              data-haptic="light"
            >
              Manage orgs
              <ArrowRightIcon />
            </button>
          </div>
          <div className="workspace-cards">
            <WorkspaceCard
              title="Personal workspace"
              subtitle="Projects you own outside any organization."
              meta={currentOrgId ? 'Switch to personal' : 'Selected'}
              active={!currentOrgId}
              variant="personal"
              onClick={() => orgContextStore.setCurrentOrgId(null)}
            />
            {sortedOrganizations.length === 0 ? (
              <WorkspaceCard
                title="Create an organization"
                subtitle="Invite teammates and manage shared work."
                meta="Start collaborating"
                variant="create"
                onClick={() => handleNavigate('/orgs')}
              />
            ) : (
              sortedOrganizations.map((org) => (
                <WorkspaceCard
                  key={org.id}
                  title={org.name}
                  subtitle={org.slug}
                  meta={
                    org.member_count == null
                      ? 'Members unknown'
                      : `${org.member_count} member${org.member_count === 1 ? '' : 's'}`
                  }
                  active={currentOrgId === org.id}
                  variant="org"
                  onClick={() => orgContextStore.setCurrentOrgId(org.id)}
                />
              ))
            )}
          </div>
        </section>

        {/* Stats Row */}
        <section className="dashboard-stats" aria-label="Key metrics">
          {statsLoading ? (
            <>
              <StatCardSkeleton />
              <StatCardSkeleton />
              <StatCardSkeleton />
              <StatCardSkeleton />
            </>
          ) : (
            <>
              <StatCard
                icon={<ProjectIcon />}
                label="Projects"
                value={scopedStats?.total_projects ?? 0}
                onClick={() => handleNavigate('/projects')}
              />
              <StatCard
                icon={<AgentIcon />}
                label="Agents"
                value={scopedStats?.total_agents ?? 0}
                subValue={`${scopedStats?.active_agents ?? 0} active`}
                onClick={() => handleNavigate('/agents')}
              />
              <StatCard
                icon={<RunIcon />}
                label="Runs Today"
                value={stats?.completed_runs_today ?? 0}
                subValue={`${stats?.running_runs ?? 0} running`}
                onClick={() => handleNavigate('/runs')}
              />
              <StatCard
                icon={<BehaviorIcon />}
                label="Behaviors"
                value={stats?.total_behaviors ?? 0}
                onClick={() => handleNavigate('/bci')}
              />
            </>
          )}
        </section>

        {/* Main Content Grid */}
        <div className="dashboard-grid">
          {/* Projects Section */}
          <section className="dashboard-section dashboard-projects" aria-label="Projects">
            <div className="section-header">
              <h2 className="section-title">Projects</h2>
              <button
                className="section-action pressable"
                onClick={() => handleNavigate(newProjectPath)}
                data-haptic="light"
              >
                <PlusIcon />
                New Project
              </button>
            </div>
            <div className="projects-grid">
              {showProjectsLoading ? (
                <>
                  <div className={projectsBannerClassName} role="status" aria-live="polite">
                    <span className="projects-loading-dot animate-pulse" />
                    <div className="projects-loading-text">
                      <span className="projects-loading-title">{projectsBannerTitle}</span>
                      <span className="projects-loading-description">{projectsBannerDescription}</span>
                    </div>
                    {projectsError && (
                      <button
                        type="button"
                        className="projects-loading-action pressable"
                        onClick={handleProjectsRetry}
                        data-haptic="light"
                      >
                        Retry
                      </button>
                    )}
                  </div>
                  <ProjectCardSkeleton />
                  <ProjectCardSkeleton />
                  <ProjectCardSkeleton />
                </>
              ) : displayedProjects.length > 0 ? (
                displayedProjects.map((project) => (
                  <ProjectCard
                    key={project.id}
                    project={project}
                    onClick={() => handleProjectClick(project)}
                  />
                ))
              ) : (
                <EmptyState
                  title="No projects yet"
                  description="Create your first project to get started"
                  actionLabel="Create Project"
                  onAction={() => handleNavigate(newProjectPath)}
                />
              )}
            </div>
          </section>

          {/* Active Agents Section */}
          <section className="dashboard-section dashboard-agents" aria-label="Active agents">
            <div className="section-header">
              <h2 className="section-title">Agents</h2>
              <button
                className="section-action pressable"
                onClick={() => handleNavigate('/agents')}
                data-haptic="light"
              >
                View All
                <ArrowRightIcon />
              </button>
            </div>
            <div className="agents-list">
              {showAgentsLoading ? (
                <div className="loading-placeholder animate-shimmer" />
              ) : displayedAgents.length > 0 ? (
                displayedAgents.map((agent) => (
                  <AgentRow
                    key={agent.id}
                    agent={agent}
                    onClick={() => handleAgentClick(agent)}
                  />
                ))
              ) : (
                <EmptyState
                  title="No agents configured"
                  description="Set up agents to automate your workflows"
                  actionLabel="Create Agent"
                  onAction={() => handleNavigate('/agents/new')}
                />
              )}
            </div>
          </section>

          {/* Recent Activity Section */}
          <section className="dashboard-section dashboard-activity" aria-label="Recent activity">
            <div className="section-header">
              <h2 className="section-title">Recent Runs</h2>
              <button
                className="section-action pressable"
                onClick={() => handleNavigate('/runs')}
                data-haptic="light"
              >
                View All
                <ArrowRightIcon />
              </button>
            </div>
            <div className="runs-list">
              {showRunsLoading ? (
                <div className="loading-placeholder animate-shimmer" />
              ) : recentRuns.length > 0 ? (
                recentRuns.map((run) => (
                  <RunRow
                    key={run.run_id}
                    run={run}
                    onClick={() => handleRunClick(run)}
                  />
                ))
              ) : (
                <EmptyState
                  title="No recent runs"
                  description="Runs will appear here once agents start executing"
                />
              )}
            </div>
          </section>

          {/* Quick Actions Section */}
          <section className="dashboard-section dashboard-quick-actions" aria-label="Quick actions">
            <div className="section-header">
              <h2 className="section-title">Quick Actions</h2>
            </div>
            <div className="quick-actions-list">
              <QuickAction
                icon={<BehaviorIcon />}
                label="BCI Query"
                description="Search behaviors with natural language"
                onClick={() => handleNavigate('/bci')}
              />
              <QuickAction
                icon={<PlusIcon />}
                label="Extract Behaviors"
                description="Extract new behaviors from traces"
                onClick={() => handleNavigate('/extraction')}
              />
              <QuickAction
                icon={<AgentIcon />}
                label="Create Agent"
                description="Configure a new AI agent"
                onClick={() => handleNavigate('/agents/new')}
              />
              <QuickAction
                icon={<ProjectIcon />}
                label="New Project"
                description="Start a new project workspace"
                onClick={() => handleNavigate(newProjectPath)}
              />
            </div>
          </section>
        </div>
      </div>
    </WorkspaceShell>
  );
}

export default Dashboard;
