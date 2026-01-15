/**
 * Boards + Work Items API (web console)
 *
 * Following:
 * - COLLAB_SAAS_REQUIREMENTS.md: optimistic updates, fast UI
 * - behavior_use_raze_for_logging (Student)
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiClient, ApiError } from './client';
import { razeLog } from '../telemetry/raze';

// ---------------------------------------------------------------------------
// Types (mirrors guideai.multi_tenant.board_contracts)
// ---------------------------------------------------------------------------

export type WorkItemType = 'epic' | 'story' | 'task';
export type WorkItemStatus =
  | 'draft'
  | 'backlog'
  | 'todo'
  | 'in_progress'
  | 'in_review'
  | 'done'
  | 'cancelled';

export type WorkItemPriority = 'critical' | 'high' | 'medium' | 'low';

export interface Board {
  board_id: string;
  project_id: string;
  name: string;
  description?: string | null;
  is_default: boolean;
  created_at: string;
  updated_at: string;
  created_by: string;
  org_id?: string | null;
}

export interface BoardColumn {
  column_id: string;
  board_id: string;
  name: string;
  position: number;
  status_mapping: WorkItemStatus;
  wip_limit?: number | null;
  created_at: string;
  updated_at: string;
  created_by: string;
  org_id?: string | null;
}

export interface BoardWithColumns extends Board {
  columns: BoardColumn[];
}

export interface WorkItem {
  item_id: string;
  item_type: WorkItemType;
  project_id: string;
  board_id?: string | null;
  column_id?: string | null;
  parent_id?: string | null;
  title: string;
  description?: string | null;
  status: WorkItemStatus;
  priority: WorkItemPriority;
  position: number;
  labels: string[];
  story_points?: number | null;
  estimated_hours?: string | number | null;
  actual_hours?: string | number | null;
  assignee_id?: string | null;
  assignee_type?: 'user' | 'agent' | null;
  start_date?: string | null;
  target_date?: string | null;
  due_date?: string | null;
  completed_at?: string | null;
  behavior_id?: string | null;
  run_id?: string | null;
  metadata?: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
  created_by: string;
  org_id?: string | null;
}

export type WorkItemCommentAuthorType = 'user' | 'agent';

export interface WorkItemComment {
  comment_id: string;
  work_item_id: string;
  author_id: string;
  author_type: WorkItemCommentAuthorType;
  content: string;
  run_id?: string | null;
  metadata?: Record<string, unknown> | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface CreateWorkItemCommentRequest {
  body: string;
  author_type?: WorkItemCommentAuthorType;
  run_id?: string | null;
  metadata?: Record<string, unknown>;
}

export interface CreateBoardRequest {
  project_id: string;
  name: string;
  description?: string;
  is_default?: boolean;
  create_default_columns?: boolean;
}

export interface CreateWorkItemRequest {
  item_type: WorkItemType;
  project_id: string;
  board_id: string;
  column_id?: string;
  title: string;
  description?: string;
  priority?: WorkItemPriority;
}

export interface UpdateWorkItemRequest {
  title?: string;
  description?: string | null;
  status?: WorkItemStatus;
  priority?: WorkItemPriority;
  labels?: string[];
  parent_id?: string | null;
  story_points?: number | null;
  estimated_hours?: string | number | null;
  actual_hours?: string | number | null;
  start_date?: string | null;
  target_date?: string | null;
  due_date?: string | null;
  behavior_id?: string | null;
  run_id?: string | null;
  metadata?: Record<string, unknown> | null;
}

export interface MoveWorkItemRequest {
  column_id: string | null;
  position: number;
  expected_from_column_updated_at?: string | null;
  expected_to_column_updated_at?: string | null;
}

export interface AssignWorkItemRequest {
  assignee_id: string;
  assignee_type: 'user' | 'agent';
  reason?: string;
}

interface AssignmentResponse {
  item: WorkItem;
  message?: string;
}

// ---------------------------------------------------------------------------
// Query Keys
// ---------------------------------------------------------------------------

export const boardKeys = {
  all: ['boards'] as const,
  list: (projectId?: string) => [...boardKeys.all, 'list', projectId] as const,
  board: (boardId?: string) => [...boardKeys.all, 'board', boardId] as const,
  items: (boardId?: string) => [...boardKeys.all, 'items', boardId] as const,
  item: (itemId?: string) => [...boardKeys.all, 'item', itemId] as const,
  comments: (itemId?: string) => [...boardKeys.all, 'comments', itemId] as const,
};

// ---------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------

export function useBoards(projectId?: string) {
  return useQuery({
    queryKey: boardKeys.list(projectId),
    queryFn: async (): Promise<Board[]> => {
      if (!projectId) return [];
      try {
        const response = await apiClient.get<{ boards: Board[] }>(
          `/v1/boards?project_id=${encodeURIComponent(projectId)}`
        );
        return response.boards ?? [];
      } catch (error) {
        if (error instanceof ApiError && error.status === 404) return [];
        throw error;
      }
    },
    enabled: Boolean(projectId),
    staleTime: 15_000,
  });
}

export function useCreateBoard() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (payload: CreateBoardRequest): Promise<Board> => {
      await razeLog('INFO', 'Board create requested', {
        project_id: payload.project_id,
        name: payload.name,
      });

      const response = await apiClient.post<{ board: Board }>('/v1/boards', payload);
      await razeLog('INFO', 'Board created', {
        project_id: payload.project_id,
        board_id: response.board.board_id,
      });
      return response.board;
    },
    onMutate: async (payload) => {
      await queryClient.cancelQueries({ queryKey: boardKeys.list(payload.project_id) });

      const previous = queryClient.getQueryData<Board[]>(boardKeys.list(payload.project_id)) ?? [];
      const optimisticId = `temp-board-${Date.now()}`;

      const now = new Date().toISOString();
      const optimistic: Board = {
        board_id: optimisticId,
        project_id: payload.project_id,
        name: payload.name,
        description: payload.description ?? null,
        is_default: Boolean(payload.is_default),
        created_at: now,
        updated_at: now,
        created_by: 'me',
        org_id: null,
      };

      queryClient.setQueryData<Board[]>(boardKeys.list(payload.project_id), [optimistic, ...previous]);
      return { previous, optimisticId };
    },
    onError: async (error, payload, context) => {
      queryClient.setQueryData(boardKeys.list(payload.project_id), context?.previous ?? []);
      await razeLog('ERROR', 'Board create failed', {
        project_id: payload.project_id,
        error: error instanceof Error ? error.message : String(error),
      });
    },
    onSuccess: async (created, payload, context) => {
      queryClient.setQueryData<Board[]>(boardKeys.list(payload.project_id), (current) => {
        const list = current ?? [];
        const replaced = list.map((b) => (b.board_id === context?.optimisticId ? created : b));
        return replaced.some((b) => b.board_id === created.board_id) ? replaced : [created, ...replaced];
      });
    },
  });
}

export function useBoard(boardId?: string) {
  return useQuery({
    queryKey: boardKeys.board(boardId),
    queryFn: async (): Promise<BoardWithColumns | null> => {
      if (!boardId) return null;
      const response = await apiClient.get<{ board: BoardWithColumns }>(`/v1/boards/${boardId}`);
      return response.board ?? null;
    },
    enabled: Boolean(boardId),
    staleTime: 5_000,
  });
}

export function useWorkItems(boardId?: string) {
  return useQuery({
    queryKey: boardKeys.items(boardId),
    queryFn: async (): Promise<WorkItem[]> => {
      if (!boardId) return [];
      const response = await apiClient.get<{ items: WorkItem[] }>(
        `/v1/work-items?board_id=${encodeURIComponent(boardId)}&limit=100`
      );
      return response.items ?? [];
    },
    enabled: Boolean(boardId),
    staleTime: 3_000,
  });
}

export function useWorkItem(itemId?: string, initialData?: WorkItem) {
  return useQuery({
    queryKey: boardKeys.item(itemId),
    queryFn: async (): Promise<WorkItem | null> => {
      if (!itemId) return null;
      const response = await apiClient.get<{ item: WorkItem }>(`/v1/work-items/${itemId}`);
      return response.item ?? null;
    },
    enabled: Boolean(itemId),
    staleTime: 2_000,
    initialData: itemId && initialData ? initialData : undefined,
  });
}

export function useWorkItemComments(
  itemId?: string,
  options?: { limit?: number; offset?: number; enabled?: boolean }
) {
  const limit = options?.limit ?? 200;
  const offset = options?.offset ?? 0;

  return useQuery({
    queryKey: boardKeys.comments(itemId),
    queryFn: async (): Promise<WorkItemComment[]> => {
      if (!itemId) return [];
      const params = new URLSearchParams();
      params.set('limit', String(limit));
      params.set('offset', String(offset));
      const suffix = params.toString();
      const response = await apiClient.get<{ comments: WorkItemComment[] }>(
        `/v1/work-items/${itemId}/comments${suffix ? `?${suffix}` : ''}`
      );
      return response.comments ?? [];
    },
    enabled: Boolean(itemId) && (options?.enabled ?? true),
    staleTime: 2_000,
  });
}

export function useCreateWorkItem() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (payload: CreateWorkItemRequest): Promise<WorkItem> => {
      await razeLog('INFO', 'Work item create requested', {
        project_id: payload.project_id,
        board_id: payload.board_id,
        column_id: payload.column_id ?? null,
        item_type: payload.item_type,
      });

      const response = await apiClient.post<{ item: WorkItem }>('/v1/work-items', {
        ...payload,
        priority: payload.priority ?? 'medium',
        metadata: {},
        labels: [],
        acceptance_criteria: [],
        checklist: [],
      });
      return response.item;
    },
    onMutate: async (payload) => {
      await queryClient.cancelQueries({ queryKey: boardKeys.items(payload.board_id) });

      const previous = queryClient.getQueryData<WorkItem[]>(boardKeys.items(payload.board_id)) ?? [];
      const optimisticId = `temp-item-${Date.now()}`;
      const now = new Date().toISOString();
      const optimistic: WorkItem = {
        item_id: optimisticId,
        item_type: payload.item_type,
        project_id: payload.project_id,
        board_id: payload.board_id,
        column_id: payload.column_id ?? null,
        parent_id: null,
        title: payload.title,
        description: payload.description ?? null,
        status: payload.item_type === 'epic' ? 'draft' : payload.item_type === 'task' ? 'todo' : 'backlog',
        priority: payload.priority ?? 'medium',
        position: 0,
        labels: [],
        created_at: now,
        updated_at: now,
        created_by: 'me',
        org_id: null,
      };

      queryClient.setQueryData<WorkItem[]>(boardKeys.items(payload.board_id), [optimistic, ...previous]);
      return { previous, optimisticId };
    },
    onError: async (error, payload, context) => {
      queryClient.setQueryData(boardKeys.items(payload.board_id), context?.previous ?? []);
      await razeLog('ERROR', 'Work item create failed', {
        project_id: payload.project_id,
        board_id: payload.board_id,
        error: error instanceof Error ? error.message : String(error),
      });
    },
    onSuccess: async (created, payload, context) => {
      queryClient.setQueryData<WorkItem[]>(boardKeys.items(payload.board_id), (current) => {
        const list = current ?? [];
        const replaced = list.map((i) => (i.item_id === context?.optimisticId ? created : i));
        return replaced.some((i) => i.item_id === created.item_id) ? replaced : [created, ...replaced];
      });
    },
  });
}

export function useMoveWorkItem(boardId?: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (input: { itemId: string; move: MoveWorkItemRequest }): Promise<WorkItem> => {
      if (!boardId) throw new Error('boardId is required');
      const response = await apiClient.post<{ item: WorkItem }>(`/v1/work-items/${input.itemId}:move`, input.move);
      return response.item;
    },
    onMutate: async (input) => {
      if (!boardId) return {};
      await queryClient.cancelQueries({ queryKey: boardKeys.items(boardId) });
      await queryClient.cancelQueries({ queryKey: boardKeys.item(input.itemId) });

      const previous = queryClient.getQueryData<WorkItem[]>(boardKeys.items(boardId)) ?? [];
      const previousItem = queryClient.getQueryData<WorkItem | null>(boardKeys.item(input.itemId)) ?? null;

      // Optimistically update the items list
      queryClient.setQueryData<WorkItem[]>(boardKeys.items(boardId), (current) => {
        const list = current ?? [];
        return list.map((item) =>
          item.item_id === input.itemId
            ? { ...item, column_id: input.move.column_id, position: input.move.position }
            : item
        );
      });

      // Optimistically update the individual item query (for the drawer)
      if (previousItem) {
        queryClient.setQueryData<WorkItem>(boardKeys.item(input.itemId), {
          ...previousItem,
          column_id: input.move.column_id,
          position: input.move.position,
        });
      }

      return { previous, previousItem };
    },
    onError: async (error, input, context) => {
      if (!boardId) return;
      const ctx = context as { previous?: WorkItem[]; previousItem?: WorkItem | null } | undefined;
      queryClient.setQueryData(boardKeys.items(boardId), ctx?.previous ?? []);
      if (ctx?.previousItem !== undefined) {
        queryClient.setQueryData(boardKeys.item(input.itemId), ctx.previousItem);
      }
      await razeLog('ERROR', 'Work item move failed', {
        board_id: boardId,
        error: error instanceof Error ? error.message : String(error),
      });
    },
    onSuccess: async (updated) => {
      if (!boardId) return;
      // Update the items list with server response
      queryClient.setQueryData<WorkItem[]>(boardKeys.items(boardId), (current) => {
        const list = current ?? [];
        return list.map((item) => (item.item_id === updated.item_id ? updated : item));
      });
      // Update the individual item query (for the drawer)
      queryClient.setQueryData<WorkItem>(boardKeys.item(updated.item_id), updated);
    },
  });
}

export function useUpdateWorkItem(boardId?: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (input: { itemId: string; patch: UpdateWorkItemRequest }): Promise<WorkItem> => {
      await razeLog('INFO', 'Work item update requested', {
        board_id: boardId ?? null,
        item_id: input.itemId,
        fields: Object.keys(input.patch),
      });
      const response = await apiClient.patch<{ item: WorkItem }>(`/v1/work-items/${input.itemId}`, input.patch);
      return response.item;
    },
    onMutate: async (input) => {
      await queryClient.cancelQueries({ queryKey: boardKeys.item(input.itemId) });
      if (boardId) {
        await queryClient.cancelQueries({ queryKey: boardKeys.items(boardId) });
      }

      const previousItem = queryClient.getQueryData<WorkItem | null>(boardKeys.item(input.itemId)) ?? null;
      const previousItems = boardId ? (queryClient.getQueryData<WorkItem[]>(boardKeys.items(boardId)) ?? []) : null;

      const applyPatch = (item: WorkItem): WorkItem => ({ ...item, ...input.patch });

      if (previousItem) {
        queryClient.setQueryData<WorkItem | null>(boardKeys.item(input.itemId), applyPatch(previousItem));
      }

      if (boardId && previousItems) {
        queryClient.setQueryData<WorkItem[]>(boardKeys.items(boardId), (current) => {
          const list = current ?? [];
          return list.map((item) => (item.item_id === input.itemId ? applyPatch(item) : item));
        });
      }

      return { previousItem, previousItems };
    },
    onError: async (error, input, context) => {
      queryClient.setQueryData(boardKeys.item(input.itemId), (context as { previousItem?: WorkItem | null } | undefined)?.previousItem ?? null);
      if (boardId) {
        queryClient.setQueryData(boardKeys.items(boardId), (context as { previousItems?: WorkItem[] } | undefined)?.previousItems ?? []);
      }
      await razeLog('ERROR', 'Work item update failed', {
        board_id: boardId ?? null,
        item_id: input.itemId,
        error: error instanceof Error ? error.message : String(error),
      });
    },
    onSuccess: async (updated) => {
      queryClient.setQueryData<WorkItem | null>(boardKeys.item(updated.item_id), updated);
      if (boardId) {
        queryClient.setQueryData<WorkItem[]>(boardKeys.items(boardId), (current) => {
          const list = current ?? [];
          return list.map((item) => (item.item_id === updated.item_id ? updated : item));
        });
      }
      await razeLog('INFO', 'Work item updated', {
        board_id: boardId ?? null,
        item_id: updated.item_id,
      });
    },
  });
}

export function useAssignWorkItem(boardId?: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (input: { itemId: string; assigneeId: string; assigneeType: 'user' | 'agent'; reason?: string }): Promise<WorkItem> => {
      await razeLog('INFO', 'Work item assign requested', {
        board_id: boardId ?? null,
        item_id: input.itemId,
        assignee_id: input.assigneeId,
        assignee_type: input.assigneeType,
      });
      const payload: AssignWorkItemRequest = {
        assignee_id: input.assigneeId,
        assignee_type: input.assigneeType,
      };
      if (input.reason) payload.reason = input.reason;
      const response = await apiClient.post<AssignmentResponse>(`/v1/work-items/${input.itemId}:assign`, payload);
      return response.item;
    },
    onMutate: async (input) => {
      await queryClient.cancelQueries({ queryKey: boardKeys.item(input.itemId) });
      if (boardId) {
        await queryClient.cancelQueries({ queryKey: boardKeys.items(boardId) });
      }

      const previousItem = queryClient.getQueryData<WorkItem | null>(boardKeys.item(input.itemId)) ?? null;
      const previousItems = boardId ? (queryClient.getQueryData<WorkItem[]>(boardKeys.items(boardId)) ?? []) : null;

      const applyPatch = (item: WorkItem): WorkItem => ({
        ...item,
        assignee_id: input.assigneeId,
        assignee_type: input.assigneeType,
      });

      if (previousItem) {
        queryClient.setQueryData<WorkItem | null>(boardKeys.item(input.itemId), applyPatch(previousItem));
      }

      if (boardId && previousItems) {
        queryClient.setQueryData<WorkItem[]>(boardKeys.items(boardId), (current) => {
          const list = current ?? [];
          return list.map((item) => (item.item_id === input.itemId ? applyPatch(item) : item));
        });
      }

      return { previousItem, previousItems };
    },
    onError: async (error, input, context) => {
      queryClient.setQueryData(boardKeys.item(input.itemId), (context as { previousItem?: WorkItem | null } | undefined)?.previousItem ?? null);
      if (boardId) {
        queryClient.setQueryData(boardKeys.items(boardId), (context as { previousItems?: WorkItem[] } | undefined)?.previousItems ?? []);
      }
      await razeLog('ERROR', 'Work item assign failed', {
        board_id: boardId ?? null,
        item_id: input.itemId,
        error: error instanceof Error ? error.message : String(error),
      });
    },
    onSuccess: async (updated) => {
      queryClient.setQueryData<WorkItem | null>(boardKeys.item(updated.item_id), updated);
      if (boardId) {
        queryClient.setQueryData<WorkItem[]>(boardKeys.items(boardId), (current) => {
          const list = current ?? [];
          return list.map((item) => (item.item_id === updated.item_id ? updated : item));
        });
      }
      await razeLog('INFO', 'Work item assigned', {
        board_id: boardId ?? null,
        item_id: updated.item_id,
        assignee_id: updated.assignee_id ?? null,
        assignee_type: updated.assignee_type ?? null,
      });
    },
  });
}

export function useUnassignWorkItem(boardId?: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (input: { itemId: string; reason?: string }): Promise<WorkItem> => {
      await razeLog('INFO', 'Work item unassign requested', {
        board_id: boardId ?? null,
        item_id: input.itemId,
      });
      const reasonParam = input.reason ? `?reason=${encodeURIComponent(input.reason)}` : '';
      const response = await apiClient.post<AssignmentResponse>(`/v1/work-items/${input.itemId}:unassign${reasonParam}`, {});
      return response.item;
    },
    onMutate: async (input) => {
      await queryClient.cancelQueries({ queryKey: boardKeys.item(input.itemId) });
      if (boardId) {
        await queryClient.cancelQueries({ queryKey: boardKeys.items(boardId) });
      }

      const previousItem = queryClient.getQueryData<WorkItem | null>(boardKeys.item(input.itemId)) ?? null;
      const previousItems = boardId ? (queryClient.getQueryData<WorkItem[]>(boardKeys.items(boardId)) ?? []) : null;

      const applyPatch = (item: WorkItem): WorkItem => ({
        ...item,
        assignee_id: null,
        assignee_type: null,
      });

      if (previousItem) {
        queryClient.setQueryData<WorkItem | null>(boardKeys.item(input.itemId), applyPatch(previousItem));
      }

      if (boardId && previousItems) {
        queryClient.setQueryData<WorkItem[]>(boardKeys.items(boardId), (current) => {
          const list = current ?? [];
          return list.map((item) => (item.item_id === input.itemId ? applyPatch(item) : item));
        });
      }

      return { previousItem, previousItems };
    },
    onError: async (error, input, context) => {
      queryClient.setQueryData(boardKeys.item(input.itemId), (context as { previousItem?: WorkItem | null } | undefined)?.previousItem ?? null);
      if (boardId) {
        queryClient.setQueryData(boardKeys.items(boardId), (context as { previousItems?: WorkItem[] } | undefined)?.previousItems ?? []);
      }
      await razeLog('ERROR', 'Work item unassign failed', {
        board_id: boardId ?? null,
        item_id: input.itemId,
        error: error instanceof Error ? error.message : String(error),
      });
    },
    onSuccess: async (updated) => {
      queryClient.setQueryData<WorkItem | null>(boardKeys.item(updated.item_id), updated);
      if (boardId) {
        queryClient.setQueryData<WorkItem[]>(boardKeys.items(boardId), (current) => {
          const list = current ?? [];
          return list.map((item) => (item.item_id === updated.item_id ? updated : item));
        });
      }
      await razeLog('INFO', 'Work item unassigned', {
        board_id: boardId ?? null,
        item_id: updated.item_id,
      });
    },
  });
}

export function usePostWorkItemComment(itemId?: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (input: {
      body: string;
      authorId: string;
      authorType: WorkItemCommentAuthorType;
      runId?: string | null;
      metadata?: Record<string, unknown>;
    }): Promise<WorkItemComment> => {
      if (!itemId) throw new Error('itemId is required');
      await razeLog('INFO', 'Work item comment post requested', {
        item_id: itemId,
        author_id: input.authorId,
        author_type: input.authorType,
      });
      const response = await apiClient.post<{ comment: WorkItemComment }>(
        `/v1/work-items/${itemId}/comments`,
        {
          body: input.body,
          author_type: input.authorType,
          run_id: input.runId ?? undefined,
          metadata: input.metadata ?? undefined,
        } satisfies CreateWorkItemCommentRequest
      );
      return response.comment;
    },
    onMutate: async (input) => {
      if (!itemId) return {};
      await queryClient.cancelQueries({ queryKey: boardKeys.comments(itemId) });

      const previous = queryClient.getQueryData<WorkItemComment[]>(boardKeys.comments(itemId)) ?? [];
      const optimisticId = `temp-comment-${Date.now()}`;
      const now = new Date().toISOString();
      const optimistic: WorkItemComment = {
        comment_id: optimisticId,
        work_item_id: itemId,
        author_id: input.authorId,
        author_type: input.authorType,
        content: input.body,
        run_id: input.runId ?? null,
        metadata: input.metadata ?? {},
        created_at: now,
        updated_at: now,
      };
      queryClient.setQueryData<WorkItemComment[]>(boardKeys.comments(itemId), [...previous, optimistic]);

      return { previous, optimisticId };
    },
    onError: async (error, input, context) => {
      if (!itemId) return;
      const previous = (context as { previous?: WorkItemComment[] } | undefined)?.previous ?? [];
      queryClient.setQueryData(boardKeys.comments(itemId), previous);
      await razeLog('ERROR', 'Work item comment post failed', {
        item_id: itemId,
        error: error instanceof Error ? error.message : String(error),
      });
    },
    onSuccess: async (comment, input, context) => {
      if (!itemId) return;
      const optimisticId = (context as { optimisticId?: string } | undefined)?.optimisticId ?? null;
      queryClient.setQueryData<WorkItemComment[]>(boardKeys.comments(itemId), (current) => {
        const list = current ?? [];
        if (!optimisticId) return [...list, comment];
        const replaced = list.map((entry) => (entry.comment_id === optimisticId ? comment : entry));
        return replaced.some((entry) => entry.comment_id === comment.comment_id) ? replaced : [...replaced, comment];
      });
      await razeLog('INFO', 'Work item comment posted', {
        item_id: itemId,
        comment_id: comment.comment_id,
      });
    },
  });
}
