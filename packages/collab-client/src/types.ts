/**
 * GuideAI Collaboration Protocol Types
 *
 * Shared between SaaS (web-console) and VS Code extension for cross-surface parity.
 * Mirrors backend contracts in guideai/collaboration_contracts.py.
 */

// ---------------------------------------------------------------------------
// Core Identifiers
// ---------------------------------------------------------------------------

export type WorkspaceId = string;
export type DocumentId = string;
export type UserId = string;
export type SessionId = string;
export type OperationId = string;

// ---------------------------------------------------------------------------
// Enums (mirror Python enums)
// ---------------------------------------------------------------------------

export enum EditOperationType {
  Insert = 'insert',
  Delete = 'delete',
  Replace = 'replace',
  Move = 'move',
  Format = 'format',
}

export enum CollaborationRole {
  Owner = 'owner',
  Admin = 'admin',
  Editor = 'editor',
  Commenter = 'commenter',
  Viewer = 'viewer',
}

export enum DocumentType {
  Markdown = 'markdown',
  Plan = 'plan',
  Workflow = 'workflow',
  Agent = 'agent',
  Json = 'json',
}

// ---------------------------------------------------------------------------
// Document Structures
// ---------------------------------------------------------------------------

export interface Workspace {
  id: WorkspaceId;
  name: string;
  description: string;
  owner_id: UserId;
  created_at: string; // ISO 8601
  updated_at: string;
  is_shared: boolean;
  settings?: Record<string, unknown>;
  tags?: string[];
}

export interface Document {
  id: DocumentId;
  workspace_id: WorkspaceId;
  title: string;
  content: string;
  document_type: DocumentType | string;
  created_by: UserId;
  created_at: string;
  updated_at: string;
  version: number;
  metadata?: Record<string, unknown>;
}

export interface EditOperation {
  id: OperationId;
  document_id: DocumentId;
  user_id: UserId;
  operation_type: EditOperationType;
  position: number;
  content: string;
  length?: number;
  version: number;
  timestamp: string;
  session_id?: SessionId;
  metadata?: Record<string, unknown>;
}

// ---------------------------------------------------------------------------
// WebSocket Protocol Messages
// ---------------------------------------------------------------------------

/**
 * Client → Server messages
 */
export type ClientMessage =
  | { type: 'ping' }
  | { type: 'edit'; operation: ClientEditOperation }
  | { type: 'cursor'; position: number; selection_end?: number }
  | { type: 'presence'; status: 'active' | 'idle' | 'away' };

export interface ClientEditOperation {
  operation_type: EditOperationType;
  position: number;
  content: string;
  length?: number;
  version: number; // Base version client is editing from
  user_id?: UserId;
  session_id?: SessionId;
}

/**
 * Server → Client messages
 */
export type ServerMessage =
  | { type: 'pong' }
  | { type: 'snapshot'; document: Document }
  | { type: 'operation'; operation: EditOperation; document: Document | null }
  | { type: 'cursor'; user_id: UserId; position: number; selection_end?: number }
  | { type: 'presence'; user_id: UserId; status: 'active' | 'idle' | 'away' | 'disconnected' }
  | { type: 'error'; code: ErrorCode; message: string; expected_version?: number; got_version?: number; document?: Document | null };

export type ErrorCode =
  | 'BAD_REQUEST'
  | 'NOT_FOUND'
  | 'VERSION_CONFLICT'
  | 'APPLY_FAILED'
  | 'UNAUTHORIZED';

// ---------------------------------------------------------------------------
// REST API Request/Response Types
// ---------------------------------------------------------------------------

export interface CreateWorkspaceRequest {
  name: string;
  description?: string;
  owner_id: string;
  settings?: Record<string, unknown>;
  tags?: string[];
  is_shared?: boolean;
}

export interface CreateDocumentRequest {
  workspace_id: WorkspaceId;
  title: string;
  content?: string;
  document_type?: DocumentType | string;
  created_by: UserId;
  metadata?: Record<string, unknown>;
}

// ---------------------------------------------------------------------------
// Presence & Cursors
// ---------------------------------------------------------------------------

export interface UserPresence {
  user_id: UserId;
  session_id?: SessionId;
  display_name?: string;
  color?: string; // Assigned cursor color
  status: 'active' | 'idle' | 'away' | 'disconnected';
  cursor_position?: number;
  selection_end?: number;
  last_active: string;
}

// ---------------------------------------------------------------------------
// Project Settings
// ---------------------------------------------------------------------------

export interface WorkflowSettings {
  require_approval_for_deploy: boolean;
  auto_merge_enabled: boolean;
  branch_protection_enabled: boolean;
  ci_required: boolean;
  code_owners_required: boolean;
  min_reviewers: number;
  allowed_merge_methods: string[];
}

export interface AgentSettings {
  max_concurrent_runs: number;
  default_timeout_seconds: number;
  auto_retry_enabled: boolean;
  max_retries: number;
  require_human_approval: boolean;
  allowed_actions: string[];
  blocked_actions: string[];
}

export interface BrandingSettings {
  logo_url?: string;
  favicon_url?: string;
  primary_color?: string;
  accent_color?: string;
  font_family?: string;
}

export interface GitHubBranchInfo {
  name: string;
  sha: string;
  protected: boolean;
}

export interface ProjectSettings {
  project_id: string;
  inherit_org_settings: boolean;
  branding?: BrandingSettings;
  workflow: WorkflowSettings;
  agents: AgentSettings;
  repository_url?: string;
  default_branch: string;
  protected_branches: string[];
  local_project_path?: string;
  environments: string[];
  active_environment: string;
  features: Record<string, boolean>;
  custom: Record<string, unknown>;
}

export interface UpdateProjectSettingsRequest {
  inherit_org_settings?: boolean;
  branding?: Partial<BrandingSettings>;
  workflow?: Partial<WorkflowSettings>;
  repository_url?: string;
  default_branch?: string;
  protected_branches?: string[];
  local_project_path?: string;
  environments?: string[];
  active_environment?: string;
  features?: Record<string, boolean>;
  custom?: Record<string, unknown>;
}

export interface GitHubRepoValidationRequest {
  repository_url: string;
  access_token?: string;
}

export interface GitHubRepoValidationResponse {
  valid: boolean;
  owner?: string;
  repo?: string;
  default_branch?: string;
  branches: GitHubBranchInfo[];
  visibility?: 'public' | 'private';
  description?: string;
  error?: string;
}

export interface GitHubBranchListResponse {
  branches: GitHubBranchInfo[];
  total_count?: number;
  page: number;
  per_page: number;
}

// ---------------------------------------------------------------------------
// Client Events (for UI binding)
// ---------------------------------------------------------------------------

export interface CollabClientEvents {
  /** Connection established, initial snapshot received */
  connected: (document: Document) => void;
  /** Connection lost */
  disconnected: (reason: string) => void;
  /** Remote operation applied */
  operation: (operation: EditOperation, document: Document | null) => void;
  /** Version conflict - client should rebase */
  conflict: (expected: number, got: number, serverDocument: Document | null) => void;
  /** Remote cursor update */
  cursor: (userId: UserId, position: number, selectionEnd?: number) => void;
  /** Presence change */
  presence: (userId: UserId, status: UserPresence['status']) => void;
  /** Generic error */
  error: (code: ErrorCode, message: string) => void;
}
