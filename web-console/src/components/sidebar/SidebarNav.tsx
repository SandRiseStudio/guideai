import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useLocation } from 'react-router-dom';
import { useProjects, type Project } from '../../api/dashboard';
import { useProjectAgents } from '../../api/agentRegistry';
import { useBoards } from '../../api/boards';
import { useOrgContext } from '../../store/orgContextStore';
import { loadProjectSortPreference, sortProjects } from '../../utils/projectSort';
import './SidebarNav.css';

const STORAGE_KEY_SECTIONS = 'guideai.sidebar.sections';
const STORAGE_KEY_PROJECT = 'guideai.sidebar.expandedProject';

type SectionState = {
  home: boolean;
  projects: boolean;
  tools: boolean;
};

interface SidebarNavProps {
  onNavigate: (path: string) => void;
  selectedId?: string;
}

interface NavItemProps {
  label: string;
  icon: React.ReactNode;
  active?: boolean;
  nested?: boolean;
  onClick: () => void;
  trailing?: React.ReactNode;
  onKeyDown?: (event: React.KeyboardEvent<HTMLButtonElement>) => void;
  role?: string;
  level?: number;
  expanded?: boolean;
  controls?: string;
}

interface SidebarProjectNodeProps {
  project: Project;
  expanded: boolean;
  isActive: boolean;
  onToggle: (projectId: string) => void;
  onNavigate: (path: string) => void;
  pathname: string;
  onMoveFocus: (current: HTMLElement, delta: number) => void;
  activeAgentCount: number;
}

const CountBadge = ({ count }: { count: number }) => (
  <span className="sidebar-count-badge">{count}</span>
);

const HomeIcon = () => (
  <svg className="sidebar-nav-icon" viewBox="0 0 16 16" fill="none">
    <path d="M2.5 7.2L8 2.8l5.5 4.4v5.3a1 1 0 0 1-1 1h-3v-3.3H6.5V13.5h-3a1 1 0 0 1-1-1V7.2z" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
  </svg>
);

const OrgIcon = () => (
  <svg className="sidebar-nav-icon" viewBox="0 0 16 16" fill="none">
    <rect x="2" y="3" width="12" height="10" rx="2" stroke="currentColor" strokeWidth="1.5" />
    <path d="M5 6h2M9 6h2M5 9h2M9 9h2" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
  </svg>
);

const AgentIcon = () => (
  <svg className="sidebar-nav-icon" viewBox="0 0 16 16" fill="none">
    <circle cx="8" cy="5" r="3" stroke="currentColor" strokeWidth="1.5" />
    <path d="M3 14c0-2.761 2.239-5 5-5s5 2.239 5 5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
  </svg>
);

const ProjectIcon = () => (
  <svg className="sidebar-nav-icon" viewBox="0 0 16 16" fill="none">
    <rect x="2" y="3" width="12" height="10" rx="2" stroke="currentColor" strokeWidth="1.5" />
    <path d="M2 6.5h12" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
  </svg>
);

const BoardIcon = () => (
  <svg className="sidebar-nav-icon" viewBox="0 0 16 16" fill="none">
    <rect x="2" y="2.5" width="12" height="11" rx="2" stroke="currentColor" strokeWidth="1.5" />
    <path d="M6 2.5v11M10 2.5v11" stroke="currentColor" strokeWidth="1.5" />
  </svg>
);

const DefaultBoardIcon = () => (
  <svg className="sidebar-nav-icon" viewBox="0 0 16 16" fill="none">
    <path d="M8 2.5l1.4 2.9 3.1.5-2.2 2.2.5 3.1L8 9.9l-2.8 1.5.5-3.1-2.2-2.2 3.1-.5L8 2.5Z" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" />
  </svg>
);

