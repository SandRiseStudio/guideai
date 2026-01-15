/**
 * WorkspaceShell Component
 *
 * High-performance collaborative workspace shell with:
 * - Smooth sidebar collapse animation
 * - Presence indicators
 * - Command palette ready
 * - Optimized rendering via memo + refs
 */

import React, { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useCollabStore, collabStore, usePresenceList } from '../../store/collabStore';
import { useAuth } from '../../auth';
import { useOrganizations } from '../../api/dashboard';
import { OrgSwitcher } from '../OrgSwitcher';
import { orgContextStore, useOrgContext } from '../../store/orgContextStore';
import './WorkspaceShell.css';

// ---------------------------------------------------------------------------
// Presence Avatar Component
// ---------------------------------------------------------------------------

interface PresenceAvatarProps {
  name: string;
  color: string;
  status: 'active' | 'idle' | 'away' | 'disconnected';
  showStatus?: boolean;
}

const PresenceAvatar = memo(function PresenceAvatar({
  name,
  color,
  status,
  showStatus = true,
}: PresenceAvatarProps) {
  const initials = name
    .split(' ')
    .map((n) => n[0])
    .join('')
    .toUpperCase()
    .slice(0, 2);

  return (
    <div className="presence-avatar" style={{ '--avatar-color': color } as React.CSSProperties}>
      <span className="presence-avatar-initials">{initials}</span>
      {showStatus && (
        <span
          className={`presence-avatar-status presence-status-${status}`}
          aria-label={`Status: ${status}`}
        />
      )}
    </div>
  );
});

// ---------------------------------------------------------------------------
// Sidebar Component
// ---------------------------------------------------------------------------

interface SidebarProps {
  collapsed: boolean;
  onToggle: () => void;
  children?: React.ReactNode;
}

const Sidebar = memo(function Sidebar({ collapsed, onToggle, children }: SidebarProps) {
  const sidebarRef = useRef<HTMLElement>(null);

  return (
    <aside
      ref={sidebarRef}
      className={`workspace-sidebar ${collapsed ? 'collapsed' : ''}`}
      aria-label="Workspace navigation"
    >
      <div className="sidebar-header">
        <button
          className="sidebar-toggle pressable"
          onClick={onToggle}
          aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          data-haptic="light"
        >
          <svg
            width="16"
            height="16"
            viewBox="0 0 16 16"
            fill="none"
            className={`sidebar-toggle-icon ${collapsed ? 'rotated' : ''}`}
          >
            <path
              d="M10.5 3.5L5.5 8L10.5 12.5"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </button>
        {!collapsed && (
          <span className="sidebar-title animate-fade-in-up">Workspace</span>
        )}
      </div>

      <nav className="sidebar-nav">{children}</nav>

      <div className="sidebar-footer">
        {!collapsed && <span className="sidebar-version">v0.1.0</span>}
      </div>
    </aside>
  );
});

// ---------------------------------------------------------------------------
// Header Component
// ---------------------------------------------------------------------------

interface HeaderProps {
  documentTitle?: string;
  connectionState: string;
}

