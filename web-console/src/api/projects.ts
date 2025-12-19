/**
 * Projects API
 *
 * Following:
 * - behavior_use_raze_for_logging (Student)
 */

import { useMutation, useQueryClient } from '@tanstack/react-query';
import { apiClient, ApiError } from './client';
import { dashboardKeys, type Project } from './dashboard';
import { razeLog } from '../telemetry/raze';

export interface CreateProjectRequest {
  name: string;
  description?: string;
  visibility: 'private' | 'internal' | 'public';
  slug?: string;
}

function normalizeApiError(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return 'Failed to create project';
}

export async function createProject(
  orgId: string | undefined,
  payload: CreateProjectRequest
): Promise<Project> {
  // Prefer unified `/v1/projects` (single project type; org optional).
  const endpoints = ['/v1/projects'];
  // Legacy org-scoped endpoints (may exist in some deployments).
  if (orgId) {
    endpoints.push(`/v1/orgs/${orgId}/projects`, `/v1/organizations/${orgId}/projects`);
  }

  await razeLog('INFO', 'Project create requested', {
    org_id: orgId ?? null,
    name: payload.name,
    visibility: payload.visibility,
  });

  let lastError: unknown = null;
  for (const endpoint of endpoints) {
    try {
      const body = endpoint === '/v1/projects' && orgId ? { ...payload, org_id: orgId } : payload;
      const created = await apiClient.post<Project>(endpoint, body);
      await razeLog('INFO', 'Project created', {
        org_id: orgId ?? null,
        project_id: created.id,
        project_slug: created.slug,
      });
      return created;
    } catch (error) {
      lastError = error;
    }
  }

  await razeLog('ERROR', 'Project create failed', {
    org_id: orgId ?? null,
    error: normalizeApiError(lastError),
  });

  throw lastError instanceof Error ? lastError : new Error(normalizeApiError(lastError));
}

export function useCreateProject() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (input: { orgId?: string; payload: CreateProjectRequest }) =>
      createProject(input.orgId, input.payload),
    onSuccess: async (_created, variables) => {
      await queryClient.invalidateQueries({ queryKey: dashboardKeys.projects(variables.orgId) });
      await queryClient.invalidateQueries({ queryKey: dashboardKeys.stats() });
    },
  });
}
