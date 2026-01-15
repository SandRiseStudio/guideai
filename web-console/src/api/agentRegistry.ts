/**
 * Agent Registry API
 *
 * Following:
 * - behavior_use_raze_for_logging (Student)
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiClient, ApiError, API_ORIGIN } from './client';
import { apiClient as clientInstance } from './client';
import { razeLog } from '../telemetry/raze';
import { dashboardKeys, type Agent as OrgAgent } from './dashboard';

export type AgentVisibility = 'PRIVATE' | 'ORGANIZATION' | 'PUBLIC';
export type AgentStatus = 'DRAFT' | 'ACTIVE' | 'DEPRECATED';
export type RoleAlignment = 'STRATEGIST' | 'TEACHER' | 'STUDENT' | 'MULTI_ROLE';

export interface AgentRegistryEntry {
  agent_id: string;
  name: string;
  slug: string;
  description: string;
  tags: string[];
  created_at: string;
  updated_at: string;
  latest_version: string;
  status: AgentStatus;
  visibility: AgentVisibility;
  owner_id: string;
  org_id?: string | null;
  published_at?: string | null;
  is_builtin: boolean;
  service_principal_id?: string | null;
}

export interface AgentRegistryVersion {
  version_id?: string;
  agent_id: string;
  version: string;
  mission: string;
  role_alignment: RoleAlignment;
  capabilities: string[];
  default_behaviors: string[];
  playbook_content?: string;
  status: AgentStatus;
  created_at: string;
  created_by: string;
  effective_from: string;
  effective_to?: string | null;
  created_from?: string | null;
  metadata?: Record<string, unknown>;
}

export interface AgentRegistryDetail {
  agent: AgentRegistryEntry;
  versions: AgentRegistryVersion[];
}

export interface AgentRegistrySearchResult {
  agent: AgentRegistryEntry;
  active_version?: AgentRegistryVersion | null;
  score: number;
}

export interface AgentRegistryListItem {
  agent: AgentRegistryEntry;
  active_version?: AgentRegistryVersion | null;
  score?: number;
}

type RawAgentListItem =
  | AgentRegistryEntry
  | {
      agent: AgentRegistryEntry;
      active_version?: AgentRegistryVersion | null;
      score?: number;
    };

export interface AgentRegistryQuery {
  query?: string;
  status?: AgentStatus;
  visibility?: AgentVisibility;
  roleAlignment?: RoleAlignment;
  includeBuiltin?: boolean;
  ownerId?: string;
  tags?: string[];
  limit?: number;
  offset?: number;
  orgId?: string;
}

export interface CreateAgentInput {
  name: string;
  slug?: string;
  description: string;
  mission: string;
  role_alignment: RoleAlignment;
  capabilities?: string[];
  default_behaviors?: string[];
  playbook_content?: string;
  tags?: string[];
  visibility?: AgentVisibility;
  request_api_credentials?: boolean;
  org_id?: string;
}

export interface CreateAgentResponse extends AgentRegistryEntry {
  credentials?: {
    client_id: string;
    client_secret: string;
  };
}

export interface UpdateAgentInput {
  name?: string;
  description?: string;
  tags?: string[];
  visibility?: AgentVisibility;
  latest_version?: string;
}

export interface CreateAgentVersionInput {
  base_version?: string;
  mission?: string;
  role_alignment?: RoleAlignment;
  capabilities?: string[];
  default_behaviors?: string[];
  playbook_content?: string;
  metadata?: Record<string, unknown>;
}

export interface PublishAgentInput {
  version?: string;
  visibility?: AgentVisibility;
  effective_from?: string;
}

export interface AgentAssignmentInput {
  orgId: string;
  agent: AgentRegistryEntry;
  projectId?: string | null;
  roleAlignment?: RoleAlignment;
  capabilities?: string[];
}

export interface PersonalAgentAssignmentInput {
  agent: AgentRegistryEntry;
  projectId: string;
  roleAlignment?: RoleAlignment;
  capabilities?: string[];
}

export const agentRegistryKeys = {
  all: ['agentRegistry'] as const,
  list: (filters: AgentRegistryQuery) => [...agentRegistryKeys.all, 'list', filters] as const,
  detail: (agentId?: string | null) => [...agentRegistryKeys.all, 'detail', agentId] as const,
  personalAgents: () => [...agentRegistryKeys.all, 'personalAgents'] as const,
};

const openApiKeys = {
  paths: () => ['openapi', 'paths'] as const,
};

async function fetchOpenApiPaths(): Promise<string[]> {
  const response = await fetch(`${API_ORIGIN}/openapi.json`, {
    method: 'GET',
    headers: { Accept: 'application/json' },
  });

  if (!response.ok) {
    throw new Error(`Failed to fetch OpenAPI spec (${response.status})`);
  }

  const json = (await response.json()) as { paths?: Record<string, unknown> };
  return Object.keys(json.paths ?? {});
}

function normalizeApiError(error: unknown, fallback: string): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return fallback;
}

function normalizeListResponse(response: unknown): RawAgentListItem[] {
  if (!response) return [];
  if (Array.isArray(response)) return response as RawAgentListItem[];
  if (typeof response === 'object') {
    const payload = response as { agents?: RawAgentListItem[]; items?: RawAgentListItem[] };
    if (Array.isArray(payload.agents)) return payload.agents;
    if (Array.isArray(payload.items)) return payload.items;
  }
  return [];
}

function normalizeAssignmentList(response: unknown): OrgAgent[] {
  if (!response) return [];
  if (Array.isArray(response)) return response as OrgAgent[];
  if (typeof response === 'object') {
    const payload = response as { agents?: OrgAgent[]; items?: OrgAgent[] };
    if (Array.isArray(payload.agents)) return payload.agents;
    if (Array.isArray(payload.items)) return payload.items;
  }
  return [];
}

async function listPersonalAgents(): Promise<OrgAgent[]> {
  try {
    const response = await apiClient.get<OrgAgent[] | { agents?: OrgAgent[]; items?: OrgAgent[] }>(
      '/v1/projects/agents'
    );
    return normalizeAssignmentList(response);
  } catch (error) {
    // In some deployments this endpoint may be unavailable for "personal" context.
    // Treat a 404 as "no assignments" to avoid noisy console errors.
    if (error instanceof ApiError && error.status === 404) {
      return [];
    }
    throw error;
  }
}

async function listAgentRegistry(filters: AgentRegistryQuery): Promise<AgentRegistryListItem[]> {
  const params = new URLSearchParams();
  if (filters.status) params.set('status', filters.status);
  if (filters.visibility) params.set('visibility', filters.visibility);
  if (filters.roleAlignment) params.set('role_alignment', filters.roleAlignment);
  if (filters.includeBuiltin !== undefined) params.set('builtin', String(filters.includeBuiltin));
  if (filters.ownerId) params.set('owner_id', filters.ownerId);
  if (filters.tags?.length) {
    filters.tags.forEach((tag) => params.append('tags', tag));
  }
  if (filters.limit) params.set('limit', String(filters.limit));
  if (filters.offset) params.set('offset', String(filters.offset));
  const query = params.toString();
  const path = query ? `/v1/agents?${query}` : '/v1/agents';
  const response = await apiClient.get<RawAgentListItem[] | { agents?: RawAgentListItem[] }>(path);
  const agents = normalizeListResponse(response);
  return agents.map((agent) => {
    if (typeof agent === 'object' && agent !== null && 'agent' in agent) {
      const payload = agent as { agent: AgentRegistryEntry; active_version?: AgentRegistryVersion | null };
      return { agent: payload.agent, active_version: payload.active_version ?? null };
    }
    return { agent: agent as AgentRegistryEntry };
  });
}

async function searchAgentRegistry(filters: AgentRegistryQuery): Promise<AgentRegistryListItem[]> {
  const response = await apiClient.post<{ results?: AgentRegistrySearchResult[] }>(
    '/v1/agents:search',
    {
      query: filters.query,
      tags: filters.tags,
      role_alignment: filters.roleAlignment,
      visibility: filters.visibility,
      status: filters.status,
      owner_id: filters.ownerId,
      include_builtin: filters.includeBuiltin ?? true,
      limit: filters.limit ?? 50,
      org_id: filters.orgId,
    }
  );
  const results = response?.results ?? [];
  return results.map((result) => ({
    agent: result.agent,
    active_version: result.active_version ?? null,
    score: result.score,
  }));
}

export function useAgentRegistry(filters: AgentRegistryQuery) {
  const shouldSearch = Boolean(filters.query && filters.query.trim().length > 0);
  return useQuery({
    queryKey: agentRegistryKeys.list(filters),
    queryFn: () => (shouldSearch ? searchAgentRegistry(filters) : listAgentRegistry(filters)),
    staleTime: 30_000,
  });
}

export function useAgentRegistryDetail(agentId?: string | null) {
  return useQuery({
    queryKey: agentRegistryKeys.detail(agentId),
    queryFn: async (): Promise<AgentRegistryDetail | null> => {
      if (!agentId) return null;
      return apiClient.get<AgentRegistryDetail>(`/v1/agents/${agentId}`);
    },
    enabled: Boolean(agentId),
    staleTime: 30_000,
  });
}

export function usePersonalAgents(enabled = true) {
  // Skip entirely if user isn't authenticated—this endpoint returns 404 without a valid token
  // (security measure to hide endpoint existence from unauthenticated requests).
  const hasToken = clientInstance.hasToken();

  const { data: openApiPaths } = useQuery({
    queryKey: openApiKeys.paths(),
    queryFn: fetchOpenApiPaths,
    staleTime: Infinity,
    gcTime: Infinity,
    enabled: enabled && hasToken,
    retry: false,
  });

  // Our API client calls `/v1/...` under `${API_BASE}` which already includes `/api`.
  // Therefore `/v1/projects/agents` maps to the OpenAPI path `/api/v1/projects/agents`.
  const supportsPersonalAgents = openApiPaths?.includes('/api/v1/projects/agents') ?? false;

  return useQuery({
    queryKey: agentRegistryKeys.personalAgents(),
    queryFn: listPersonalAgents,
    staleTime: 30_000,
    enabled: enabled && hasToken && supportsPersonalAgents,
  });
}

export async function createRegistryAgent(payload: CreateAgentInput): Promise<CreateAgentResponse> {
  await razeLog('INFO', 'Agent registry create requested', {
    name: payload.name,
    visibility: payload.visibility ?? 'PRIVATE',
  });
  try {
    const created = await apiClient.post<CreateAgentResponse>('/v1/agents', payload);
    await razeLog('INFO', 'Agent registry created', {
      agent_id: created.agent_id,
      visibility: created.visibility,
    });
    return created;
  } catch (error) {
    await razeLog('ERROR', 'Agent registry create failed', {
      error: normalizeApiError(error, 'Failed to create agent'),
    });
    throw error;
  }
}

export async function updateRegistryAgent(agentId: string, payload: UpdateAgentInput): Promise<AgentRegistryEntry> {
  await razeLog('INFO', 'Agent registry update requested', {
    agent_id: agentId,
  });
  try {
    const updated = await apiClient.patch<AgentRegistryEntry>(`/v1/agents/${agentId}`, payload);
    await razeLog('INFO', 'Agent registry updated', {
      agent_id: agentId,
    });
    return updated;
  } catch (error) {
    await razeLog('ERROR', 'Agent registry update failed', {
      agent_id: agentId,
      error: normalizeApiError(error, 'Failed to update agent'),
    });
    throw error;
  }
}

export async function createRegistryAgentVersion(
  agentId: string,
  payload: CreateAgentVersionInput
): Promise<AgentRegistryVersion> {
  await razeLog('INFO', 'Agent registry version create requested', {
    agent_id: agentId,
  });
  try {
    const created = await apiClient.post<AgentRegistryVersion>(`/v1/agents/${agentId}/versions`, payload);
    await razeLog('INFO', 'Agent registry version created', {
      agent_id: agentId,
      version: created.version,
    });
    return created;
  } catch (error) {
    await razeLog('ERROR', 'Agent registry version create failed', {
      agent_id: agentId,
      error: normalizeApiError(error, 'Failed to create agent version'),
    });
    throw error;
  }
}

export async function publishRegistryAgent(agentId: string, payload: PublishAgentInput): Promise<AgentRegistryEntry> {
  await razeLog('INFO', 'Agent registry publish requested', {
    agent_id: agentId,
    version: payload.version ?? 'latest',
  });
  try {
    const updated = await apiClient.post<AgentRegistryEntry>(`/v1/agents/${agentId}:publish`, payload);
    await razeLog('INFO', 'Agent registry published', {
      agent_id: agentId,
      status: updated.status,
    });
    return updated;
  } catch (error) {
    await razeLog('ERROR', 'Agent registry publish failed', {
      agent_id: agentId,
      error: normalizeApiError(error, 'Failed to publish agent'),
    });
    throw error;
  }
}

export async function assignRegistryAgentToOrg(payload: AgentAssignmentInput): Promise<OrgAgent> {
  await razeLog('INFO', 'Agent assignment requested', {
    agent_id: payload.agent.agent_id,
    org_id: payload.orgId,
    project_id: payload.projectId ?? null,
  });
  const body = {
    name: payload.agent.name,
    project_id: payload.projectId ?? undefined,
    agent_type: 'custom',
    capabilities: payload.capabilities ?? payload.agent.tags ?? [],
    config: {
      registry_agent_id: payload.agent.agent_id,
      registry_agent_slug: payload.agent.slug,
      registry_agent_version: payload.agent.latest_version,
      registry_visibility: payload.agent.visibility,
      registry_role_alignment: payload.roleAlignment ?? null,
    },
  };
  try {
    const assigned = await apiClient.post<OrgAgent>(`/v1/orgs/${payload.orgId}/agents`, body);
    await razeLog('INFO', 'Agent assigned to org/project', {
      agent_id: payload.agent.agent_id,
      org_id: payload.orgId,
      assigned_id: assigned.id,
    });
    return assigned;
  } catch (error) {
    await razeLog('ERROR', 'Agent assignment failed', {
      agent_id: payload.agent.agent_id,
      org_id: payload.orgId,
      error: normalizeApiError(error, 'Failed to assign agent'),
    });
    throw error;
  }
}

export async function assignRegistryAgentToPersonalProject(
  payload: PersonalAgentAssignmentInput
): Promise<OrgAgent> {
  await razeLog('INFO', 'Agent assignment requested', {
    agent_id: payload.agent.agent_id,
    org_id: null,
    project_id: payload.projectId,
  });
  const body = {
    name: payload.agent.name,
    project_id: payload.projectId,
    agent_type: 'custom',
    capabilities: payload.capabilities ?? payload.agent.tags ?? [],
    config: {
      registry_agent_id: payload.agent.agent_id,
      registry_agent_slug: payload.agent.slug,
      registry_agent_version: payload.agent.latest_version,
      registry_visibility: payload.agent.visibility,
      registry_role_alignment: payload.roleAlignment ?? null,
    },
  };
  try {
    const assigned = await apiClient.post<OrgAgent>('/v1/projects/agents', body);
    await razeLog('INFO', 'Agent assigned to personal project', {
      agent_id: payload.agent.agent_id,
      assigned_id: assigned.id,
      project_id: payload.projectId,
    });
    return assigned;
  } catch (error) {
    await razeLog('ERROR', 'Agent assignment failed', {
      agent_id: payload.agent.agent_id,
      error: normalizeApiError(error, 'Failed to assign agent'),
    });
    throw error;
  }
}

export async function unassignRegistryAgentFromOrg(orgId: string, orgAgentId: string): Promise<void> {
  await razeLog('INFO', 'Agent unassign requested', {
    org_id: orgId,
    org_agent_id: orgAgentId,
  });
  try {
    await apiClient.delete<void>(`/v1/orgs/${orgId}/agents/${orgAgentId}`);
    await razeLog('INFO', 'Agent unassigned', {
      org_id: orgId,
      org_agent_id: orgAgentId,
    });
  } catch (error) {
    await razeLog('ERROR', 'Agent unassign failed', {
      org_id: orgId,
      org_agent_id: orgAgentId,
      error: normalizeApiError(error, 'Failed to unassign agent'),
    });
    throw error;
  }
}

export async function unassignRegistryAgentFromPersonalProject(orgAgentId: string): Promise<void> {
  await razeLog('INFO', 'Agent unassign requested', {
    org_id: null,
    org_agent_id: orgAgentId,
  });
  try {
    await apiClient.delete<void>(`/v1/projects/agents/${orgAgentId}`);
    await razeLog('INFO', 'Agent unassigned', {
      org_id: null,
      org_agent_id: orgAgentId,
    });
  } catch (error) {
    await razeLog('ERROR', 'Agent unassign failed', {
      org_id: null,
      org_agent_id: orgAgentId,
      error: normalizeApiError(error, 'Failed to unassign agent'),
    });
    throw error;
  }
}

export function useCreateRegistryAgent() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: createRegistryAgent,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: agentRegistryKeys.all });
      await queryClient.invalidateQueries({ queryKey: dashboardKeys.stats() });
    },
  });
}

export function useUpdateRegistryAgent() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ agentId, payload }: { agentId: string; payload: UpdateAgentInput }) =>
      updateRegistryAgent(agentId, payload),
    onSuccess: async (_data, variables) => {
      await queryClient.invalidateQueries({ queryKey: agentRegistryKeys.detail(variables.agentId) });
      await queryClient.invalidateQueries({ queryKey: agentRegistryKeys.all });
    },
  });
}

export function useCreateRegistryAgentVersion() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ agentId, payload }: { agentId: string; payload: CreateAgentVersionInput }) =>
      createRegistryAgentVersion(agentId, payload),
    onSuccess: async (_data, variables) => {
      await queryClient.invalidateQueries({ queryKey: agentRegistryKeys.detail(variables.agentId) });
      await queryClient.invalidateQueries({ queryKey: agentRegistryKeys.all });
    },
  });
}

export function usePublishRegistryAgent() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ agentId, payload }: { agentId: string; payload: PublishAgentInput }) =>
      publishRegistryAgent(agentId, payload),
    onSuccess: async (_data, variables) => {
      await queryClient.invalidateQueries({ queryKey: agentRegistryKeys.detail(variables.agentId) });
      await queryClient.invalidateQueries({ queryKey: agentRegistryKeys.all });
      await queryClient.invalidateQueries({ queryKey: dashboardKeys.stats() });
    },
  });
}

export function useAssignRegistryAgent() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: assignRegistryAgentToOrg,
    onSuccess: async (_data, variables) => {
      await queryClient.invalidateQueries({ queryKey: dashboardKeys.agents(variables.orgId) });
    },
  });
}

export function useAssignRegistryAgentToPersonalProject() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: assignRegistryAgentToPersonalProject,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: agentRegistryKeys.personalAgents() });
    },
  });
}

export function useUnassignRegistryAgent() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ orgId, orgAgentId }: { orgId: string; orgAgentId: string }) =>
      unassignRegistryAgentFromOrg(orgId, orgAgentId),
    onSuccess: async (_data, variables) => {
      await queryClient.invalidateQueries({ queryKey: dashboardKeys.agents(variables.orgId) });
    },
  });
}

export function useUnassignRegistryAgentFromPersonalProject() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ orgAgentId }: { orgAgentId: string }) =>
      unassignRegistryAgentFromPersonalProject(orgAgentId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: agentRegistryKeys.personalAgents() });
    },
  });
}
