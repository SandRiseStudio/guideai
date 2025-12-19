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
 * - /bci: BCI Query panel (protected)
 * - /extraction: Behavior extraction (protected)
 *
 * Following:
 * - behavior_validate_accessibility (Student)
 * - behavior_prototype_consent_ux (Teacher)
 */

import { useState, useCallback } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { AuthProvider } from './auth';
import { LoginPage } from './components/LoginPage';
import { OAuthCallback } from './components/OAuthCallback';
import { Dashboard } from './components/Dashboard';
import { ProtectedRoute } from './components/ProtectedRoute';
import { BCIResponsePanel } from './components/BCIResponsePanel';
import { ExtractionCandidates } from './components/ExtractionCandidates';
import { NotFoundPage } from './components/NotFoundPage';
import { ProjectsPage } from './components/projects/ProjectsPage';
import { NewProjectPage } from './components/projects/NewProjectPage';
import { ProjectPage } from './components/projects/ProjectPage';
import { ProjectSettingsPage } from './components/projects/ProjectSettingsPage';
import { BoardPage } from './components/boards/BoardPage';
import type { ReflectionCandidate } from './api/reflection';
import './styles/design-system.css';
import './App.css';

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

  return (
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
  );
}

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthProvider>
          <Routes>
            {/* Public routes */}
            <Route path="/login" element={<LoginPage />} />
            <Route path="/auth/callback" element={<OAuthCallback />} />

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

            {/* Project routes */}
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
        </AuthProvider>
      </BrowserRouter>
    </QueryClientProvider>
  );
}

export default App;
