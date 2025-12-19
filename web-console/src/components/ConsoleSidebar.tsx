/**
 * Console Sidebar
 *
 * Shared sidebar navigation used across console pages.
 */

import { memo, useCallback } from 'react';
import { DocumentList } from './workspace/DocumentList';

export type ConsoleSidebarSelectedId = 'dashboard' | 'projects' | 'projects-new' | 'bci' | 'extraction';

interface ConsoleSidebarProps {
  selectedId: ConsoleSidebarSelectedId;
  onNavigate: (path: string) => void;
}

export const ConsoleSidebar = memo(function ConsoleSidebar({ selectedId, onNavigate }: ConsoleSidebarProps) {
  const sidebarItems = [
    { id: 'dashboard', title: 'Dashboard', type: 'dashboard', updated_at: new Date().toISOString() },
    { id: 'projects', title: 'Projects', type: 'folder', updated_at: new Date().toISOString() },
    { id: 'projects-new', title: 'New Project', type: 'plan', updated_at: new Date().toISOString() },
    { id: 'bci', title: 'BCI Query', type: 'plan', updated_at: new Date().toISOString() },
    { id: 'extraction', title: 'Extraction', type: 'workflow', updated_at: new Date().toISOString() },
  ];

  const handleSelect = useCallback(
    (id: string) => {
      switch (id) {
        case 'dashboard':
          onNavigate('/');
          break;
        case 'projects':
          onNavigate('/projects');
          break;
        case 'projects-new':
          onNavigate('/projects/new');
          break;
        case 'bci':
          onNavigate('/bci');
          break;
        case 'extraction':
          onNavigate('/extraction');
          break;
        default:
          break;
      }
    },
    [onNavigate]
  );

  return <DocumentList documents={sidebarItems as any} selectedId={selectedId} onSelect={handleSelect} />;
});
