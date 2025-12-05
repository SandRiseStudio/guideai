/**
 * GuideAI Client
 *
 * Communicates with the guideai Python CLI to access:
 * - BehaviorService (via MCP tools)
 * - WorkflowService (via MCP tools)
 * - ComplianceService (via MCP tools)
 * - ActionService
 */
import * as vscode from 'vscode';
interface BehaviorTelemetryContext {
    source?: string;
    query?: string;
    roleFocus?: string;
}
interface WorkflowTelemetryContext {
    source?: string;
    roleFocus?: string;
}
interface TelemetryEmitOptions {
    runId?: string;
    actionId?: string;
    sessionId?: string;
}
export interface Behavior {
    behavior_id: string;
    name: string;
    description: string;
    tags: string[];
    status: string;
    versions?: BehaviorVersion[];
    version?: string;
    instruction?: string;
    role_focus?: string;
    trigger_keywords?: string[];
    examples?: any[];
    metadata?: any;
}
export interface BehaviorVersion {
    version: string;
    status: string;
    instruction: string;
    role_focus: string;
    trigger_keywords: string[];
    examples: any[];
    metadata: any;
    created_by: string;
    effective_from?: string;
}
export interface WorkflowTemplate {
    template_id: string;
    name: string;
    description: string;
    role: string;
    role_focus?: string;
    steps: WorkflowStep[];
}
export interface WorkflowStep {
    step_id: string;
    name: string;
    description: string;
    behavior_ids: string[];
}
export interface BCIBehaviorMatch {
    behavior_id: string;
    name: string;
    version: string;
    instruction: string;
    score: number;
    description?: string;
    role_focus?: string;
    tags?: string[];
    strategy_breakdown?: Record<string, number>;
    citation_label?: string;
    metadata?: Record<string, unknown> | null;
}
export interface BCIRetrieveOptions {
    query: string;
    topK?: number;
    strategy?: 'embedding' | 'keyword' | 'hybrid';
    roleFocus?: string;
    tags?: string[];
    includeMetadata?: boolean;
    embeddingWeight?: number;
    keywordWeight?: number;
}
export interface BCIRetrieveResponse {
    query: string;
    results: BCIBehaviorMatch[];
    strategy_used: string;
    latency_ms?: number;
    metadata?: Record<string, unknown> | null;
}
export interface BCIPrependedBehavior {
    behavior_name: string;
    behavior_id?: string;
    version?: string;
}
export interface BCICitation {
    text: string;
    type: string;
    start_index: number;
    end_index: number;
    behavior_name?: string;
    behavior_id?: string;
    confidence?: number;
}
export interface BCIValidateRequest {
    outputText: string;
    prepended: BCIPrependedBehavior[];
    minimumCitations?: number;
    allowUnlisted?: boolean;
}
export interface BCIValidateResponse {
    total_citations: number;
    valid_citations: BCICitation[];
    invalid_citations: BCICitation[];
    compliance_rate: number;
    is_compliant: boolean;
    missing_behaviors: string[];
    warnings: string[];
}
export interface CostByServiceRow {
    service: string;
    total_cost_usd: number;
    total_runs: number;
    avg_cost_per_run: number;
    pct_of_total: number;
}
export interface CostByServiceResponse {
    period_days: number;
    rows: CostByServiceRow[];
    total_cost_usd: number;
}
export interface CostPerRunRow {
    run_id: string;
    workflow_name: string;
    cost_usd: number;
    tokens_generated: number;
    created_at: string;
    status: string;
}
export interface CostPerRunResponse {
    period_days: number;
    rows: CostPerRunRow[];
    avg_cost_per_run: number;
    total_runs: number;
}
export interface ROISummaryResponse {
    period_days: number;
    total_cost_usd: number;
    total_tokens_saved: number;
    token_savings_value_usd: number;
    net_cost_usd: number;
    roi_ratio: number;
    runs_analyzed: number;
}
export interface DailyCostRow {
    date: string;
    cost_usd: number;
    runs: number;
    tokens: number;
}
export interface DailyCostResponse {
    period_days: number;
    rows: DailyCostRow[];
    avg_daily_cost: number;
    max_daily_cost: number;
}
export interface TopExpensiveRow {
    workflow_id: string;
    workflow_name: string;
    total_cost_usd: number;
    run_count: number;
    avg_cost_per_run: number;
}
export interface TopExpensiveResponse {
    period_days: number;
    rows: TopExpensiveRow[];
}
export interface Run {
    run_id: string;
    status: string;
    progress_pct: number;
    actor: {
        id: string;
        role: string;
        surface: string;
    };
    workflow_id?: string;
    workflow_name?: string;
    template_id?: string;
    template_name?: string;
    behavior_ids: string[];
    initial_message?: string;
    total_steps?: number;
    created_at: string;
    updated_at: string;
    completed_at?: string;
    metadata: Record<string, any>;
    step_current?: {
        step_id: string;
        name: string;
        status: string;
    };
    step_progress?: {
        current: number;
        total: number;
    };
    tokens_generated?: number;
    tokens_baseline?: number;
    error?: string;
    outputs?: Record<string, any>;
}
export interface ComplianceChecklist {
    checklist_id: string;
    title: string;
    description: string;
    template_id?: string;
    milestone?: string;
    compliance_category: string[];
    actor: {
        id: string;
        role: string;
        surface: string;
    };
    created_at: string;
    updated_at: string;
    status: 'DRAFT' | 'IN_PROGRESS' | 'COMPLETED' | 'APPROVED' | 'REJECTED';
    progress: {
        total_steps: number;
        completed_steps: number;
        coverage_score: number;
    };
    steps: ComplianceStep[];
}
export interface ComplianceStep {
    step_id: string;
    checklist_id: string;
    title: string;
    status: 'PENDING' | 'IN_PROGRESS' | 'COMPLETED' | 'BLOCKED' | 'SKIPPED';
    actor: {
        id: string;
        role: string;
        surface: string;
    };
    created_at: string;
    updated_at: string;
    completed_at?: string;
    evidence: Record<string, any>;
    behaviors_cited: string[];
    related_run_id?: string;
    comments: ComplianceComment[];
}
export interface ComplianceComment {
    comment_id: string;
    step_id: string;
    actor: {
        id: string;
        role: string;
        surface: string;
    };
    content: string;
    created_at: string;
}
export declare class GuideAIClient {
    private context;
    private pythonPath;
    private cliPath;
    private outputChannel;
    private telemetryEnabled;
    private telemetryActorId;
    private telemetryActorRole;
    private readonly telemetrySurface;
    constructor(context: vscode.ExtensionContext);
    /**
     * List all behaviors with optional filters
     */
    listBehaviors(filters?: {
        status?: string;
        tags?: string[];
        role_focus?: string;
    }, telemetryContext?: BehaviorTelemetryContext): Promise<Behavior[]>;
    /**
     * Search behaviors with semantic query
     */
    searchBehaviors(query: string, filters?: {
        role_focus?: string;
        tags?: string[];
    }, telemetryContext?: BehaviorTelemetryContext): Promise<Behavior[]>;
    /**
     * Get behavior details by ID
     */
    getBehavior(behaviorId: string, version?: string): Promise<{
        behavior: Behavior;
        versions: BehaviorVersion[];
    }>;
    /**
     * List workflow templates
     */
    listWorkflowTemplates(role?: string, telemetryContext?: WorkflowTelemetryContext): Promise<WorkflowTemplate[]>;
    /**
     * Get workflow template details
     */
    getWorkflowTemplate(templateId: string): Promise<WorkflowTemplate>;
    /**
     * Run a workflow from template
     */
    runWorkflow(templateId: string, context?: any, telemetryContext?: WorkflowTelemetryContext): Promise<{
        run_id: string;
    }>;
    /**
     * Get workflow run status
     */
    getWorkflowStatus(runId: string): Promise<any>;
    /**
     * List all workflow runs with optional filters
     */
    listRuns(filters?: {
        status?: string;
        workflow_id?: string;
        template_id?: string;
        limit?: number;
    }): Promise<Run[]>;
    /**
     * Get detailed information about a specific run
     */
    getRun(runId: string): Promise<Run>;
    /**
     * Update run progress and status
     */
    updateRun(runId: string, update: {
        status?: string;
        progress_pct?: number;
        message?: string;
        step_id?: string;
        step_name?: string;
        step_status?: string;
        tokens_generated?: number;
        tokens_baseline?: number;
        metadata?: Record<string, any>;
    }): Promise<Run>;
    /**
     * List compliance checklists with optional filters
     */
    listComplianceChecklists(filters?: {
        milestone?: string;
        compliance_category?: string[];
        status_filter?: string;
    }): Promise<ComplianceChecklist[]>;
    /**
     * Get detailed information about a specific compliance checklist
     */
    getComplianceChecklist(checklistId: string): Promise<ComplianceChecklist>;
    /**
     * Create a new compliance checklist
     */
    createComplianceChecklist(checklist: {
        title: string;
        description: string;
        template_id?: string;
        milestone?: string;
        compliance_category: string[];
        actor: {
            id: string;
            role: string;
            surface: string;
        };
    }): Promise<ComplianceChecklist>;
    /**
     * Record a step in a compliance checklist
     */
    recordComplianceStep(step: {
        checklist_id: string;
        title: string;
        status: string;
        evidence?: Record<string, any>;
        behaviors_cited?: string[];
        related_run_id?: string;
        actor: {
            id: string;
            role: string;
            surface: string;
        };
    }): Promise<ComplianceStep>;
    /**
     * Validate a compliance checklist
     */
    validateComplianceChecklist(checklistId: string, actor: {
        id: string;
        role: string;
        surface: string;
    }): Promise<any>;
    bciRetrieve(options: BCIRetrieveOptions): Promise<BCIRetrieveResponse>;
    bciValidateCitations(request: BCIValidateRequest): Promise<BCIValidateResponse>;
    /**
     * Convert days to start/end date strings for CLI
     */
    private daysToDateRange;
    /**
     * Get cost breakdown by service (LLM, storage, compute, etc.)
     */
    getCostByService(days?: number): Promise<CostByServiceResponse>;
    /**
     * Get cost per run statistics
     */
    getCostPerRun(days?: number, limit?: number): Promise<CostPerRunResponse>;
    /**
     * Get ROI summary with token savings value
     */
    getROISummary(days?: number): Promise<ROISummaryResponse>;
    /**
     * Get daily cost trend
     */
    getDailyCosts(days?: number): Promise<DailyCostResponse>;
    /**
     * Get top expensive workflows
     */
    getTopExpensiveWorkflows(days?: number, limit?: number): Promise<TopExpensiveResponse>;
    /**
     * Execute CLI command and return parsed JSON result
     */
    runCLI(args: string[], options?: {
        parseJson?: boolean;
    }): Promise<any>;
    private sendTelemetry;
    emitTelemetry(eventType: string, payload: Record<string, unknown>, options?: TelemetryEmitOptions): Promise<void>;
    private withJsonFormat;
    private cleanupTempDir;
    dispose(): void;
}
export {};
//# sourceMappingURL=GuideAIClient.d.ts.map
