/**
 * GuideAI Web Console - Main Application
 *
 * Full-featured SaaS console with authentication, dashboard,
 * collaborative workspaces, and behavior-conditioned inference.
 *
 * Routes:
 * - /login: Authentication (device flow + OAuth)
 * - /auth/callback: OAuth redirect handler
 * - /: Dashboard (protected)
 * - /agents: Agent registry (protected)
 * - /bci: BCI Query panel (protected)
 * - /extraction: Behavior extraction (protected)
 *
 * Following:
 * - behavior_validate_accessibility (Student)
 * - behavior_prototype_consent_ux (Teacher)
 */

import { lazy, Suspense, useState, useCallback } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter, Routes, Route, useLocation, useNavigate } from 'react-router-dom';
import { AuthProvider } from './auth';
import { ProtectedRoute } from './components/ProtectedRoute';
import { ConsoleSidebar } from './components/ConsoleSidebar';
import { WorkspaceShell } from './components/workspace/WorkspaceShell';
import type { ReflectionCandidate } from './api/reflection';
import './styles/design-system.css';
import './App.css';

const LoginPage = lazy(() => import('./components/LoginPage').then((module) => ({ default: module.LoginPage })));
const OAuthCallback = lazy(() => import('./components/OAuthCallback').then((module) => ({ default: module.OAuthCallback })));
const Dashboard = lazy(() => import('./components/Dashboard').then((module) => ({ default: module.Dashboard })));
const BCIResponsePanel = lazy(() => import('./components/BCIResponsePanel').then((module) => ({ default: module.BCIResponsePanel })));
const ExtractionCandidates = lazy(() => import('./components/ExtractionCandidates').then((module) => ({ default: module.ExtractionCandidates })));
const NotFoundPage = lazy(() => import('./components/NotFoundPage').then((module) => ({ default: module.NotFoundPage })));
const SecuritySettings = lazy(() => import('./components/SecuritySettings').then((module) => ({ default: module.SecuritySettings })));
const ProjectsPage = lazy(() => import('./components/projects/ProjectsPage').then((module) => ({ default: module.ProjectsPage })));
const NewProjectPage = lazy(() => import('./components/projects/NewProjectPage').then((module) => ({ default: module.NewProjectPage })));
const ProjectPage = lazy(() => import('./components/projects/ProjectPage').then((module) => ({ default: module.ProjectPage })));
const ProjectSettingsPage = lazy(() => import('./components/projects/ProjectSettingsPage').then((module) => ({ default: module.ProjectSettingsPage })));
const BoardPage = lazy(() => import('./components/boards/BoardPage').then((module) => ({ default: module.BoardPage })));
const OrganizationsPage = lazy(() => import('./components/orgs/OrganizationsPage').then((module) => ({ default: module.OrganizationsPage })));
const AgentsPage = lazy(() => import('./components/agents/AgentsPage').then((module) => ({ default: module.AgentsPage })));
const GitHubAppCallbackPage = lazy(() => import('./pages/GitHubAppCallbackPage').then((module) => ({ default: module.GitHubAppCallbackPage })));

function RouteFallback() {
  return <div className="app-route-fallback animate-fade-in-up">Loading…</div>;
}

// Create a client
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5 * 60 * 1000, // 5 minutes
      retry: 2,
    },
  },
});

/**
 * BCI Tools Layout - for BCI and Extraction routes
 */
function BCILayout() {
  const location = useLocation();
  const navigate = useNavigate();
  const [notifications, setNotifications] = useState<string[]>([]);

  const handleAutoApproved = useCallback((candidates: ReflectionCandidate[]) => {
    const message = `✓ Auto-approved ${candidates.length} behavior(s): ${candidates.map(c => c.slug).join(', ')}`;
    setNotifications((prev) => [...prev, message]);
    setTimeout(() => {
      setNotifications((prev) => prev.filter((n) => n !== message));
    }, 5000);
  }, []);

  const handleCandidateApproved = useCallback((candidate: ReflectionCandidate, behaviorId: string) => {
    const message = `✓ Approved behavior "${candidate.display_name}" (ID: ${behaviorId})`;
    setNotifications((prev) => [...prev, message]);
    setTimeout(() => {
      setNotifications((prev) => prev.filter((n) => n !== message));
    }, 5000);
  }, []);

  const isExtractionRoute = location.pathname === '/bci/extraction';

  return (
    <WorkspaceShell
      sidebarContent={<ConsoleSidebar selectedId={isExtractionRoute ? 'extraction' : 'bci'} onNavigate={(path) => navigate(path)} />}
      documentTitle={isExtractionRoute ? 'Behavior Extraction' : 'Behavior Search'}
    >
      <>
        {notifications.length > 0 && (
          <div className="notifications">
            {notifications.map((notification, i) => (
              <div key={i} className="notification">
                {notification}
              </div>
            ))}
          </div>
        )}
        <Routes>
          <Route index element={<BCIResponsePanel />} />
          <Route
            path="extraction"
            element={
              <ExtractionCandidates
                onAutoApproved={handleAutoApproved}
                onCandidateApproved={handleCandidateApproved}
              />
            }
          />
        </Routes>
      </>
    </WorkspaceShell>
  );
}

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthProvider>
          <Suspense fallback={<RouteFallback />}>
            <AnimatedRoutes />
          </Suspense>
        </AuthProvider>
      </BrowserRouter>
    </QueryClientProvider>
  );
}

function AnimatedRoutes() {
  const location = useLocation();
  // Only re-animate on top-level route changes (e.g. /agents → /projects),
  // not sub-path changes within the same section (e.g. /agents/a → /agents/b).
  const routeSegment = '/' + (location.pathname.split('/')[1] ?? '');

  return (
    <div key={routeSegment} className="app-route-stage">
      <Routes location={location}>
              {/* Public routes */}
              <Route path="/login" element={<LoginPage />} />
              <Route path="/auth/callback" element={<OAuthCallback />} />
              <Route path="/auth/github-app/callback" element={<GitHubAppCallbackPage />} />

              {/* Protected routes */}
              <Route
                path="/"
                element={
                  <ProtectedRoute>
                    <Dashboard />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/bci/*"
                element={
                  <ProtectedRoute>
                    <BCILayout />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/settings"
                element={
                  <ProtectedRoute>
                    <SecuritySettings />
                  </ProtectedRoute>
                }
              />

              {/* Project routes */}
              <Route
                path="/orgs"
                element={
                  <ProtectedRoute>
                    <OrganizationsPage />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/agents"
                element={
                  <ProtectedRoute>
                    <AgentsPage />
                  </ProtectedRoute>
                }
              >
                <Route path="new" element={null} />
                <Route path=":agentId" element={null} />
              </Route>
              <Route
                path="/projects"
                element={
                  <ProtectedRoute>
                    <ProjectsPage />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/projects/new"
                element={
                  <ProtectedRoute>
                    <NewProjectPage />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/projects/:projectId"
                element={
                  <ProtectedRoute>
                    <ProjectPage />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/projects/:projectId/settings"
                element={
                  <ProtectedRoute>
                    <ProjectSettingsPage />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/projects/:projectId/boards/:boardId"
                element={
                  <ProtectedRoute>
                    <BoardPage />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/projects/:projectId/boards/:boardId/items/:itemId"
                element={
                  <ProtectedRoute>
                    <BoardPage />
                  </ProtectedRoute>
                }
              />

              {/* Catch-all */}
              <Route path="*" element={<NotFoundPage />} />
      </Routes>
    </div>
  );
}

export default App;
