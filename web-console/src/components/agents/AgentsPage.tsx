/**
 * Agent Registry Page
 *
 * Discover, publish, assign, and manage agents from the registry.
 * Following COLLAB_SAAS_REQUIREMENTS.md for fast, floaty UX.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useLocation, useNavigate, useParams } from 'react-router-dom';
import { WorkspaceShell } from '../workspace/WorkspaceShell';
import { ConsoleSidebar } from '../ConsoleSidebar';
import { useOrganizations, useProjects, useAgents } from '../../api/dashboard';
import { useOrgContext } from '../../store/orgContextStore';
import { useAuth } from '../../contexts/AuthContext';
import {
  useAgentRegistry,
  useAgentRegistryDetail,
  useCreateRegistryAgent,
  useUpdateRegistryAgent,
  useCreateRegistryAgentVersion,
  usePublishRegistryAgent,
  useAssignRegistryAgent,
  useUnassignRegistryAgent,
  usePersonalAgents,
  useAssignRegistryAgentToPersonalProject,
  useUnassignRegistryAgentFromPersonalProject,
  type AgentRegistryEntry,
  type AgentRegistryVersion,
  type AgentRegistryListItem,
  type UpdateAgentInput,
  type CreateAgentVersionInput,
  type AgentVisibility,
  type AgentStatus,
  type RoleAlignment,
} from '../../api/agentRegistry';
import './AgentsPage.css';

type PanelMode = 'detail' | 'create';
type ProjectFilter = 'all' | 'assigned' | 'unassigned';

interface AgentFormState {
  name: string;
  description: string;
  visibility: AgentVisibility;
  tags: string;
  mission: string;
  roleAlignment: RoleAlignment;
  capabilities: string;
  defaultBehaviors: string;
  playbookContent: string;
}

interface CreateAgentState extends AgentFormState {
  slug: string;
  requestApiCredentials: boolean;
  publishOnCreate: boolean;
  orgScopeId: string | null;
}

const VISIBILITY_FILTERS: Array<{ label: string; value: AgentVisibility | 'all' }> = [
  { label: 'All', value: 'all' },
  { label: 'Public', value: 'PUBLIC' },
  { label: 'Org', value: 'ORGANIZATION' },
  { label: 'Private', value: 'PRIVATE' },
];

const ROLE_FILTERS: Array<{ label: string; value: RoleAlignment | 'all' }> = [
  { label: 'Any role', value: 'all' },
  { label: 'Student', value: 'STUDENT' },
  { label: 'Teacher', value: 'TEACHER' },
  { label: 'Strategist', value: 'STRATEGIST' },
  { label: 'Multi-role', value: 'MULTI_ROLE' },
];

const STATUS_FILTERS: Array<{ label: string; value: AgentStatus | 'all' }> = [
  { label: 'Any status', value: 'all' },
  { label: 'Draft', value: 'DRAFT' },
  { label: 'Active', value: 'ACTIVE' },
  { label: 'Deprecated', value: 'DEPRECATED' },
];

const PROJECT_FILTERS: Array<{ label: string; value: ProjectFilter }> = [
  { label: 'All', value: 'all' },
  { label: 'Assigned', value: 'assigned' },
  { label: 'Unassigned', value: 'unassigned' },
];

const ROLE_OPTIONS: RoleAlignment[] = ['STUDENT', 'TEACHER', 'STRATEGIST', 'MULTI_ROLE'];
const STATUS_LABELS: Record<AgentStatus, string> = {
  DRAFT: 'Draft',
  ACTIVE: 'Active',
  DEPRECATED: 'Deprecated',
};

const VISIBILITY_LABELS: Record<AgentVisibility, string> = {
  PRIVATE: 'Private',
  ORGANIZATION: 'Organization',
  PUBLIC: 'Public',
};

function slugify(name: string): string {
  return name
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9\\s-]/g, '')
    .replace(/\\s+/g, '-')
    .replace(/-+/g, '-')
    .replace(/^-|-$/g, '');
}

function validateName(name: string): string | null {
  const trimmed = name.trim();
  if (!trimmed) return 'Agent name is required';
  if (trimmed.length < 3) return 'Agent name must be at least 3 characters';
  if (trimmed.length > 80) return 'Agent name must be 80 characters or less';
  return null;
}

function validateSlug(slug: string): string | null {
  const trimmed = slug.trim();
  if (!trimmed) return null;
  if (!/^[a-z0-9-]+$/.test(trimmed)) return 'Slug can only use lowercase letters, numbers, and dashes';
  return null;
}

function parseCommaList(value: string): string[] {
  return value
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean);
}

function normalizeList(value: string[]): string[] {
  return value.map((item) => item.trim().toLowerCase()).filter(Boolean).sort();
}

function listsEqual(a: string[], b: string[]): boolean {
  const left = normalizeList(a);
  const right = normalizeList(b);
  if (left.length !== right.length) return false;
  return left.every((item, index) => item === right[index]);
}

function formatRelativeTime(dateString?: string): string {
  if (!dateString) return 'Unknown';
  const updated = new Date(dateString);
  const now = new Date();
  const diffMs = now.getTime() - updated.getTime();
  const diffMins = Math.floor(diffMs / 60000);

  if (diffMins < 1) return 'Just now';
  if (diffMins < 60) return `${diffMins}m ago`;
  const diffHours = Math.floor(diffMins / 60);
  if (diffHours < 24) return `${diffHours}h ago`;
  const diffDays = Math.floor(diffHours / 24);
  if (diffDays < 7) return `${diffDays}d ago`;
  return updated.toLocaleDateString();
}

function pickActiveVersion(agentDetail: { versions: AgentRegistryVersion[] } | null, agent: AgentRegistryEntry | null) {
  if (!agentDetail || agentDetail.versions.length === 0) return null;
  if (agent?.latest_version) {
    const match = agentDetail.versions.find((version) => version.version === agent.latest_version);
    if (match) return match;
  }
  const active = agentDetail.versions.find((version) => version.status === 'ACTIVE');
  return active ?? agentDetail.versions[0];
}

function useSelectedAgentItem(items: AgentRegistryListItem[], selectedId: string | null) {
  return useMemo(
    () => items.find((item) => item.agent.agent_id === selectedId) ?? null,
    [items, selectedId]
  );
}

export function AgentsPage(): React.JSX.Element {
  const navigate = useNavigate();
  const location = useLocation();
  const { agentId } = useParams();
  const { currentOrgId } = useOrgContext();
  const { data: organizations = [] } = useOrganizations();
  const { actor } = useAuth();

  const [panelMode, setPanelMode] = useState<PanelMode>('detail');
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [visibilityFilter, setVisibilityFilter] = useState<AgentVisibility | 'all'>('all');
  const [roleFilter, setRoleFilter] = useState<RoleAlignment | 'all'>('all');
  const [statusFilter, setStatusFilter] = useState<AgentStatus | 'all'>('all');
  const [includeBuiltin, setIncludeBuiltin] = useState(true);
  const [actionError, setActionError] = useState<string | null>(null);
  const [isEditing, setIsEditing] = useState(false);
  const [credentials, setCredentials] = useState<{ client_id: string; client_secret: string } | null>(null);

  const [editState, setEditState] = useState<AgentFormState>({
    name: '',
    description: '',
    visibility: 'PRIVATE',
    tags: '',
    mission: '',
    roleAlignment: 'STUDENT',
    capabilities: '',
    defaultBehaviors: '',
    playbookContent: '',
  });

  const [createState, setCreateState] = useState<CreateAgentState>({
    name: '',
    slug: '',
    description: '',
    visibility: 'PRIVATE',
    tags: '',
    mission: '',
    roleAlignment: 'STUDENT',
    capabilities: '',
    defaultBehaviors: '',
    playbookContent: '',
    requestApiCredentials: false,
    publishOnCreate: true,
    orgScopeId: currentOrgId ?? null,
  });
  const [createSlugEdited, setCreateSlugEdited] = useState(false);
  const [assignmentOrgId, setAssignmentOrgId] = useState<string | null>(currentOrgId ?? null);
  const [assignmentScopeTouched, setAssignmentScopeTouched] = useState(false);
  const [projectQuery, setProjectQuery] = useState('');
  const [projectFilter, setProjectFilter] = useState<ProjectFilter>('all');
  const [bulkActionPending, setBulkActionPending] = useState(false);

  const createMutation = useCreateRegistryAgent();
  const updateMutation = useUpdateRegistryAgent();
  const versionMutation = useCreateRegistryAgentVersion();
  const publishMutation = usePublishRegistryAgent();
  const assignMutation = useAssignRegistryAgent();
  const unassignMutation = useUnassignRegistryAgent();
  const assignPersonalMutation = useAssignRegistryAgentToPersonalProject();
  const unassignPersonalMutation = useUnassignRegistryAgentFromPersonalProject();

  const filters = useMemo(
    () => ({
      query,
      visibility: visibilityFilter === 'all' ? undefined : visibilityFilter,
      roleAlignment: roleFilter === 'all' ? undefined : roleFilter,
      status: statusFilter === 'all' ? undefined : statusFilter,
      includeBuiltin,
      limit: 50,
    }),
    [query, visibilityFilter, roleFilter, statusFilter, includeBuiltin]
  );

  const {
    data: registryItems = [],
    isLoading: registryLoading,
    isError: registryError,
    refetch: refetchRegistry,
  } = useAgentRegistry(filters);
  const selectedItem = useSelectedAgentItem(registryItems, selectedAgentId);
  const { data: agentDetail } = useAgentRegistryDetail(selectedAgentId);
  const selectedAgent = agentDetail?.agent ?? selectedItem?.agent ?? null;
  const activeVersion = useMemo(
    () => pickActiveVersion(agentDetail ?? null, selectedAgent),
    [agentDetail, selectedAgent]
  );

  const { data: assignmentProjects = [] } = useProjects(assignmentOrgId ?? undefined);
  const { data: assignmentAgentsRaw = [] } = useAgents(assignmentOrgId ?? undefined, Boolean(assignmentOrgId));
  const { data: personalAssignmentAgents = [] } = usePersonalAgents(!assignmentOrgId);
  const assignmentAgents = useMemo(
    () => (assignmentOrgId ? assignmentAgentsRaw : personalAssignmentAgents),
    [assignmentAgentsRaw, assignmentOrgId, personalAssignmentAgents]
  );

  const assignmentIndex = useMemo(() => {
    const map = new Map<string, { org: number; projects: number }>();
    assignmentAgents.forEach((agent) => {
      const config = (agent.config ?? {}) as Record<string, unknown>;
      const registryId = typeof config.registry_agent_id === 'string' ? config.registry_agent_id : null;
      const registrySlug = typeof config.registry_agent_slug === 'string' ? config.registry_agent_slug : null;
      const key = registryId ?? registrySlug;
      if (!key) return;
      const entry = map.get(key) ?? { org: 0, projects: 0 };
      if (agent.project_id) {
        entry.projects += 1;
      } else {
        entry.org += 1;
      }
      map.set(key, entry);
    });
    return map;
  }, [assignmentAgents]);

  const agentCounts = useMemo(() => {
    const items = registryItems.map((item) => item.agent);
    const total = items.length;
    const publicCount = items.filter((agent) => agent.visibility === 'PUBLIC').length;
    const orgCount = items.filter((agent) => agent.visibility === 'ORGANIZATION').length;
    const privateCount = items.filter((agent) => agent.visibility === 'PRIVATE').length;
    const builtinCount = items.filter((agent) => agent.is_builtin).length;
    return { total, publicCount, orgCount, privateCount, builtinCount };
  }, [registryItems]);

  const assignmentMatches = useMemo(() => {
    if (!selectedAgent) return [];
    return assignmentAgents.filter((agent) => {
      const config = (agent.config ?? {}) as Record<string, unknown>;
      const registryId = typeof config.registry_agent_id === 'string' ? config.registry_agent_id : null;
      const registrySlug = typeof config.registry_agent_slug === 'string' ? config.registry_agent_slug : null;
      return registryId === selectedAgent.agent_id || registrySlug === selectedAgent.slug;
    });
  }, [assignmentAgents, selectedAgent]);

  const orgAssignment = useMemo(
    () => (assignmentOrgId ? assignmentMatches.find((agent) => !agent.project_id) ?? null : null),
    [assignmentMatches, assignmentOrgId]
  );

  const projectAssignments = useMemo(() => {
    const mapping = new Map<string, string>();
    assignmentMatches.forEach((agent) => {
      if (agent.project_id) {
        mapping.set(agent.project_id, agent.id);
      }
    });
    return mapping;
  }, [assignmentMatches]);

  const projectFilterOptions = useMemo(() => {
    if (orgAssignment) {
      return [
        { label: 'All', value: 'all' },
        { label: 'Pinned', value: 'assigned' },
        { label: 'Inherited', value: 'unassigned' },
      ];
    }
    return PROJECT_FILTERS;
  }, [orgAssignment]);

  const hasOrganizations = organizations.length > 0;

  const selectedOrganization = useMemo(
    () => organizations.find((org) => org.id === assignmentOrgId) ?? null,
    [assignmentOrgId, organizations]
  );

  const visibilityLabel = selectedAgent
    ? VISIBILITY_LABELS[selectedAgent.visibility ?? 'PRIVATE']
    : VISIBILITY_LABELS.PRIVATE;

  const isPrivateAgent = selectedAgent?.visibility === 'PRIVATE';
  const isOwner = Boolean(selectedAgent?.owner_id && actor?.id && selectedAgent.owner_id === actor.id);
  const assignmentLocked = Boolean(selectedAgent && isPrivateAgent && !isOwner);

  const visibilityHint = useMemo(() => {
    if (!selectedAgent) return '';
    if (selectedAgent.visibility === 'PRIVATE') {
      if (assignmentLocked) {
        return 'This private agent was assigned by its owner. Only the owner can change assignments.';
      }
      return 'Private agents stay visible only to you until you assign them to an org or project. Once assigned, members can use them within that scope.';
    }
    if (selectedAgent.visibility === 'ORGANIZATION') {
      return 'Organization agents appear in the registry for org members and can still be scoped to specific projects.';
    }
    return 'Public agents are discoverable by everyone. Assignments let you pin usage to specific orgs or projects.';
  }, [assignmentLocked, selectedAgent]);

  const filteredProjects = useMemo(() => {
    const normalizedQuery = projectQuery.trim().toLowerCase();
    return assignmentProjects
      .filter((project) => {
        const pinned = projectAssignments.has(project.id);
        const inherited = Boolean(orgAssignment) && !pinned;
        if (projectFilter === 'assigned') {
          if (orgAssignment) return pinned;
          return pinned;
        }
        if (projectFilter === 'unassigned') {
          if (orgAssignment) return inherited;
          return !pinned;
        }
        if (!normalizedQuery) return true;
        const nameMatch = project.name.toLowerCase().includes(normalizedQuery);
        const slugMatch = (project.slug ?? '').toLowerCase().includes(normalizedQuery);
        return nameMatch || slugMatch;
      })
      .sort((left, right) => {
        const leftPinned = projectAssignments.has(left.id);
        const rightPinned = projectAssignments.has(right.id);
        if (leftPinned !== rightPinned) {
          return leftPinned ? -1 : 1;
        }
        return left.name.localeCompare(right.name);
      });
  }, [assignmentProjects, orgAssignment, projectAssignments, projectFilter, projectQuery]);

  useEffect(() => {
    const isCreateRoute = location.pathname.endsWith('/new');
    setPanelMode(isCreateRoute ? 'create' : 'detail');
  }, [location.pathname]);

  useEffect(() => {
    if (agentId && agentId !== selectedAgentId) {
      setSelectedAgentId(agentId);
      return;
    }
    if (panelMode === 'create') return;
    if (!selectedAgentId && registryItems.length > 0) {
      setSelectedAgentId(registryItems[0].agent.agent_id);
    }
  }, [agentId, panelMode, registryItems, selectedAgentId]);

  useEffect(() => {
    if (!selectedAgent || !activeVersion) return;
    setEditState({
      name: selectedAgent.name,
      description: selectedAgent.description ?? '',
      visibility: selectedAgent.visibility ?? 'PRIVATE',
      tags: (selectedAgent.tags ?? []).join(', '),
      mission: activeVersion.mission ?? '',
      roleAlignment: activeVersion.role_alignment ?? 'STUDENT',
      capabilities: (activeVersion.capabilities ?? []).join(', '),
      defaultBehaviors: (activeVersion.default_behaviors ?? []).join(', '),
      playbookContent: activeVersion.playbook_content ?? '',
    });
    setIsEditing(false);
    setActionError(null);
  }, [activeVersion, selectedAgent]);

  useEffect(() => {
    if (assignmentScopeTouched) return;
    if (currentOrgId && assignmentOrgId !== currentOrgId) {
      setAssignmentOrgId(currentOrgId);
      return;
    }
    if (!assignmentOrgId && organizations.length > 0) {
      setAssignmentOrgId(organizations[0].id);
    }
  }, [assignmentOrgId, assignmentScopeTouched, currentOrgId, organizations]);

  useEffect(() => {
    if (!createState.orgScopeId && currentOrgId) {
      setCreateState((prev) => ({ ...prev, orgScopeId: currentOrgId }));
    }
  }, [currentOrgId, createState.orgScopeId]);

  const handleSelectAgent = useCallback(
    (agentId: string) => {
      setSelectedAgentId(agentId);
      setPanelMode('detail');
      navigate(`/agents/${agentId}`, { replace: true });
    },
    [navigate]
  );

  const handleCreateMode = useCallback(() => {
    setPanelMode('create');
    setActionError(null);
    setCredentials(null);
    navigate('/agents/new');
  }, [navigate]);

  const handleCancelCreate = useCallback(() => {
    setPanelMode('detail');
    setActionError(null);
    setCredentials(null);
    navigate('/agents');
  }, [navigate]);

  const handleEditToggle = useCallback(() => {
    setIsEditing((prev) => !prev);
    setActionError(null);
  }, []);

  const handleCreateNameChange = useCallback(
    (next: string) => {
      setCreateState((prev) => ({
        ...prev,
        name: next,
        slug: createSlugEdited ? prev.slug : slugify(next),
      }));
    },
    [createSlugEdited]
  );

  const handleCreateSlugChange = useCallback((next: string) => {
    setCreateSlugEdited(true);
    setCreateState((prev) => ({ ...prev, slug: next.toLowerCase() }));
  }, []);

  const handleEditStateChange = useCallback(
    <Key extends keyof AgentFormState>(key: Key, value: AgentFormState[Key]) => {
      setEditState((prev) => ({ ...prev, [key]: value }));
    },
    []
  );

  const handleCreateStateChange = useCallback(
    <Key extends keyof CreateAgentState>(key: Key, value: CreateAgentState[Key]) => {
      setCreateState((prev) => ({ ...prev, [key]: value }));
    },
    []
  );

  const handleAssignmentOrgChange = useCallback((nextOrgId: string | null) => {
    setAssignmentOrgId(nextOrgId);
    setAssignmentScopeTouched(true);
  }, []);

  const handleUpdateAgent = useCallback(async () => {
    if (!selectedAgent || !activeVersion) return;
    const nameError = validateName(editState.name);
    if (nameError) {
      setActionError(nameError);
      return;
    }

    const nextTags = parseCommaList(editState.tags);
    const agentUpdates: UpdateAgentInput = {};

    if (editState.name.trim() !== selectedAgent.name) {
      agentUpdates.name = editState.name.trim();
    }
    if ((editState.description ?? '').trim() !== (selectedAgent.description ?? '').trim()) {
      agentUpdates.description = editState.description.trim();
    }
    if (!listsEqual(nextTags, selectedAgent.tags ?? [])) {
      agentUpdates.tags = nextTags;
    }
    if (editState.visibility !== selectedAgent.visibility) {
      agentUpdates.visibility = editState.visibility;
    }
    if (Object.keys(agentUpdates).length > 0) {
      agentUpdates.latest_version = selectedAgent.latest_version;
    }

    const versionUpdates: CreateAgentVersionInput = {};
    const nextCapabilities = parseCommaList(editState.capabilities);
    const nextBehaviors = parseCommaList(editState.defaultBehaviors);

    if ((editState.mission ?? '').trim() !== (activeVersion.mission ?? '').trim()) {
      versionUpdates.mission = editState.mission.trim();
    }
    if (editState.roleAlignment !== activeVersion.role_alignment) {
      versionUpdates.role_alignment = editState.roleAlignment;
    }
    if (!listsEqual(nextCapabilities, activeVersion.capabilities ?? [])) {
      versionUpdates.capabilities = nextCapabilities;
    }
    if (!listsEqual(nextBehaviors, activeVersion.default_behaviors ?? [])) {
      versionUpdates.default_behaviors = nextBehaviors;
    }
    if ((editState.playbookContent ?? '').trim() !== (activeVersion.playbook_content ?? '').trim()) {
      versionUpdates.playbook_content = editState.playbookContent.trim();
    }

    setActionError(null);
    try {
      if (Object.keys(agentUpdates).length > 0) {
        await updateMutation.mutateAsync({
          agentId: selectedAgent.agent_id,
          payload: agentUpdates,
        });
      }
      if (Object.keys(versionUpdates).length > 0) {
        await versionMutation.mutateAsync({
          agentId: selectedAgent.agent_id,
          payload: {
            ...versionUpdates,
            base_version: selectedAgent.latest_version,
          },
        });
      }
      setIsEditing(false);
    } catch (error) {
      setActionError(error instanceof Error ? error.message : 'Failed to save changes');
    }
  }, [activeVersion, editState, selectedAgent, updateMutation, versionMutation]);

  const handlePublish = useCallback(async () => {
    if (!selectedAgent) return;
    setActionError(null);
    try {
      await publishMutation.mutateAsync({
        agentId: selectedAgent.agent_id,
        payload: {
          version: selectedAgent.latest_version,
          visibility: selectedAgent.visibility,
        },
      });
    } catch (error) {
      setActionError(error instanceof Error ? error.message : 'Failed to publish agent');
    }
  }, [publishMutation, selectedAgent]);

  const handleCreateAgent = useCallback(async () => {
    const nameError = validateName(createState.name);
    const slugError = validateSlug(createState.slug);
    if (nameError || slugError) {
      setActionError(nameError ?? slugError ?? null);
      return;
    }
    if (!createState.mission.trim()) {
      setActionError('Mission is required');
      return;
    }

    setActionError(null);
    try {
      const created = await createMutation.mutateAsync({
        name: createState.name.trim(),
        slug: createState.slug.trim() || undefined,
        description: createState.description.trim(),
        mission: createState.mission.trim(),
        role_alignment: createState.roleAlignment,
        capabilities: parseCommaList(createState.capabilities),
        default_behaviors: parseCommaList(createState.defaultBehaviors),
        playbook_content: createState.playbookContent.trim(),
        tags: parseCommaList(createState.tags),
        visibility: createState.visibility,
        request_api_credentials: createState.requestApiCredentials,
        org_id: createState.orgScopeId ?? undefined,
      });

      if (created.credentials) {
        setCredentials(created.credentials);
      }

      if (createState.publishOnCreate) {
        await publishMutation.mutateAsync({
          agentId: created.agent_id,
          payload: {
            version: created.latest_version,
            visibility: created.visibility,
          },
        });
      }

      setCreateState((prev) => ({
        ...prev,
        name: '',
        slug: '',
        description: '',
        mission: '',
        tags: '',
        capabilities: '',
        defaultBehaviors: '',
        playbookContent: '',
        requestApiCredentials: false,
      }));
      setCreateSlugEdited(false);
      setPanelMode('detail');
      setSelectedAgentId(created.agent_id);
      navigate(`/agents/${created.agent_id}`);
    } catch (error) {
      setActionError(error instanceof Error ? error.message : 'Failed to create agent');
    }
  }, [createMutation, createState, navigate, publishMutation]);

  const handleAssignOrg = useCallback(async () => {
    if (!selectedAgent || !assignmentOrgId) return;
    try {
      await assignMutation.mutateAsync({
        orgId: assignmentOrgId,
        agent: selectedAgent,
        roleAlignment: activeVersion?.role_alignment,
        capabilities: activeVersion?.capabilities ?? [],
      });
    } catch (error) {
      setActionError(error instanceof Error ? error.message : 'Failed to assign agent');
    }
  }, [activeVersion, assignMutation, assignmentOrgId, selectedAgent]);

  const handleUnassignOrg = useCallback(async () => {
    if (!assignmentOrgId || !orgAssignment) return;
    try {
      await unassignMutation.mutateAsync({
        orgId: assignmentOrgId,
        orgAgentId: orgAssignment.id,
      });
    } catch (error) {
      setActionError(error instanceof Error ? error.message : 'Failed to unassign agent');
    }
  }, [assignmentOrgId, orgAssignment, unassignMutation]);

  const handleAssignAllProjects = useCallback(async () => {
    if (!selectedAgent) return;
    setActionError(null);
    setBulkActionPending(true);
    try {
      for (const project of assignmentProjects) {
        if (!projectAssignments.has(project.id)) {
          if (assignmentOrgId) {
            await assignMutation.mutateAsync({
              orgId: assignmentOrgId,
              agent: selectedAgent,
              projectId: project.id,
              roleAlignment: activeVersion?.role_alignment,
              capabilities: activeVersion?.capabilities ?? [],
            });
          } else {
            await assignPersonalMutation.mutateAsync({
              agent: selectedAgent,
              projectId: project.id,
              roleAlignment: activeVersion?.role_alignment,
              capabilities: activeVersion?.capabilities ?? [],
            });
          }
        }
      }
    } catch (error) {
      setActionError(error instanceof Error ? error.message : 'Failed to assign to all projects');
    } finally {
      setBulkActionPending(false);
    }
  }, [
    activeVersion,
    assignMutation,
    assignPersonalMutation,
    assignmentOrgId,
    assignmentProjects,
    projectAssignments,
    selectedAgent,
  ]);

  const handleClearAllProjects = useCallback(async () => {
    if (projectAssignments.size === 0) return;
    setActionError(null);
    setBulkActionPending(true);
    try {
      for (const orgAgentId of projectAssignments.values()) {
        if (assignmentOrgId) {
          await unassignMutation.mutateAsync({
            orgId: assignmentOrgId,
            orgAgentId,
          });
        } else {
          await unassignPersonalMutation.mutateAsync({
            orgAgentId,
          });
        }
      }
    } catch (error) {
      setActionError(error instanceof Error ? error.message : 'Failed to clear project assignments');
    } finally {
      setBulkActionPending(false);
    }
  }, [assignmentOrgId, projectAssignments, unassignMutation, unassignPersonalMutation]);

  const handleToggleProjectAssignment = useCallback(
    async (projectId: string) => {
      if (!selectedAgent) return;
      const assignedId = projectAssignments.get(projectId);
      try {
        if (assignedId) {
          if (assignmentOrgId) {
            await unassignMutation.mutateAsync({
              orgId: assignmentOrgId,
              orgAgentId: assignedId,
            });
          } else {
            await unassignPersonalMutation.mutateAsync({
              orgAgentId: assignedId,
            });
          }
        } else if (assignmentOrgId) {
          await assignMutation.mutateAsync({
            orgId: assignmentOrgId,
            agent: selectedAgent,
            projectId,
            roleAlignment: activeVersion?.role_alignment,
            capabilities: activeVersion?.capabilities ?? [],
          });
        } else {
          await assignPersonalMutation.mutateAsync({
            agent: selectedAgent,
            projectId,
            roleAlignment: activeVersion?.role_alignment,
            capabilities: activeVersion?.capabilities ?? [],
          });
        }
      } catch (error) {
        setActionError(error instanceof Error ? error.message : 'Failed to update assignment');
      }
    },
    [
      activeVersion,
      assignMutation,
      assignPersonalMutation,
      assignmentOrgId,
      projectAssignments,
      selectedAgent,
      unassignMutation,
      unassignPersonalMutation,
    ]
  );

  const showRegistryError = registryError && registryItems.length === 0;
  const showRegistryEmpty = !registryLoading && registryItems.length === 0;

  const isBuiltin = selectedAgent?.is_builtin ?? false;
  const nameError = validateName(editState.name);
  const projectAssignmentCount = projectAssignments.size;
  const projectTotalCount = assignmentProjects.length;
  const assignmentSummary = projectTotalCount > 0
    ? orgAssignment
      ? 'All projects'
      : `${projectAssignmentCount}/${projectTotalCount}`
    : 'No projects';
  const pinSummary = orgAssignment ? `${projectAssignmentCount}` : null;
  const assignmentScopeLabel = assignmentOrgId
    ? selectedOrganization?.name ?? 'Organization'
    : 'Personal workspace';
  const projectResultsLabel = projectTotalCount > 0
    ? `${filteredProjects.length} of ${projectTotalCount} projects`
    : assignmentOrgId
      ? 'No projects yet'
      : 'No personal projects yet';
  const mutationPending = assignmentOrgId
    ? assignMutation.isPending || unassignMutation.isPending
    : assignPersonalMutation.isPending || unassignPersonalMutation.isPending;
  const bulkActionsDisabled = bulkActionPending || mutationPending || assignmentLocked;

  return (
    <WorkspaceShell
      sidebarContent={<ConsoleSidebar selectedId="agents" onNavigate={(path) => navigate(path)} />}
      documentTitle="Agents"
    >
      <div className="agents-page">
        <header className="agents-header">
          <div className="agents-header-left">
            <h1 className="agents-title animate-fade-in-up">Agent Registry</h1>
            <p className="agents-subtitle animate-fade-in-up">
              Discover platform agents, publish your own, and assign them across organizations and projects.
            </p>
          </div>
          <div className="agents-header-actions">
            <button
              type="button"
              className="agents-secondary-button pressable"
              onClick={() => void refetchRegistry()}
              data-haptic="light"
            >
              Refresh
            </button>
            <button
              type="button"
              className="agents-primary-button pressable"
              onClick={handleCreateMode}
              data-haptic="light"
            >
              New Agent
            </button>
          </div>
        </header>

        <section className="agents-metrics" aria-label="Agent registry stats">
          <div className="agents-metric-card">
            <span className="agents-metric-label">Total</span>
            <span className="agents-metric-value">{agentCounts.total}</span>
          </div>
          <div className="agents-metric-card">
            <span className="agents-metric-label">Public</span>
            <span className="agents-metric-value">{agentCounts.publicCount}</span>
          </div>
          <div className="agents-metric-card">
            <span className="agents-metric-label">Org</span>
            <span className="agents-metric-value">{agentCounts.orgCount}</span>
          </div>
          <div className="agents-metric-card">
            <span className="agents-metric-label">Private</span>
            <span className="agents-metric-value">{agentCounts.privateCount}</span>
          </div>
          <div className="agents-metric-card">
            <span className="agents-metric-label">Built-in</span>
            <span className="agents-metric-value">{agentCounts.builtinCount}</span>
          </div>
        </section>

        <section className="agents-filters" aria-label="Agent registry filters">
          <label className="agents-search">
            <span className="agents-search-label">Search</span>
            <input
              className="agents-search-input"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search by name, mission, tags..."
              autoComplete="off"
            />
          </label>

          <div className="agents-filter-group">
            <span className="agents-filter-label">Visibility</span>
            <div className="agents-filter-pills">
              {VISIBILITY_FILTERS.map((filter) => (
                <button
                  key={filter.value}
                  type="button"
                  className={`agents-filter-pill pressable ${visibilityFilter === filter.value ? 'active' : ''}`}
                  onClick={() => setVisibilityFilter(filter.value)}
                  data-haptic="light"
                >
                  {filter.label}
                </button>
              ))}
            </div>
          </div>

          <div className="agents-filter-row">
            <label className="agents-filter-select">
              <span className="agents-filter-label">Role</span>
              <select
                className="agents-select"
                value={roleFilter}
                onChange={(event) => setRoleFilter(event.target.value as RoleAlignment | 'all')}
              >
                {ROLE_FILTERS.map((filter) => (
                  <option key={filter.value} value={filter.value}>
                    {filter.label}
                  </option>
                ))}
              </select>
            </label>

            <label className="agents-filter-select">
              <span className="agents-filter-label">Status</span>
              <select
                className="agents-select"
                value={statusFilter}
                onChange={(event) => setStatusFilter(event.target.value as AgentStatus | 'all')}
              >
                {STATUS_FILTERS.map((filter) => (
                  <option key={filter.value} value={filter.value}>
                    {filter.label}
                  </option>
                ))}
              </select>
            </label>

            <button
              type="button"
              className={`agents-filter-toggle pressable ${includeBuiltin ? 'active' : ''}`}
              onClick={() => setIncludeBuiltin((prev) => !prev)}
              data-haptic="light"
            >
              {includeBuiltin ? 'Built-in on' : 'Built-in off'}
            </button>
          </div>
        </section>

        <section className="agents-layout" aria-label="Agent registry layout">
          <div className="agents-list-pane">
            <div className="agents-list-header">
              <h2 className="agents-section-title">Registry</h2>
              <span className="agents-list-count">{registryItems.length} agents</span>
            </div>
            <div className="agents-list">
              {registryLoading ? (
                <>
                  <div className="agents-list-card skeleton animate-shimmer" />
                  <div className="agents-list-card skeleton animate-shimmer" />
                  <div className="agents-list-card skeleton animate-shimmer" />
                </>
              ) : showRegistryError ? (
                <div className="agents-empty animate-fade-in-up">
                  <h3 className="agents-empty-title">Registry offline</h3>
                  <p className="agents-empty-description">
                    We couldn't load the agent registry. Retry to reconnect.
                  </p>
                  <button
                    type="button"
                    className="agents-primary-button pressable"
                    onClick={() => void refetchRegistry()}
                    data-haptic="light"
                  >
                    Retry
                  </button>
                </div>
              ) : showRegistryEmpty ? (
                <div className="agents-empty animate-fade-in-up">
                  <h3 className="agents-empty-title">No agents yet</h3>
                  <p className="agents-empty-description">
                    Publish your first agent or bootstrap the platform defaults.
                  </p>
                  <button
                    type="button"
                    className="agents-primary-button pressable"
                    onClick={handleCreateMode}
                    data-haptic="light"
                  >
                    Create Agent
                  </button>
                </div>
              ) : (
                registryItems.map((item) => {
                  const assignmentMeta = assignmentIndex.get(item.agent.agent_id)
                    ?? assignmentIndex.get(item.agent.slug);
                  const assignedToOrg = (assignmentMeta?.org ?? 0) > 0;
                  const assignedProjects = assignmentMeta?.projects ?? 0;

                  return (
                    <button
                      key={item.agent.agent_id}
                      type="button"
                      className={`agents-list-card pressable ${selectedAgentId === item.agent.agent_id ? 'active' : ''}`}
                      onClick={() => handleSelectAgent(item.agent.agent_id)}
                      data-haptic="light"
                    >
                      <div className="agents-list-card-top">
                        <div>
                          <span className="agents-list-name">{item.agent.name}</span>
                          <span className="agents-list-meta">{item.agent.slug}</span>
                        </div>
                        <span className={`agents-badge status-${(item.agent.status ?? 'DRAFT').toLowerCase()}`}>
                          {STATUS_LABELS[item.agent.status ?? 'DRAFT']}
                        </span>
                      </div>
                      <p className="agents-list-description">{item.agent.description || 'No description yet.'}</p>
                      <div className="agents-list-tags">
                        {(item.agent.tags ?? []).slice(0, 3).map((tag) => (
                          <span key={tag} className="agents-pill">
                            {tag}
                          </span>
                        ))}
                        {item.agent.is_builtin && (
                          <span className="agents-pill builtin">Built-in</span>
                        )}
                        <span className="agents-pill subtle">{VISIBILITY_LABELS[item.agent.visibility ?? 'PRIVATE']}</span>
                        {assignedToOrg && (
                          <span className="agents-pill assigned">Org access</span>
                        )}
                        {assignedProjects > 0 && (
                          <span className="agents-pill assigned">{assignedProjects} projects</span>
                        )}
                      </div>
                      <div className="agents-list-footer">
                        <span>Updated {formatRelativeTime(item.agent.updated_at)}</span>
                        {item.active_version?.role_alignment && (
                          <span className="agents-pill subtle">{item.active_version.role_alignment}</span>
                        )}
                      </div>
                    </button>
                  );
                })
              )}
            </div>
          </div>

          <div className="agents-detail-pane">
            {panelMode === 'create' ? (
              <div className="agents-detail-card animate-fade-in-up">
                <div className="agents-detail-header">
                  <div>
                    <h2 className="agents-section-title">Create agent</h2>
                    <p className="agents-section-subtitle">Design a new agent and decide how it is shared.</p>
                  </div>
                  <button
                    type="button"
                    className="agents-secondary-button pressable"
                    onClick={handleCancelCreate}
                    data-haptic="light"
                  >
                    Cancel
                  </button>
                </div>

                <div className="agents-form-grid">
                  <label className="agents-field">
                    <span className="agents-field-label">Agent name</span>
                    <input
                      className="agents-input"
                      value={createState.name}
                      onChange={(event) => handleCreateNameChange(event.target.value)}
                      placeholder="e.g. Build Engineer"
                    />
                  </label>

                  <label className="agents-field">
                    <span className="agents-field-label">Slug</span>
                    <input
                      className="agents-input"
                      value={createState.slug}
                      onChange={(event) => handleCreateSlugChange(event.target.value)}
                      placeholder="build-engineer"
                    />
                  </label>

                  <label className="agents-field">
                    <span className="agents-field-label">Workspace scope</span>
                    <select
                      className="agents-select"
                      value={createState.orgScopeId ?? ''}
                      onChange={(event) =>
                        handleCreateStateChange('orgScopeId', event.target.value || null)}
                    >
                      <option value="">Personal</option>
                      {organizations.map((org) => (
                        <option key={org.id} value={org.id}>
                          {org.name}
                        </option>
                      ))}
                    </select>
                  </label>

                  <label className="agents-field">
                    <span className="agents-field-label">Visibility</span>
                    <select
                      className="agents-select"
                      value={createState.visibility}
                      onChange={(event) =>
                        handleCreateStateChange('visibility', event.target.value as AgentVisibility)}
                    >
                      {Object.keys(VISIBILITY_LABELS).map((value) => (
                        <option key={value} value={value}>
                          {VISIBILITY_LABELS[value as AgentVisibility]}
                        </option>
                      ))}
                    </select>
                  </label>

                  <label className="agents-field full">
                    <span className="agents-field-label">Description</span>
                    <textarea
                      className="agents-textarea"
                      value={createState.description}
                      onChange={(event) => handleCreateStateChange('description', event.target.value)}
                      placeholder="Short, human-readable summary."
                      rows={3}
                    />
                  </label>

                  <label className="agents-field full">
                    <span className="agents-field-label">Mission</span>
                    <textarea
                      className="agents-textarea"
                      value={createState.mission}
                      onChange={(event) => handleCreateStateChange('mission', event.target.value)}
                      placeholder="Describe the agent's mission, boundaries, and tone."
                      rows={4}
                    />
                  </label>

                  <label className="agents-field">
                    <span className="agents-field-label">Role alignment</span>
                    <select
                      className="agents-select"
                      value={createState.roleAlignment}
                      onChange={(event) =>
                        handleCreateStateChange('roleAlignment', event.target.value as RoleAlignment)}
                    >
                      {ROLE_OPTIONS.map((role) => (
                        <option key={role} value={role}>
                          {role}
                        </option>
                      ))}
                    </select>
                  </label>

                  <label className="agents-field">
                    <span className="agents-field-label">Tags</span>
                    <input
                      className="agents-input"
                      value={createState.tags}
                      onChange={(event) => handleCreateStateChange('tags', event.target.value)}
                      placeholder="collab, infra, build"
                    />
                  </label>

                  <label className="agents-field">
                    <span className="agents-field-label">Capabilities</span>
                    <input
                      className="agents-input"
                      value={createState.capabilities}
                      onChange={(event) => handleCreateStateChange('capabilities', event.target.value)}
                      placeholder="api design, testing, refactoring"
                    />
                  </label>

                  <label className="agents-field">
                    <span className="agents-field-label">Default behaviors</span>
                    <input
                      className="agents-input"
                      value={createState.defaultBehaviors}
                      onChange={(event) => handleCreateStateChange('defaultBehaviors', event.target.value)}
                      placeholder="behavior_prefer_mcp_tools, behavior_use_raze_for_logging"
                    />
                  </label>

                  <label className="agents-field full">
                    <span className="agents-field-label">Playbook</span>
                    <textarea
                      className="agents-textarea"
                      value={createState.playbookContent}
                      onChange={(event) => handleCreateStateChange('playbookContent', event.target.value)}
                      placeholder="Paste the full playbook content (markdown supported)."
                      rows={6}
                    />
                  </label>
                </div>

                <div className="agents-form-footer">
                  <label className="agents-checkbox">
                    <input
                      type="checkbox"
                      checked={createState.requestApiCredentials}
                      onChange={(event) =>
                        handleCreateStateChange('requestApiCredentials', event.target.checked)}
                    />
                    <span>Request API credentials</span>
                  </label>

                  <label className="agents-checkbox">
                    <input
                      type="checkbox"
                      checked={createState.publishOnCreate}
                      onChange={(event) =>
                        handleCreateStateChange('publishOnCreate', event.target.checked)}
                    />
                    <span>Publish immediately</span>
                  </label>

                  <button
                    type="button"
                    className="agents-primary-button pressable"
                    onClick={handleCreateAgent}
                    disabled={createMutation.isPending || publishMutation.isPending}
                    data-haptic="light"
                  >
                    Create Agent
                  </button>
                </div>

                {credentials && (
                  <div className="agents-credentials">
                    <h3 className="agents-section-title">API Credentials</h3>
                    <p className="agents-section-subtitle">
                      Copy these credentials now. They will only be shown once.
                    </p>
                    <div className="agents-credentials-grid">
                      <div>
                        <span className="agents-field-label">Client ID</span>
                        <div className="agents-code">{credentials.client_id}</div>
                      </div>
                      <div>
                        <span className="agents-field-label">Client Secret</span>
                        <div className="agents-code">{credentials.client_secret}</div>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            ) : (
              <div className="agents-detail-card animate-fade-in-up">
                {!selectedAgent ? (
                  <div className="agents-empty">
                    <h3 className="agents-empty-title">Select an agent</h3>
                    <p className="agents-empty-description">
                      Choose an agent from the registry to see details, assignments, and controls.
                    </p>
                  </div>
                ) : !activeVersion ? (
                  <div className="agents-empty">
                    <h3 className="agents-empty-title">Loading agent profile</h3>
                    <p className="agents-empty-description">
                      Syncing versions and assignments for this agent.
                    </p>
                  </div>
                ) : (
                  <>
                    <div className="agents-detail-header">
                      <div>
                        <h2 className="agents-section-title">{selectedAgent.name}</h2>
                        <p className="agents-section-subtitle">{selectedAgent.slug}</p>
                      </div>
                      <div className="agents-detail-actions">
                        {!isBuiltin && (
                          <button
                            type="button"
                            className="agents-secondary-button pressable"
                            onClick={handleEditToggle}
                            data-haptic="light"
                          >
                            {isEditing ? 'Stop editing' : 'Edit'}
                          </button>
                        )}
                        {selectedAgent.status === 'DRAFT' && !isBuiltin && (
                          <button
                            type="button"
                            className="agents-primary-button pressable"
                            onClick={handlePublish}
                            disabled={publishMutation.isPending}
                            data-haptic="light"
                          >
                            Publish
                          </button>
                        )}
                      </div>
                    </div>

                    <div className="agents-detail-meta">
                      <span className={`agents-badge status-${(selectedAgent.status ?? 'DRAFT').toLowerCase()}`}>
                        {STATUS_LABELS[selectedAgent.status ?? 'DRAFT']}
                      </span>
                      <span className="agents-pill subtle">{VISIBILITY_LABELS[selectedAgent.visibility ?? 'PRIVATE']}</span>
                      {activeVersion?.role_alignment && (
                        <span className="agents-pill subtle">{activeVersion.role_alignment}</span>
                      )}
                      {isBuiltin && <span className="agents-pill builtin">Built-in</span>}
                      <span className="agents-pill subtle">v{selectedAgent.latest_version}</span>
                    </div>

                    {isBuiltin && (
                      <div className="agents-lockout">
                        Built-in agents are managed by the platform and cannot be edited directly.
                      </div>
                    )}

                    <div className="agents-form-grid">
                      <label className="agents-field">
                        <span className="agents-field-label">Name</span>
                        <input
                          className="agents-input"
                          value={editState.name}
                          onChange={(event) => handleEditStateChange('name', event.target.value)}
                          disabled={!isEditing || isBuiltin}
                        />
                      </label>
                      <label className="agents-field">
                        <span className="agents-field-label">Visibility</span>
                        <select
                          className="agents-select"
                          value={editState.visibility}
                          onChange={(event) =>
                            handleEditStateChange('visibility', event.target.value as AgentVisibility)}
                          disabled={!isEditing || isBuiltin}
                        >
                          {Object.keys(VISIBILITY_LABELS).map((value) => (
                            <option key={value} value={value}>
                              {VISIBILITY_LABELS[value as AgentVisibility]}
                            </option>
                          ))}
                        </select>
                      </label>
                      <label className="agents-field full">
                        <span className="agents-field-label">Description</span>
                        <textarea
                          className="agents-textarea"
                          value={editState.description}
                          onChange={(event) => handleEditStateChange('description', event.target.value)}
                          disabled={!isEditing || isBuiltin}
                          rows={3}
                        />
                      </label>
                      <label className="agents-field full">
                        <span className="agents-field-label">Mission</span>
                        <textarea
                          className="agents-textarea"
                          value={editState.mission}
                          onChange={(event) => handleEditStateChange('mission', event.target.value)}
                          disabled={!isEditing || isBuiltin}
                          rows={4}
                        />
                      </label>
                      <label className="agents-field">
                        <span className="agents-field-label">Role alignment</span>
                        <select
                          className="agents-select"
                          value={editState.roleAlignment}
                          onChange={(event) =>
                            handleEditStateChange('roleAlignment', event.target.value as RoleAlignment)}
                          disabled={!isEditing || isBuiltin}
                        >
                          {ROLE_OPTIONS.map((role) => (
                            <option key={role} value={role}>
                              {role}
                            </option>
                          ))}
                        </select>
                      </label>
                      <label className="agents-field">
                        <span className="agents-field-label">Tags</span>
                        <input
                          className="agents-input"
                          value={editState.tags}
                          onChange={(event) => handleEditStateChange('tags', event.target.value)}
                          disabled={!isEditing || isBuiltin}
                          placeholder="collab, infra"
                        />
                      </label>
                      <label className="agents-field">
                        <span className="agents-field-label">Capabilities</span>
                        <input
                          className="agents-input"
                          value={editState.capabilities}
                          onChange={(event) => handleEditStateChange('capabilities', event.target.value)}
                          disabled={!isEditing || isBuiltin}
                          placeholder="api design, testing"
                        />
                      </label>
                      <label className="agents-field">
                        <span className="agents-field-label">Default behaviors</span>
                        <input
                          className="agents-input"
                          value={editState.defaultBehaviors}
                          onChange={(event) => handleEditStateChange('defaultBehaviors', event.target.value)}
                          disabled={!isEditing || isBuiltin}
                          placeholder="behavior_prefer_mcp_tools"
                        />
                      </label>
                      <label className="agents-field full">
                        <span className="agents-field-label">Playbook</span>
                        <textarea
                          className="agents-textarea"
                          value={editState.playbookContent}
                          onChange={(event) => handleEditStateChange('playbookContent', event.target.value)}
                          disabled={!isEditing || isBuiltin}
                          rows={6}
                        />
                      </label>
                    </div>

                    {isEditing && !isBuiltin && (
                      <div className="agents-form-footer">
                        <div className="agents-form-hint">
                          {nameError ? nameError : 'Saving creates a new draft version when content changes.'}
                        </div>
                        <button
                          type="button"
                          className="agents-primary-button pressable"
                          onClick={handleUpdateAgent}
                          disabled={updateMutation.isPending || versionMutation.isPending || Boolean(nameError)}
                          data-haptic="light"
                        >
                          Save changes
                        </button>
                      </div>
                    )}

                    <div className="agents-assignments">
                      <div className="agents-assignments-header">
                        <div>
                          <h3 className="agents-section-title">Assignment studio</h3>
                          <p className="agents-section-subtitle">
                            Manage org + project access. Org assignments inherit to every project, with per-project pins.
                          </p>
                        </div>
                        <div className="agents-assignment-summary">
                          <span className="agents-assignment-chip">Visibility: {visibilityLabel}</span>
                          <span className="agents-assignment-chip">
                            Workspace access: {orgAssignment ? 'Assigned' : 'Not assigned'}
                          </span>
                          <span className="agents-assignment-chip">Projects: {assignmentSummary}</span>
                          {pinSummary && (
                            <span className="agents-assignment-chip">Pins: {pinSummary}</span>
                          )}
                        </div>
                      </div>

                      {visibilityHint && (
                        <div className="agents-assignment-note">{visibilityHint}</div>
                      )}

                      {assignmentLocked && (
                        <div className="agents-lockout">
                          Assignment controls are locked for private agents you do not own.
                        </div>
                      )}

                      <div className="agents-assignments-grid">
                        <div className="agents-assignment-card">
                          <div className="agents-assignment-card-header">
                            <div>
                              <h4 className="agents-assignment-title">Workspace access</h4>
                              <p className="agents-assignment-subtitle">
                                {assignmentOrgId
                                  ? 'Assigning to an org makes the agent available to every project. Pin or unpin per project below.'
                                  : 'Personal workspaces skip org-wide access. Assign directly to projects.'}
                              </p>
                            </div>
                            <span className="agents-pill subtle">Optional</span>
                          </div>

                          <label className="agents-field">
                            <span className="agents-field-label">Workspace</span>
                            <select
                              className="agents-select"
                              value={assignmentOrgId ?? ''}
                              onChange={(event) =>
                                handleAssignmentOrgChange(event.target.value || null)}
                            >
                              <option value="">Personal workspace</option>
                              {organizations.map((org) => (
                                <option key={org.id} value={org.id}>
                                  {org.name}
                                </option>
                              ))}
                            </select>
                          </label>

                          {!hasOrganizations && (
                            <div className="agents-assignment-empty">
                              <p className="agents-empty-description">
                                You do not have an org yet. Create one to share agents across projects.
                              </p>
                            </div>
                          )}

                          <div className="agents-assignment-row">
                            <div>
                              <span className="agents-assignment-label">Workspace access</span>
                              <span className="agents-assignment-meta">
                                {orgAssignment ? `Enabled for ${assignmentScopeLabel}` : 'Not assigned'}
                              </span>
                            </div>
                            {orgAssignment ? (
                              <button
                                type="button"
                                className="agents-secondary-button pressable"
                                onClick={handleUnassignOrg}
                                disabled={unassignMutation.isPending || !assignmentOrgId || assignmentLocked}
                                data-haptic="light"
                              >
                                Remove from org
                              </button>
                            ) : (
                              <button
                                type="button"
                                className="agents-primary-button pressable"
                                onClick={handleAssignOrg}
                                disabled={assignMutation.isPending || !assignmentOrgId || assignmentLocked}
                                data-haptic="light"
                              >
                                Assign to org
                              </button>
                            )}
                          </div>

                          <div className="agents-assignment-hint">
                            {assignmentOrgId
                              ? 'Workspace access makes this agent available across every project in the org.'
                              : 'Personal workspaces skip org-wide access. Assign directly to projects below.'}
                          </div>
                        </div>

                        <div className="agents-assignment-card">
                          <div className="agents-assignment-card-header">
                            <div>
                              <h4 className="agents-assignment-title">Project routing</h4>
                              <p className="agents-assignment-subtitle">
                                {orgAssignment
                                  ? 'Projects inherit access by default. Pin to emphasize specific workspaces; agents can span many projects.'
                                  : 'Assign the agent directly to projects for focused use. Agents can span many projects.'}
                              </p>
                            </div>
                            <div className="agents-assignment-actions">
                              <button
                                type="button"
                                className="agents-secondary-button pressable"
                                onClick={handleAssignAllProjects}
                                disabled={bulkActionsDisabled || projectTotalCount === 0}
                                data-haptic="light"
                              >
                                {orgAssignment ? 'Pin all' : 'Assign all'}
                              </button>
                              <button
                                type="button"
                                className="agents-secondary-button pressable"
                                onClick={handleClearAllProjects}
                                disabled={bulkActionsDisabled || projectAssignments.size === 0}
                                data-haptic="light"
                              >
                                {orgAssignment ? 'Clear pins' : 'Clear all'}
                              </button>
                            </div>
                          </div>

                          <div className="agents-project-toolbar">
                            <label className="agents-field agents-project-search">
                              <span className="agents-field-label">Find project</span>
                              <input
                                className="agents-input"
                                value={projectQuery}
                                onChange={(event) => setProjectQuery(event.target.value)}
                                placeholder="Search by name or slug"
                              />
                            </label>
                            <div className="agents-filter-group">
                              <span className="agents-filter-label">Filter</span>
                              <div className="agents-filter-pills">
                                {projectFilterOptions.map((filter) => (
                                  <button
                                    type="button"
                                    key={filter.value}
                                    className={`agents-filter-pill ${projectFilter === filter.value ? 'active' : ''}`}
                                    onClick={() => setProjectFilter(filter.value)}
                                  >
                                    {filter.label}
                                  </button>
                                ))}
                              </div>
                            </div>
                          </div>

                          <div className="agents-project-stats">
                            <span>{projectResultsLabel}</span>
                            <span>{assignmentScopeLabel}</span>
                          </div>

                          <div className="agents-project-assignments">
                            {projectTotalCount === 0 ? (
                              <div className="agents-empty compact">
                                <p className="agents-empty-description">
                                  {assignmentOrgId
                                    ? 'This organization has no projects yet.'
                                    : 'You do not have personal projects yet.'}
                                </p>
                              </div>
                            ) : filteredProjects.length === 0 ? (
                              <div className="agents-empty compact">
                                <p className="agents-empty-description">
                                  No projects match this filter.
                                </p>
                              </div>
                            ) : (
                              filteredProjects.map((project) => {
                                const assignedId = projectAssignments.get(project.id);
                                const pinned = Boolean(assignedId);
                                const inherited = Boolean(orgAssignment) && !pinned;
                                const statusLabel = orgAssignment
                                  ? pinned
                                    ? 'Pinned'
                                    : 'Inherited'
                                  : pinned
                                    ? 'Assigned'
                                    : 'Not assigned';
                                const statusClass = orgAssignment
                                  ? pinned
                                    ? 'status-pinned'
                                    : 'status-inherited'
                                  : pinned
                                    ? 'status-assigned'
                                    : 'status-unassigned';
                                const actionLabel = orgAssignment
                                  ? pinned
                                    ? 'Unpin'
                                    : 'Pin'
                                  : pinned
                                    ? 'Unassign'
                                    : 'Assign';
                                return (
                                  <div key={project.id} className="agents-project-row">
                                    <div>
                                      <span className="agents-project-name">{project.name}</span>
                                      <span className="agents-project-meta">{project.slug}</span>
                                    </div>
                                    <div className="agents-project-actions">
                                      <span className={`agents-project-status ${statusClass}`}>{statusLabel}</span>
                                      <button
                                        type="button"
                                        className={`agents-project-toggle pressable ${pinned ? 'active' : ''}`}
                                        onClick={() => handleToggleProjectAssignment(project.id)}
                                        disabled={mutationPending || bulkActionPending || assignmentLocked}
                                        data-haptic="light"
                                      >
                                        {actionLabel}
                                      </button>
                                    </div>
                                  </div>
                                );
                              })
                            )}
                          </div>
                        </div>
                      </div>
                    </div>
                  </>
                )}
              </div>
            )}
          </div>
        </section>

        {actionError && (
          <div className="agents-error" role="status" aria-live="polite">
            {actionError}
          </div>
        )}
      </div>
    </WorkspaceShell>
  );
}