const SettingsIcon = () => (
  <svg className="sidebar-nav-icon" viewBox="0 0 16 16" fill="none">
    <path d="M8 5.5a2.5 2.5 0 1 0 0 5 2.5 2.5 0 0 0 0-5Z" stroke="currentColor" strokeWidth="1.5" />
    <path d="M13.2 8.8v-1.6l-1.1-.3a4.5 4.5 0 0 0-.4-.9l.6-1-1.1-1.1-1 .6c-.3-.2-.6-.3-.9-.4L8.8 2.8H7.2l-.3 1.1c-.3.1-.6.2-.9.4l-1-.6-1.1 1.1.6 1c-.2.3-.3.6-.4.9l-1.1.3v1.6l1.1.3c.1.3.2.6.4.9l-.6 1 1.1 1.1 1-.6c.3.2.6.3.9.4l.3 1.1h1.6l.3-1.1c.3-.1.6-.2.9-.4l1 .6 1.1-1.1-.6-1c.2-.3.3-.6.4-.9l1.1-.3Z" stroke="currentColor" strokeWidth="1.2" strokeLinejoin="round" />
  </svg>
);

const SearchIcon = () => (
  <svg className="sidebar-nav-icon" viewBox="0 0 16 16" fill="none">
    <circle cx="7" cy="7" r="4.5" stroke="currentColor" strokeWidth="1.5" />
    <path d="M10.5 10.5L13.5 13.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
  </svg>
);

const SparkIcon = () => (
  <svg className="sidebar-nav-icon" viewBox="0 0 16 16" fill="none">
    <path d="M8 2.5l1.2 3.3L12.5 7 9.2 8.2 8 11.5 6.8 8.2 3.5 7l3.3-1.2L8 2.5Z" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
  </svg>
);

