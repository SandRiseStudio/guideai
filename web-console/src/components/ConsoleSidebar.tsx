/**
 * Console Sidebar
 *
 * Shared sidebar navigation used across console pages.
 */

import { memo, useCallback } from 'react';
import { DocumentList } from './workspace/DocumentList';

export type ConsoleSidebarSelectedId =
  | 'dashboard'
  | 'orgs'
  | 'projects'
  | 'projects-new'
  | 'agents'
  | 'bci'
  | 'extraction';

interface ConsoleSidebarProps {
  selectedId: ConsoleSidebarSelectedId;
  onNavigate: (path: string) => void;
}

export const ConsoleSidebar = memo(function ConsoleSidebar({ selectedId, onNavigate }: ConsoleSidebarProps) {
  const sidebarItems = [
    { id: 'dashboard', title: 'Dashboard', document_type: 'plan', updated_at: new Date().toISOString() },
    { id: 'orgs', title: 'Organizations', document_type: 'org', updated_at: new Date().toISOString() },
    { id: 'projects', title: 'Projects', document_type: 'workflow', updated_at: new Date().toISOString() },
    { id: 'agents', title: 'Agents', document_type: 'agent', updated_at: new Date().toISOString() },
    { id: 'projects-new', title: 'New Project', document_type: 'plan', updated_at: new Date().toISOString() },
    { id: 'bci', title: 'BCI Query', document_type: 'plan', updated_at: new Date().toISOString() },
    { id: 'extraction', title: 'Extraction', document_type: 'workflow', updated_at: new Date().toISOString() },
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
        case 'orgs':
          onNavigate('/orgs');
          break;
        case 'agents':
          onNavigate('/agents');
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
