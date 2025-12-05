/**
 * GuideAI Web Console - Main Application
 * Implements Epic 8.11 (BCI responses with citations) and Epic 8.12 (Behavior extraction pipeline)
 */

import { useState, useCallback } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter, Routes, Route, NavLink } from 'react-router-dom';
import { BCIResponsePanel } from './components/BCIResponsePanel';
import { ExtractionCandidates } from './components/ExtractionCandidates';
import type { ReflectionCandidate } from './api/reflection';
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

function AppLayout() {
  const [notifications, setNotifications] = useState<string[]>([]);

  const handleAutoApproved = useCallback((candidates: ReflectionCandidate[]) => {
    const message = `✓ Auto-approved ${candidates.length} behavior(s): ${candidates.map(c => c.slug).join(', ')}`;
    setNotifications((prev) => [...prev, message]);

    // Clear notification after 5 seconds
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
    <div className="app-container">
      <header className="app-header">
        <div className="header-brand">
          <h1>GuideAI Console</h1>
          <span className="header-tagline">Behavior-Conditioned Inference</span>
        </div>
        <nav className="header-nav">
          <NavLink to="/" end className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}>
            BCI Query
          </NavLink>
          <NavLink to="/extraction" className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}>
            Extraction
          </NavLink>
        </nav>
      </header>

      {notifications.length > 0 && (
        <div className="notifications">
          {notifications.map((notification, i) => (
            <div key={i} className="notification">
              {notification}
            </div>
          ))}
        </div>
      )}

      <main className="app-main">
        <Routes>
          <Route path="/" element={<BCIResponsePanel />} />
          <Route
            path="/extraction"
            element={
              <ExtractionCandidates
                onAutoApproved={handleAutoApproved}
                onCandidateApproved={handleCandidateApproved}
              />
            }
          />
        </Routes>
      </main>

      <footer className="app-footer">
        <p>GuideAI · Behavior Handbook · PRD Target: 70% behavior reuse, 30% token savings</p>
      </footer>
    </div>
  );
}

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AppLayout />
      </BrowserRouter>
    </QueryClientProvider>
  );
}

export default App;
