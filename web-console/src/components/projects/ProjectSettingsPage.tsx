/**
 * Project Settings Page
 *
 * Configure project settings including local project path and GitHub repository.
 * Provides GitHub API validation for repository and branch selection.
 *
 * Following:
 * - behavior_design_api_contract (Student)
 * - behavior_use_raze_for_logging (Student)
 * - COLLAB_SAAS_REQUIREMENTS.md (Student): fast, floaty, animated
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { WorkspaceShell } from '../workspace/WorkspaceShell';
import { ConsoleSidebar } from '../ConsoleSidebar';
import { OrgSwitcher } from '../OrgSwitcher';
import { useOrganizations, useProject } from '../../api/dashboard';
import { apiClient } from '../../api/client';
import { razeLog } from '../../telemetry/raze';
import './ProjectSettingsPage.css';

// ---------------------------------------------------------------------------
// Types (aligned with backend settings_api.py)
// ---------------------------------------------------------------------------

interface ProjectSettings {
  local_project_path?: string;
  github_repo_url?: string;
  github_default_branch?: string;
  workflow?: Record<string, unknown>;
  agents?: Record<string, unknown>;
  branding?: Record<string, unknown>;
}

interface GitHubBranchInfo {
  name: string;
  is_default: boolean;
  is_protected: boolean;
}

interface GitHubRepoValidationResponse {
  valid: boolean;
  owner?: string;
  repo?: string;
  full_name?: string;
  default_branch?: string;
  is_private?: boolean;
  description?: string;
  error?: string;
}

interface GitHubBranchListResponse {
  branches: GitHubBranchInfo[];
  total_count: number;
  page: number;
  per_page: number;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function ProjectSettingsPage(): React.JSX.Element {
  const navigate = useNavigate();
  const { projectId } = useParams<{ projectId: string }>();
  const [searchParams, setSearchParams] = useSearchParams();

  const orgFromQuery = searchParams.get('org') ?? undefined;
  const [currentOrgId, setCurrentOrgId] = useState<string | undefined>(orgFromQuery);

  const { data: organizations = [] } = useOrganizations();
  const { data: project, isLoading: projectLoading } = useProject(projectId);

  // Form state
  const [localPath, setLocalPath] = useState('');
  const [githubUrl, setGithubUrl] = useState('');
  const [selectedBranch, setSelectedBranch] = useState('');

  // GitHub validation state
  const [isValidatingGithub, setIsValidatingGithub] = useState(false);
  const [githubValidation, setGithubValidation] = useState<GitHubRepoValidationResponse | null>(null);
  const [githubError, setGithubError] = useState<string | null>(null);

  // Branch list state
  const [branches, setBranches] = useState<GitHubBranchInfo[]>([]);
  const [isLoadingBranches, setIsLoadingBranches] = useState(false);

  // Save state
  const [isSaving, setIsSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveSuccess, setSaveSuccess] = useState(false);

  // Load existing settings
  useEffect(() => {
    if (project?.settings) {
      const settings = project.settings as ProjectSettings;
      setLocalPath(settings.local_project_path ?? '');
      setGithubUrl(settings.github_repo_url ?? '');
      setSelectedBranch(settings.github_default_branch ?? '');

      // If GitHub URL is already set, validate it to load branches
      if (settings.github_repo_url) {
        void validateGithubRepo(settings.github_repo_url);
      }
    }
  }, [project]);

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

  // Validate GitHub repository
  const validateGithubRepo = useCallback(async (url: string) => {
    if (!url.trim() || !projectId) return;

    setIsValidatingGithub(true);
    setGithubError(null);
    setGithubValidation(null);
    setBranches([]);

    try {
      await razeLog('INFO', 'Validating GitHub repository', { project_id: projectId, url });

      const response = await apiClient.post<GitHubRepoValidationResponse>(
        `/v1/projects/${projectId}/settings/github/validate`,
        { repo_url: url }
      );

      setGithubValidation(response);

      if (response.valid) {
        await razeLog('INFO', 'GitHub repository validated', {
          project_id: projectId,
          full_name: response.full_name,
        });

        // If valid, auto-select default branch and load branch list
        if (response.default_branch && !selectedBranch) {
          setSelectedBranch(response.default_branch);
        }
        await loadBranches();
      } else {
        setGithubError(response.error ?? 'Repository validation failed');
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to validate repository';
      setGithubError(message);
      await razeLog('ERROR', 'GitHub validation failed', { project_id: projectId, error: message });
    } finally {
      setIsValidatingGithub(false);
    }
  }, [projectId, selectedBranch]);

  // Load GitHub branches
  const loadBranches = useCallback(async () => {
    if (!projectId) return;

    setIsLoadingBranches(true);

    try {
      const response = await apiClient.get<GitHubBranchListResponse>(
        `/v1/projects/${projectId}/settings/github/branches`
      );
      setBranches(response.branches);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to load branches';
      await razeLog('WARN', 'Failed to load GitHub branches', { project_id: projectId, error: message });
      // Don't show error to user, branches are optional
    } finally {
      setIsLoadingBranches(false);
    }
  }, [projectId]);

  // Save settings
  const handleSave = useCallback(async () => {
    if (!projectId) return;

    setIsSaving(true);
    setSaveError(null);
    setSaveSuccess(false);

    try {
      await razeLog('INFO', 'Saving project settings', { project_id: projectId });

      await apiClient.patch(`/v1/projects/${projectId}/settings`, {
        local_project_path: localPath.trim() || null,
        github_repo_url: githubUrl.trim() || null,
        github_default_branch: selectedBranch || null,
      });

      setSaveSuccess(true);
      await razeLog('INFO', 'Project settings saved', { project_id: projectId });

      // Clear success message after 3 seconds
      setTimeout(() => setSaveSuccess(false), 3000);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to save settings';
      setSaveError(message);
      await razeLog('ERROR', 'Failed to save project settings', { project_id: projectId, error: message });
    } finally {
      setIsSaving(false);
    }
  }, [projectId, localPath, githubUrl, selectedBranch]);

  // Validation status
  const isGithubValid = useMemo(() => githubValidation?.valid === true, [githubValidation]);

  if (projectLoading) {
    return (
      <WorkspaceShell
        sidebarContent={<ConsoleSidebar selectedId="projects" onNavigate={(p) => navigate(p)} />}
        documentTitle="Project Settings"
      >
        <div className="project-settings-page">
          <div className="loading-state">Loading project...</div>
        </div>
      </WorkspaceShell>
    );
  }

  if (!project) {
    return (
      <WorkspaceShell
        sidebarContent={<ConsoleSidebar selectedId="projects" onNavigate={(p) => navigate(p)} />}
        documentTitle="Project Settings"
      >
        <div className="project-settings-page">
          <div className="error-state">Project not found</div>
        </div>
      </WorkspaceShell>
    );
  }

  return (
    <WorkspaceShell
      sidebarContent={<ConsoleSidebar selectedId="projects" onNavigate={(p) => navigate(p)} />}
      documentTitle={`${project.name} Settings`}
    >
      <div className="project-settings-page">
        <header className="project-settings-header">
          <div className="project-settings-header-left">
            <button
              type="button"
              className="project-settings-back pressable"
              onClick={() => navigate('/projects')}
              data-haptic="light"
            >
              ← Back
            </button>
            <div>
              <h1 className="project-settings-title animate-fade-in-up">
                {project.name} Settings
              </h1>
              <p className="project-settings-subtitle animate-fade-in-up">
                Configure local paths, GitHub integration, and other project settings.
              </p>
            </div>
          </div>

          <div className="project-settings-header-right">
            <OrgSwitcher
              organizations={organizations}
              currentOrgId={currentOrgId}
              onSelect={handleOrgSelect}
            />
          </div>
        </header>

        <section className="project-settings-card" aria-label="Project settings form">
          {/* Local Project Path */}
          <div className="settings-section">
            <h2 className="settings-section-title">Local Project Path</h2>
            <p className="settings-section-description">
              Optional: The local filesystem path where this project is located.
              VS Code can auto-detect this from your workspace.
            </p>

            <label className="field">
              <span className="field-label">Path</span>
              <input
                className="field-input"
                value={localPath}
                onChange={(e) => setLocalPath(e.target.value)}
                placeholder="/Users/you/projects/my-project"
              />
              <span className="field-hint">
                Example: <code className="mono">/Users/nick/guideai</code>
              </span>
            </label>
          </div>

          {/* GitHub Repository */}
          <div className="settings-section">
            <h2 className="settings-section-title">GitHub Repository</h2>
            <p className="settings-section-description">
              Optional: Connect a GitHub repository for branch selection and integration features.
              Requires GitHub authentication.
            </p>

            <label className="field">
              <span className="field-label">Repository URL</span>
              <div className="field-input-group">
                <input
                  className={`field-input ${githubError ? 'error' : ''} ${isGithubValid ? 'valid' : ''}`}
                  value={githubUrl}
                  onChange={(e) => {
                    setGithubUrl(e.target.value);
                    setGithubValidation(null);
                    setGithubError(null);
                    setBranches([]);
                  }}
                  placeholder="https://github.com/owner/repo"
                  aria-invalid={Boolean(githubError)}
                />
                <button
                  type="button"
                  className="validate-button pressable"
                  onClick={() => void validateGithubRepo(githubUrl)}
                  disabled={!githubUrl.trim() || isValidatingGithub}
                  data-haptic="light"
                >
                  {isValidatingGithub ? 'Validating…' : 'Validate'}
                </button>
              </div>
              {githubError && <span className="field-error">{githubError}</span>}
              {isGithubValid && githubValidation && (
                <div className="github-validation-success">
                  <span className="validation-icon">✓</span>
                  <span className="validation-text">
                    <strong>{githubValidation.full_name}</strong>
                    {githubValidation.is_private && <span className="badge private">Private</span>}
                    {githubValidation.description && (
                      <span className="validation-description">{githubValidation.description}</span>
                    )}
                  </span>
                </div>
              )}
            </label>

            {/* Branch Selection */}
            {isGithubValid && (
              <label className="field animate-fade-in-up">
                <span className="field-label">Default Branch</span>
                <select
                  className="field-select"
                  value={selectedBranch}
                  onChange={(e) => setSelectedBranch(e.target.value)}
                  disabled={isLoadingBranches}
                >
                  {branches.length === 0 && !isLoadingBranches && (
                    <option value="">Select a branch</option>
                  )}
                  {isLoadingBranches && <option value="">Loading branches…</option>}
                  {branches.map((branch) => (
                    <option key={branch.name} value={branch.name}>
                      {branch.name}
                      {branch.is_default && ' (default)'}
                      {branch.is_protected && ' 🔒'}
                    </option>
                  ))}
                </select>
                <span className="field-hint">
                  Select the branch to use for this project. Default branch is auto-selected.
                </span>
              </label>
            )}
          </div>

          {/* Save Actions */}
          <div className="settings-actions">
            {saveError && (
              <div className="save-error" role="alert">
                {saveError}
              </div>
            )}
            {saveSuccess && (
              <div className="save-success" role="status">
                Settings saved successfully!
              </div>
            )}

            <button
              type="button"
              className="action secondary pressable"
              onClick={() => navigate('/projects')}
            >
              Cancel
            </button>
            <button
              type="button"
              className="action primary pressable"
              onClick={() => void handleSave()}
              disabled={isSaving}
              data-haptic="medium"
            >
              {isSaving ? 'Saving…' : 'Save Settings'}
            </button>
          </div>
        </section>
      </div>
    </WorkspaceShell>
  );
}