const ChevronIcon = ({ expanded }: { expanded: boolean }) => (
  <svg className={`sidebar-chevron ${expanded ? 'expanded' : ''}`} viewBox="0 0 16 16" fill="none">
    <path d="M6 3.5L10.5 8 6 12.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

const PlusIcon = () => (
  <svg className="sidebar-plus-icon" viewBox="0 0 16 16" fill="none">
    <path d="M8 3v10M3 8h10" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
  </svg>
);

function loadSectionState(): SectionState {
  if (typeof window === 'undefined') {
    return { home: false, projects: false, tools: true };
  }

  try {
    const raw = window.localStorage.getItem(STORAGE_KEY_SECTIONS);
    if (!raw) return { home: false, projects: false, tools: true };
    return { ...{ home: false, projects: false, tools: true }, ...(JSON.parse(raw) as Partial<SectionState>) };
  } catch {
    return { home: false, projects: false, tools: true };
  }
}

function loadExpandedProject(): string | null {
  if (typeof window === 'undefined') return null;
  return window.localStorage.getItem(STORAGE_KEY_PROJECT);
}

const NavItem = memo(function NavItem({ label, icon, active, nested, onClick, trailing, onKeyDown, role, level, expanded, controls }: NavItemProps) {
  return (
    <button
      type="button"
      className={`sidebar-nav-item ${active ? 'active' : ''} ${nested ? 'nested' : ''}`}
      onClick={onClick}
      onKeyDown={onKeyDown}
      aria-current={active ? 'page' : undefined}
      aria-expanded={expanded}
      aria-controls={controls}
      role={role}
      aria-level={level}
      data-sidebar-focusable="true"
    >
      <span className="sidebar-nav-item-leading">
        {icon}
        <span className="sidebar-nav-label">{label}</span>
      </span>
      {trailing && <span className="sidebar-nav-trailing">{trailing}</span>}
    </button>
  );
});

const SidebarProjectNode = memo(function SidebarProjectNode({
  project,
  expanded,
  isActive,
  onToggle,
  onNavigate,
  pathname,
  onMoveFocus,
  activeAgentCount,
}: SidebarProjectNodeProps) {
  const { data: boards = [], isLoading } = useBoards(expanded ? project.id : undefined);
  const projectPath = `/projects/${project.id}`;
  const settingsPath = `/projects/${project.id}/settings`;
  const primaryBoard = boards.find((board) => board.is_default) ?? boards[0];
  const createBoardPath = `${projectPath}?newBoard=1`;

  const isProjectRoute = pathname === projectPath || pathname.startsWith(`${projectPath}/`);
  const childGroupId = `sidebar-project-${project.id}`;

  const handleProjectKeyDown = useCallback((event: React.KeyboardEvent<HTMLButtonElement>) => {
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      onMoveFocus(event.currentTarget, 1);
      return;
    }
    if (event.key === 'ArrowUp') {
      event.preventDefault();
      onMoveFocus(event.currentTarget, -1);
      return;
    }
    if (event.key === 'ArrowRight' && !expanded) {
      event.preventDefault();
      onToggle(project.id);
      return;
    }
    if (event.key === 'ArrowLeft' && expanded) {
      event.preventDefault();
      onToggle(project.id);
    }
  }, [expanded, onMoveFocus, onToggle, project.id]);

  return (
    <div className="sidebar-project-node">
      <NavItem
        label={project.name}
        icon={<ProjectIcon />}
        active={isActive || isProjectRoute}
        onClick={() => onToggle(project.id)}
        onKeyDown={handleProjectKeyDown}
        trailing={
          <span className="sidebar-project-summary">
            {activeAgentCount > 0 && <CountBadge count={activeAgentCount} />}
            {boards.length > 0 && <CountBadge count={boards.length} />}
            <span
              role="button"
              tabIndex={0}
              className="sidebar-project-action"
              aria-label={`Create a board in ${project.name}`}
              title="Create board"
              onClick={(event) => {
                event.stopPropagation();
                onNavigate(createBoardPath);
              }}
              onKeyDown={(event) => {
                if (event.key === 'Enter' || event.key === ' ') {
                  event.preventDefault();
                  event.stopPropagation();
                  onNavigate(createBoardPath);
                }
              }}
            >
              <PlusIcon />
            </span>
            <ChevronIcon expanded={expanded} />
          </span>
        }
        role="treeitem"
        level={1}
        expanded={expanded}
        controls={childGroupId}
      />

      <div id={childGroupId} className={`sidebar-project-children ${expanded ? 'expanded' : ''}`} role="group">
        <div className="sidebar-project-children-inner">
          <NavItem
            label="Overview"
            icon={<ProjectIcon />}
            nested
            active={pathname === projectPath}
            onClick={() => onNavigate(projectPath)}
            onKeyDown={(event) => {
              if (event.key === 'ArrowDown') {
                event.preventDefault();
                onMoveFocus(event.currentTarget, 1);
              } else if (event.key === 'ArrowUp') {
                event.preventDefault();
                onMoveFocus(event.currentTarget, -1);
              } else if (event.key === 'ArrowLeft') {
                event.preventDefault();
                onToggle(project.id);
              } else if (event.key === 'ArrowRight' && primaryBoard) {
                event.preventDefault();
                onNavigate(`/projects/${project.id}/boards/${primaryBoard.board_id}`);
              }
            }}
            role="treeitem"
            level={2}
          />

          {expanded && isLoading ? (
            <div className="sidebar-project-loading" aria-hidden="true">
              <span className="sidebar-project-skeleton animate-shimmer" />
              <span className="sidebar-project-skeleton animate-shimmer" />
            </div>
          ) : (
            boards.map((board) => {
              const boardPath = `/projects/${project.id}/boards/${board.board_id}`;
              const boardActive = pathname === boardPath || pathname.startsWith(`${boardPath}/items/`);
              return (
                <NavItem
                  key={board.board_id}
                  label={board.name}
                  icon={board.is_default ? <DefaultBoardIcon /> : <BoardIcon />}
                  nested
                  active={boardActive}
                  onClick={() => onNavigate(boardPath)}
                  onKeyDown={(event) => {
                    if (event.key === 'ArrowDown') {
                      event.preventDefault();
                      onMoveFocus(event.currentTarget, 1);
                    } else if (event.key === 'ArrowUp') {
                      event.preventDefault();
                      onMoveFocus(event.currentTarget, -1);
                    } else if (event.key === 'ArrowLeft') {
                      event.preventDefault();
                      onToggle(project.id);
                    }
                  }}
                  role="treeitem"
                  level={2}
                />
              );
            })
          )}

          <NavItem
            label="Settings"
            icon={<SettingsIcon />}
            nested
            active={pathname === settingsPath}
            onClick={() => onNavigate(settingsPath)}
            onKeyDown={(event) => {
              if (event.key === 'ArrowDown') {
                event.preventDefault();
                onMoveFocus(event.currentTarget, 1);
              } else if (event.key === 'ArrowUp') {
                event.preventDefault();
                onMoveFocus(event.currentTarget, -1);
              } else if (event.key === 'ArrowLeft') {
                event.preventDefault();
                onToggle(project.id);
              }
            }}
            role="treeitem"
            level={2}
          />
        </div>
      </div>
    </div>
  );
});