const Header = memo(function Header({ documentTitle, connectionState }: HeaderProps) {
  const { actor, logout, isAuthenticated } = useAuth();
  const navigate = useNavigate();
  const presenceList = usePresenceList();
  const { data: organizations = [] } = useOrganizations();
  const { currentOrgId } = useOrgContext();
  const sortedOrganizations = useMemo(
    () => [...organizations].sort((a, b) => a.name.localeCompare(b.name)),
    [organizations]
  );
  const [commandPaletteHint, setCommandPaletteHint] = useState(false);
  const [profileMenuOpen, setProfileMenuOpen] = useState(false);
  const profileMenuRef = useRef<HTMLDivElement>(null);

  const displayName = actor?.displayName ?? actor?.email ?? actor?.id ?? 'Profile';
  const initials = displayName
    .split(' ')
    .map((segment) => segment[0])
    .join('')
    .slice(0, 2)
    .toUpperCase();

  // Show cmd+K hint on hover
  const handleKeyHint = useCallback(() => {
    setCommandPaletteHint(true);
    const timer = setTimeout(() => setCommandPaletteHint(false), 2000);
    return () => clearTimeout(timer);
  }, []);

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (!profileMenuRef.current) return;
      if (!profileMenuRef.current.contains(event.target as Node)) {
        setProfileMenuOpen(false);
      }
    }

    if (profileMenuOpen) {
      document.addEventListener('mousedown', handleClickOutside);
    }

    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, [profileMenuOpen]);

  useEffect(() => {
    if (!currentOrgId) return;
    const orgExists = organizations.some((org) => org.id === currentOrgId);
    if (!orgExists) {
      orgContextStore.setCurrentOrgId(null);
    }
  }, [currentOrgId, organizations]);

  return (
    <header className="workspace-header">
      <div className="header-left">
        <div className="header-breadcrumb">
          <OrgSwitcher
            organizations={sortedOrganizations}
            currentOrgId={currentOrgId}
            onSelect={(orgId) => orgContextStore.setCurrentOrgId(orgId)}
          />
          <span className="breadcrumb-separator">/</span>
          <span className="breadcrumb-item current">{documentTitle ?? 'Untitled'}</span>
        </div>
      </div>

      <div className="header-center">
        <button
          className="command-palette-trigger pressable"
          onClick={() => collabStore.toggleCommandPalette()}
          onMouseEnter={handleKeyHint}
          aria-label="Open command palette"
          data-haptic="medium"
        >
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
            <circle cx="7" cy="7" r="5" stroke="currentColor" strokeWidth="1.5" />
            <path d="M11 11L14 14" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
          </svg>
          <span>Search or jump to...</span>
          {commandPaletteHint && (
            <kbd className="shortcut-hint animate-fade-in-up">⌘K</kbd>
          )}
        </button>
      </div>

      <div className="header-right">
        {/* Connection indicator */}
        <div className={`connection-indicator connection-${connectionState}`}>
          <span className="connection-dot" />
          <span className="connection-label">
            {connectionState === 'connected' ? 'Live' : connectionState}
          </span>
        </div>

        {/* Presence avatars */}
        <div className="presence-list" role="list" aria-label="Active collaborators">
          {presenceList.slice(0, 5).map((p) => (
            <PresenceAvatar
              key={p.user_id}
              name={p.user_id} // TODO: Fetch display name
              color={p.color ?? '#3b82f6'}
              status={p.status}
            />
          ))}
          {presenceList.length > 5 && (
            <div className="presence-overflow">+{presenceList.length - 5}</div>
          )}
        </div>

        {/* Share button */}
        <button className="share-button pressable" data-haptic="medium">
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
            <path
              d="M12 5.5C13.1046 5.5 14 4.60457 14 3.5C14 2.39543 13.1046 1.5 12 1.5C10.8954 1.5 10 2.39543 10 3.5C10 4.60457 10.8954 5.5 12 5.5Z"
              stroke="currentColor"
              strokeWidth="1.5"
            />
            <path
              d="M4 10C5.10457 10 6 9.10457 6 8C6 6.89543 5.10457 6 4 6C2.89543 6 2 6.89543 2 8C2 9.10457 2.89543 10 4 10Z"
              stroke="currentColor"
              strokeWidth="1.5"
            />
            <path
              d="M12 14.5C13.1046 14.5 14 13.6046 14 12.5C14 11.3954 13.1046 10.5 12 10.5C10.8954 10.5 10 11.3954 10 12.5C10 13.6046 10.8954 14.5 12 14.5Z"
              stroke="currentColor"
              strokeWidth="1.5"
            />
            <path d="M5.7 9.1L10.3 11.9" stroke="currentColor" strokeWidth="1.5" />
            <path d="M10.3 4.1L5.7 6.9" stroke="currentColor" strokeWidth="1.5" />
          </svg>
          Share
        </button>

        {/* Profile menu */}
        {isAuthenticated && (
          <div className="profile-menu" ref={profileMenuRef}>
            <button
              type="button"
              className="profile-trigger pressable"
              onClick={() => setProfileMenuOpen((prev) => !prev)}
              aria-haspopup="menu"
              aria-expanded={profileMenuOpen}
              data-haptic="light"
            >
              <span className="profile-avatar">
                {actor?.avatarUrl ? (
                  <img
                    src={actor.avatarUrl}
                    alt={displayName}
                    className="profile-avatar-image"
                  />
                ) : (
                  <span className="profile-avatar-initials">{initials}</span>
                )}
              </span>
              <span className="profile-name">{displayName}</span>
              <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
                <path
                  d="M3 4.5L6 7.5L9 4.5"
                  stroke="currentColor"
                  strokeWidth="1.5"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            </button>
            {profileMenuOpen && (
              <div className="profile-dropdown animate-scale-in" role="menu" aria-label="Profile menu">
                <div className="profile-dropdown-header">
                  <span className="profile-dropdown-name">{displayName}</span>
                  {actor?.email && (
                    <span className="profile-dropdown-subtitle">{actor.email}</span>
                  )}
                </div>
                <button
                  type="button"
                  className="profile-menu-item"
                  role="menuitem"
                  onClick={() => {
                    setProfileMenuOpen(false);
                    navigate('/settings');
                  }}
                >
                  Profile
                </button>
                <button
                  type="button"
                  className="profile-menu-item profile-menu-item-logout"
                  role="menuitem"
                  onClick={async () => {
                    setProfileMenuOpen(false);
                    await logout();
                  }}
                >
                  Log out
                </button>
              </div>
            )}
          </div>
        )}
      </div>
    </header>
  );
});