export const SidebarNav = memo(function SidebarNav({ onNavigate }: SidebarNavProps) {
  const location = useLocation();
  const containerRef = useRef<HTMLDivElement | null>(null);
  const { currentOrgId } = useOrgContext();
  const [sections, setSections] = useState<SectionState>(() => loadSectionState());
  const [expandedProjectId, setExpandedProjectId] = useState<string | null>(() => loadExpandedProject());

  const { data: projects = [] } = useProjects(currentOrgId ?? undefined);
  const { data: agents = [] } = useProjectAgents(true);

  const scopedProjects = useMemo(
    () => (currentOrgId ? projects : projects.filter((project) => !project.org_id)),
    [currentOrgId, projects]
  );

  const sortedProjects = useMemo(
    () => sortProjects(scopedProjects, loadProjectSortPreference()),
    [scopedProjects]
  );

  const activeAgentCounts = useMemo(() => {
    const counts = new Map<string, number>();
    agents.forEach((agent) => {
      if (!agent.project_id) return;
      if (agent.status !== 'active' && agent.status !== 'busy') return;
      counts.set(agent.project_id, (counts.get(agent.project_id) ?? 0) + 1);
    });
    return counts;
  }, [agents]);

  useEffect(() => {
    window.localStorage.setItem(STORAGE_KEY_SECTIONS, JSON.stringify(sections));
  }, [sections]);

  useEffect(() => {
    if (expandedProjectId) {
      window.localStorage.setItem(STORAGE_KEY_PROJECT, expandedProjectId);
    } else {
      window.localStorage.removeItem(STORAGE_KEY_PROJECT);
    }
  }, [expandedProjectId]);

  const newProjectPath = useMemo(() => {
    return currentOrgId ? `/projects/new?org=${encodeURIComponent(currentOrgId)}` : '/projects/new';
  }, [currentOrgId]);

  const toggleSection = useCallback((section: keyof SectionState) => {
    setSections((prev) => ({ ...prev, [section]: !prev[section] }));
  }, []);

  const toggleProject = useCallback((projectId: string) => {
    setExpandedProjectId((prev) => (prev === projectId ? null : projectId));
  }, []);

  const moveFocus = useCallback((current: HTMLElement, delta: number) => {
    const nodes = Array.from(
      containerRef.current?.querySelectorAll<HTMLElement>('[data-sidebar-focusable="true"]') ?? []
    );
    const currentIndex = nodes.indexOf(current);
    if (currentIndex === -1) return;
    const next = nodes[currentIndex + delta];
    next?.focus();
  }, []);

  const pathname = location.pathname;
  const routeProjectId = useMemo(() => {
    const match = pathname.match(/^\/projects\/([^/]+)/);
    if (!match?.[1] || match[1] === 'new') {
      return null;
    }
    return match[1];
  }, [pathname]);

  const visibleSections = useMemo(
    () => ({
      ...sections,
      tools: pathname.startsWith('/bci') ? false : sections.tools,
      projects: pathname.startsWith('/projects') ? false : sections.projects,
    }),
    [pathname, sections]
  );

  const activeExpandedProjectId = routeProjectId ?? expandedProjectId;

  return (
    <div className="sidebar-nav" role="tree" aria-label="Primary navigation" ref={containerRef}>
      <div className="sidebar-section">
        <button
          type="button"
          className="sidebar-section-header"
          onClick={() => toggleSection('home')}
          onKeyDown={(event) => {
            if (event.key === 'ArrowDown') {
              event.preventDefault();
              moveFocus(event.currentTarget, 1);
            } else if (event.key === 'ArrowUp') {
              event.preventDefault();
              moveFocus(event.currentTarget, -1);
            } else if (event.key === 'ArrowLeft' && !visibleSections.home) {
              event.preventDefault();
              toggleSection('home');
            } else if (event.key === 'ArrowRight' && visibleSections.home) {
              event.preventDefault();
              toggleSection('home');
            }
          }}
          data-sidebar-focusable="true"
          role="treeitem"
          aria-expanded={!visibleSections.home}
          aria-level={1}
        >
          <span>Home</span>
          <ChevronIcon expanded={!visibleSections.home} />
        </button>
        <div className={`sidebar-section-body ${visibleSections.home ? 'collapsed' : ''}`}>
          <div className="sidebar-section-body-inner">
            <NavItem
              label="Dashboard"
              icon={<HomeIcon />}
              active={pathname === '/'}
              onClick={() => onNavigate('/')}
              onKeyDown={(event) => {
                if (event.key === 'ArrowDown') {
                  event.preventDefault();
                  moveFocus(event.currentTarget, 1);
                } else if (event.key === 'ArrowUp') {
                  event.preventDefault();
                  moveFocus(event.currentTarget, -1);
                } else if (event.key === 'ArrowLeft') {
                  event.preventDefault();
                  toggleSection('home');
                }
              }}
              role="treeitem"
              level={1}
            />
          </div>
        </div>
      </div>

      <div className="sidebar-section">
        <div className="sidebar-section-body">
          <div className="sidebar-section-body-inner">
            <NavItem
              label="Organizations"
              icon={<OrgIcon />}
              active={pathname.startsWith('/orgs')}
              onClick={() => onNavigate('/orgs')}
              onKeyDown={(event) => {
                if (event.key === 'ArrowDown') {
                  event.preventDefault();
                  moveFocus(event.currentTarget, 1);
                } else if (event.key === 'ArrowUp') {
                  event.preventDefault();
                  moveFocus(event.currentTarget, -1);
                }
              }}
              role="treeitem"
              level={1}
            />
            <NavItem
              label="Agents"
              icon={<AgentIcon />}
              active={pathname.startsWith('/agents')}
              onClick={() => onNavigate('/agents')}
              onKeyDown={(event) => {
                if (event.key === 'ArrowDown') {
                  event.preventDefault();
                  moveFocus(event.currentTarget, 1);
                } else if (event.key === 'ArrowUp') {
                  event.preventDefault();
                  moveFocus(event.currentTarget, -1);
                }
              }}
              role="treeitem"
              level={1}
            />
          </div>
        </div>
      </div>

      <div className="sidebar-section sidebar-section-projects">
        <div className="sidebar-section-header sidebar-section-header-with-action">
          <button
            type="button"
            className="sidebar-section-toggle"
            onClick={() => toggleSection('projects')}
            onKeyDown={(event) => {
              if (event.key === 'ArrowDown') {
                event.preventDefault();
                moveFocus(event.currentTarget, 1);
              } else if (event.key === 'ArrowUp') {
                event.preventDefault();
                moveFocus(event.currentTarget, -1);
              } else if (event.key === 'ArrowLeft' && !visibleSections.projects) {
                event.preventDefault();
                toggleSection('projects');
              } else if (event.key === 'ArrowRight' && visibleSections.projects) {
                event.preventDefault();
                toggleSection('projects');
              }
            }}
            data-sidebar-focusable="true"
            role="treeitem"
            aria-expanded={!visibleSections.projects}
            aria-level={1}
          >
            <span>Projects</span>
            <ChevronIcon expanded={!visibleSections.projects} />
          </button>
          <button
            type="button"
            className="sidebar-section-action"
            onClick={() => onNavigate(newProjectPath)}
            aria-label="Create project"
            title="Create project"
          >
            <PlusIcon />
          </button>
        </div>
        <div className={`sidebar-section-body ${visibleSections.projects ? 'collapsed' : ''}`}>
          <div className="sidebar-section-body-inner">
            <NavItem
              label="All Projects"
              icon={<ProjectIcon />}
              active={pathname === '/projects' || pathname === '/projects/new'}
              onClick={() => onNavigate('/projects')}
              onKeyDown={(event) => {
                if (event.key === 'ArrowDown') {
                  event.preventDefault();
                  moveFocus(event.currentTarget, 1);
                } else if (event.key === 'ArrowUp') {
                  event.preventDefault();
                  moveFocus(event.currentTarget, -1);
                }
              }}
              role="treeitem"
              level={1}
            />
            {sortedProjects.map((project) => {
              const isProjectRoute = pathname === `/projects/${project.id}` || pathname.startsWith(`/projects/${project.id}/`);
              return (
                <SidebarProjectNode
                  key={project.id}
                  project={project}
                  expanded={activeExpandedProjectId === project.id}
                  isActive={isProjectRoute}
                  onToggle={toggleProject}
                  onNavigate={onNavigate}
                  pathname={pathname}
                  onMoveFocus={moveFocus}
                  activeAgentCount={activeAgentCounts.get(project.id) ?? 0}
                />
              );
            })}
          </div>
        </div>
      </div>

      <div className="sidebar-section">
        <button
          type="button"
          className="sidebar-section-header"
          onClick={() => toggleSection('tools')}
          onKeyDown={(event) => {
            if (event.key === 'ArrowDown') {
              event.preventDefault();
              moveFocus(event.currentTarget, 1);
            } else if (event.key === 'ArrowUp') {
              event.preventDefault();
              moveFocus(event.currentTarget, -1);
            } else if (event.key === 'ArrowLeft' && !visibleSections.tools) {
              event.preventDefault();
              toggleSection('tools');
            } else if (event.key === 'ArrowRight' && visibleSections.tools) {
              event.preventDefault();
              toggleSection('tools');
            }
          }}
          data-sidebar-focusable="true"
          role="treeitem"
          aria-expanded={!visibleSections.tools}
          aria-level={1}
        >
          <span>Tools</span>
          <ChevronIcon expanded={!visibleSections.tools} />
        </button>
        <div className={`sidebar-section-body ${visibleSections.tools ? 'collapsed' : ''}`}>
          <div className="sidebar-section-body-inner">
            <NavItem
              label="Behavior Search"
              icon={<SearchIcon />}
              active={pathname === '/bci'}
              onClick={() => onNavigate('/bci')}
              onKeyDown={(event) => {
                if (event.key === 'ArrowDown') {
                  event.preventDefault();
                  moveFocus(event.currentTarget, 1);
                } else if (event.key === 'ArrowUp') {
                  event.preventDefault();
                  moveFocus(event.currentTarget, -1);
                }
              }}
              role="treeitem"
              level={1}
            />
            <NavItem
              label="Behavior Extraction"
              icon={<SparkIcon />}
              active={pathname === '/bci/extraction'}
              onClick={() => onNavigate('/bci/extraction')}
              onKeyDown={(event) => {
                if (event.key === 'ArrowDown') {
                  event.preventDefault();
                  moveFocus(event.currentTarget, 1);
                } else if (event.key === 'ArrowUp') {
                  event.preventDefault();
                  moveFocus(event.currentTarget, -1);
                }
              }}
              role="treeitem"
              level={1}
            />
          </div>
        </div>
      </div>
    </div>
  );
});