// ---------------------------------------------------------------------------
// Main Content Area
// ---------------------------------------------------------------------------

interface MainContentProps {
  children?: React.ReactNode;
}

const MainContent = memo(function MainContent({ children }: MainContentProps) {
  return (
    <main className="workspace-main">
      {children ?? (
        <div className="empty-state animate-fade-in-up">
          <div className="empty-state-icon">
            <svg width="48" height="48" viewBox="0 0 48 48" fill="none">
              <rect
                x="6"
                y="10"
                width="36"
                height="28"
                rx="3"
                stroke="currentColor"
                strokeWidth="2"
              />
              <path d="M6 18H42" stroke="currentColor" strokeWidth="2" />
              <path d="M16 14V14" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
              <path d="M12 14V14" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
              <path d="M20 14V14" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
            </svg>
          </div>
          <h2 className="empty-state-title">No document open</h2>
          <p className="empty-state-description">
            Create a new plan or select an existing document from the sidebar
          </p>
          <button className="empty-state-cta pressable" data-haptic="medium">
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
              <path d="M8 3V13" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
              <path d="M3 8H13" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
            </svg>
            New Plan
          </button>
        </div>
      )}
    </main>
  );
});

// ---------------------------------------------------------------------------
// WorkspaceShell Container
// ---------------------------------------------------------------------------

export interface WorkspaceShellProps {
  children?: React.ReactNode;
  sidebarContent?: React.ReactNode;
  documentTitle?: string;
}

export function WorkspaceShell({ children, sidebarContent, documentTitle }: WorkspaceShellProps) {
  const { sidebarCollapsed, connectionState, activeDocumentId, documents } = useCollabStore();
  const activeDocument = activeDocumentId ? documents.get(activeDocumentId) : null;

  // Keyboard shortcuts
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      // ⌘K / Ctrl+K → Command palette
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        collabStore.toggleCommandPalette();
      }
      // ⌘B / Ctrl+B → Toggle sidebar
      if ((e.metaKey || e.ctrlKey) && e.key === 'b') {
        e.preventDefault();
        collabStore.toggleSidebar();
      }
    }

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  return (
    <div className="workspace-shell">
      <Sidebar
        collapsed={sidebarCollapsed}
        onToggle={() => collabStore.toggleSidebar()}
      >
        {sidebarContent}
      </Sidebar>

      <div className="workspace-content">
        <Header
          documentTitle={documentTitle ?? activeDocument?.title}
          connectionState={connectionState}
        />
        <MainContent>{children}</MainContent>
      </div>
    </div>
  );
}

export default WorkspaceShell;
