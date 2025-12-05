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
import { spawn, ChildProcess} from 'child_process';
import { promises as fs } from 'fs';
import * as os from 'os';
import * as path from 'path';

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
	// Current version fields (from active version)
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
	role_focus?: string;  // Alias for role
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

// Cost Analytics interfaces (Customer-Facing)
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

// Run-related interfaces
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

// Compliance-related interfaces
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

export class GuideAIClient {
	private pythonPath: string;
	private cliPath: string;
	private outputChannel: vscode.OutputChannel;
	private telemetryEnabled: boolean;
	private telemetryActorId: string;
	private telemetryActorRole: string;
	private readonly telemetrySurface = 'MCP';  // IDE-agnostic: works across VS Code, Cursor, Claude Desktop

	constructor(private context: vscode.ExtensionContext) {
		const config = vscode.workspace.getConfiguration('guideai');
		this.pythonPath = config.get('pythonPath', 'python');
		this.cliPath = config.get('cliPath', 'guideai');
		this.outputChannel = vscode.window.createOutputChannel('GuideAI');
		this.telemetryEnabled = config.get('telemetryEnabled', true);
		this.telemetryActorId = config.get('telemetryActorId', 'ide-user');  // IDE-agnostic default
		this.telemetryActorRole = config.get('telemetryActorRole', 'STUDENT');
	}

	/**
	 * List all behaviors with optional filters
	 */
	async listBehaviors(
		filters?: { status?: string; tags?: string[]; role_focus?: string },
		telemetryContext: BehaviorTelemetryContext = {}
	): Promise<Behavior[]> {
		const args = ['behaviors', 'list'];
		if (filters?.status) {
			args.push('--status', filters.status);
		}
		if (filters?.role_focus) {
			args.push('--role-focus', filters.role_focus);
		}
		if (filters?.tags && filters.tags.length > 0) {
			args.push('--tags', ...filters.tags);
		}

		const startedAt = Date.now();
		const result = await this.runCLI(args);
		const behaviors: Behavior[] = result.map((item: any) => ({
			...item.behavior,
			versions: item.active_version ? [item.active_version] : []
		})) as Behavior[];

		const latencyMs = Date.now() - startedAt;
		this.sendTelemetry('behavior_retrieved', {
			source: telemetryContext.source ?? 'sidebar.initial_load',
			query: telemetryContext.query,
			role_focus: telemetryContext.roleFocus ?? filters?.role_focus,
			result_count: behaviors.length,
			latency_ms: latencyMs,
			behavior_ids: behaviors.map(b => b.behavior_id),
		});

		return behaviors;
	}

	/**
	 * Search behaviors with semantic query
	 */
	async searchBehaviors(
		query: string,
		filters?: { role_focus?: string; tags?: string[] },
		telemetryContext: BehaviorTelemetryContext = {}
	): Promise<Behavior[]> {
		const args = ['behaviors', 'search', '--query', query];
		if (filters?.role_focus) {
			args.push('--role-focus', filters.role_focus);
		}
		if (filters?.tags && filters.tags.length > 0) {
			args.push('--tags', ...filters.tags);
		}

		const startedAt = Date.now();
		const result = await this.runCLI(args);
		const behaviors: Behavior[] = result.map((item: any) => {
			const behavior: Behavior = {
				...item.behavior,
				versions: item.active_version ? [item.active_version] : [],
			};
			const metadata = behavior.metadata ? { ...behavior.metadata } : {};
			behavior.metadata = { ...metadata, relevance_score: item.score };
			return behavior;
		}) as Behavior[];

		const latencyMs = Date.now() - startedAt;
		this.sendTelemetry('behavior_retrieved', {
			source: telemetryContext.source ?? 'sidebar.search',
			query,
			role_focus: telemetryContext.roleFocus ?? filters?.role_focus,
			result_count: behaviors.length,
			latency_ms: latencyMs,
			behavior_ids: behaviors.map((behavior: Behavior) => behavior.behavior_id),
		});

		return behaviors;
	}

	/**
	 * Get behavior details by ID
	 */
	async getBehavior(behaviorId: string, version?: string): Promise<{ behavior: Behavior; versions: BehaviorVersion[] }> {
		const args = ['behaviors', 'get', behaviorId];
		if (version) {
			args.push('--version', version);
		}

		return await this.runCLI(args);
	}

	/**
	 * List workflow templates
	 */
	async listWorkflowTemplates(role?: string, telemetryContext: WorkflowTelemetryContext = {}): Promise<WorkflowTemplate[]> {
		const args = ['workflow', 'list-templates'];
		if (role) {
			args.push('--role', role);
		}

		const startedAt = Date.now();
		const templates: WorkflowTemplate[] = await this.runCLI(args);
		const latencyMs = Date.now() - startedAt;
		this.sendTelemetry('workflow_templates_retrieved', {
			source: telemetryContext.source ?? 'plan_composer.load',
			role_focus: telemetryContext.roleFocus ?? role,
			template_count: templates.length,
			latency_ms: latencyMs,
			template_ids: templates.map(t => t.template_id)
		});

		return templates;
	}

	/**
	 * Get workflow template details
	 */
	async getWorkflowTemplate(templateId: string): Promise<WorkflowTemplate> {
		const args = ['workflow', 'get-template', templateId];
		return await this.runCLI(args);
	}

	/**
	 * Run a workflow from template
	 */
	async runWorkflow(templateId: string, context?: any, telemetryContext: WorkflowTelemetryContext = {}): Promise<{ run_id: string }> {
		const args = ['workflow', 'run', templateId];
		if (context) {
			args.push('--context', JSON.stringify(context));
		}

		const startedAt = Date.now();
		const result = await this.runCLI(args);
		const latencyMs = Date.now() - startedAt;
		const behaviorCount = Array.isArray(context?.behaviors) ? context.behaviors.length : 0;
		const contextKeys = context ? Object.keys(context) : [];
		this.sendTelemetry('workflow_run_submitted', {
			source: telemetryContext.source ?? 'plan_composer.run',
			template_id: templateId,
			behavior_count: behaviorCount,
			context_keys: contextKeys,
			latency_ms: latencyMs
		}, { runId: result?.run_id });

		return result;
	}

	/**
	 * Get workflow run status
	 */
	async getWorkflowStatus(runId: string): Promise<any> {
		const args = ['workflow', 'status', runId];
		return await this.runCLI(args);
	}

	// ========================================
	// RunService Methods (Epic 5.4)
	// ========================================

	/**
	 * List all workflow runs with optional filters
	 */
	async listRuns(filters?: { status?: string; workflow_id?: string; template_id?: string; limit?: number }): Promise<Run[]> {
		const args = ['runs', 'list'];
		if (filters?.status) {
			args.push('--status', filters.status);
		}
		if (filters?.workflow_id) {
			args.push('--workflow-id', filters.workflow_id);
		}
		if (filters?.template_id) {
			args.push('--template-id', filters.template_id);
		}
		if (filters?.limit) {
			args.push('--limit', String(filters.limit));
		}

		const startedAt = Date.now();
		const runs: Run[] = await this.runCLI(args);
		const latencyMs = Date.now() - startedAt;
		this.sendTelemetry('runs_retrieved', {
			source: 'execution_tracker.load',
			status_filter: filters?.status,
			workflow_id: filters?.workflow_id,
			template_id: filters?.template_id,
			run_count: runs.length,
			latency_ms: latencyMs,
			run_ids: runs.map(r => r.run_id)
		});

		return runs;
	}

	/**
	 * Get detailed information about a specific run
	 */
	async getRun(runId: string): Promise<Run> {
		const args = ['runs', 'get', runId];
		return await this.runCLI(args);
	}

	/**
	 * Update run progress and status
	 */
	async updateRun(runId: string, update: {
		status?: string;
		progress_pct?: number;
		message?: string;
		step_id?: string;
		step_name?: string;
		step_status?: string;
		tokens_generated?: number;
		tokens_baseline?: number;
		metadata?: Record<string, any>;
	}): Promise<Run> {
		const args = ['runs', 'update', runId];
		if (update.status) {
			args.push('--status', update.status);
		}
		if (update.progress_pct !== undefined) {
			args.push('--progress-pct', String(update.progress_pct));
		}
		if (update.message) {
			args.push('--message', update.message);
		}
		if (update.step_id) {
			args.push('--step-id', update.step_id);
		}
		if (update.step_name) {
			args.push('--step-name', update.step_name);
		}
		if (update.step_status) {
			args.push('--step-status', update.step_status);
		}
		if (update.tokens_generated !== undefined) {
			args.push('--tokens-generated', String(update.tokens_generated));
		}
		if (update.tokens_baseline !== undefined) {
			args.push('--tokens-baseline', String(update.tokens_baseline));
		}
		if (update.metadata) {
			args.push('--metadata', JSON.stringify(update.metadata));
		}

		return await this.runCLI(args);
	}

	// ========================================
	// ComplianceService Methods (Epic 5.5)
	// ========================================

	/**
	 * List compliance checklists with optional filters
	 */
	async listComplianceChecklists(filters?: {
		milestone?: string;
		compliance_category?: string[];
		status_filter?: string;
	}): Promise<ComplianceChecklist[]> {
		const args = ['compliance', 'list-checklists'];
		if (filters?.milestone) {
			args.push('--milestone', filters.milestone);
		}
		if (filters?.compliance_category && filters.compliance_category.length > 0) {
			args.push('--category', ...filters.compliance_category);
		}
		if (filters?.status_filter) {
			args.push('--status-filter', filters.status_filter);
		}

		const startedAt = Date.now();
		const checklists: ComplianceChecklist[] = await this.runCLI(args);
		const latencyMs = Date.now() - startedAt;
		this.sendTelemetry('compliance_checklists_retrieved', {
			source: 'compliance_panel.load',
			milestone: filters?.milestone,
			compliance_category: filters?.compliance_category,
			status_filter: filters?.status_filter,
			checklist_count: checklists.length,
			latency_ms: latencyMs,
			checklist_ids: checklists.map(c => c.checklist_id)
		});

		return checklists;
	}

	/**
	 * Get detailed information about a specific compliance checklist
	 */
	async getComplianceChecklist(checklistId: string): Promise<ComplianceChecklist> {
		const args = ['compliance', 'get-checklist', checklistId];
		return await this.runCLI(args);
	}

	/**
	 * Create a new compliance checklist
	 */
	async createComplianceChecklist(checklist: {
		title: string;
		description: string;
		template_id?: string;
		milestone?: string;
		compliance_category: string[];
		actor: { id: string; role: string; surface: string };
	}): Promise<ComplianceChecklist> {
		const args = ['compliance', 'create-checklist', checklist.title, '--description', checklist.description];
		if (checklist.template_id) {
			args.push('--template-id', checklist.template_id);
		}
		if (checklist.milestone) {
			args.push('--milestone', checklist.milestone);
		}
		if (checklist.compliance_category.length > 0) {
			args.push('--category', ...checklist.compliance_category);
		}

		return await this.runCLI(args);
	}

	/**
	 * Record a step in a compliance checklist
	 */
	async recordComplianceStep(step: {
		checklist_id: string;
		title: string;
		status: string;
		evidence?: Record<string, any>;
		behaviors_cited?: string[];
		related_run_id?: string;
		actor: { id: string; role: string; surface: string };
	}): Promise<ComplianceStep> {
		const args = ['compliance', 'record-step', step.checklist_id, step.title, '--status', step.status];
		if (step.evidence) {
			args.push('--evidence', JSON.stringify(step.evidence));
		}
		if (step.behaviors_cited && step.behaviors_cited.length > 0) {
			args.push('--behaviors-cited', ...step.behaviors_cited);
		}
		if (step.related_run_id) {
			args.push('--related-run-id', step.related_run_id);
		}

		return await this.runCLI(args);
	}

	/**
	 * Validate a compliance checklist
	 */
	async validateComplianceChecklist(checklistId: string, actor: { id: string; role: string; surface: string }): Promise<any> {
		const args = ['compliance', 'validate-checklist', checklistId];
		return await this.runCLI(args);
	}

	async bciRetrieve(options: BCIRetrieveOptions): Promise<BCIRetrieveResponse> {
		const args = ['bci', 'retrieve', '--query', options.query];
		if (options.topK !== undefined) {
			args.push('--top-k', String(options.topK));
		}
		if (options.strategy) {
			args.push('--strategy', options.strategy);
		}
		if (options.roleFocus) {
			args.push('--role-focus', options.roleFocus);
		}
		if (options.tags && options.tags.length > 0) {
			for (const tag of options.tags) {
				args.push('--tag', tag);
			}
		}
		if (options.includeMetadata) {
			args.push('--include-metadata');
		}
		if (options.embeddingWeight !== undefined) {
			args.push('--embedding-weight', String(options.embeddingWeight));
		}
		if (options.keywordWeight !== undefined) {
			args.push('--keyword-weight', String(options.keywordWeight));
		}
		const response = await this.runCLI(args);
		return response as BCIRetrieveResponse;
	}

	async bciValidateCitations(request: BCIValidateRequest): Promise<BCIValidateResponse> {
		const tmpDir = await fs.mkdtemp(path.join(os.tmpdir(), 'guideai-bci-'));
		const outputPath = path.join(tmpDir, 'output.txt');
		const prependedPath = path.join(tmpDir, 'prepended.json');
		try {
			await fs.writeFile(outputPath, request.outputText, 'utf8');
			await fs.writeFile(prependedPath, JSON.stringify(request.prepended, null, 2), 'utf8');

			const args = ['bci', 'validate-citations', '--output-file', outputPath, '--prepended-file', prependedPath];
			if (request.minimumCitations !== undefined) {
				args.push('--minimum', String(request.minimumCitations));
			}
			if (request.allowUnlisted) {
				args.push('--allow-unlisted');
			}

			const response = await this.runCLI(args);
			return response as BCIValidateResponse;
		} finally {
			await this.cleanupTempDir(tmpDir);
		}
	}

	// ─────────────────────────────────────────────────────────────────────────────
	// Cost Analytics (Customer-Facing)
	// ─────────────────────────────────────────────────────────────────────────────

	/**
	 * Convert days to start/end date strings for CLI
	 */
	private daysToDateRange(days: number): { startDate: string; endDate: string } {
		const endDate = new Date();
		const startDate = new Date();
		startDate.setDate(startDate.getDate() - days);

		const formatDate = (d: Date) => d.toISOString().split('T')[0];
		return {
			startDate: formatDate(startDate),
			endDate: formatDate(endDate)
		};
	}

	/**
	 * Get cost breakdown by service (LLM, storage, compute, etc.)
	 */
	async getCostByService(days: number = 30): Promise<CostByServiceResponse> {
		const { startDate, endDate } = this.daysToDateRange(days);
		const args = ['analytics', 'cost-by-service', '--start-date', startDate, '--end-date', endDate];
		return await this.runCLI(args);
	}

	/**
	 * Get cost per run statistics
	 */
	async getCostPerRun(days: number = 30, limit: number = 100): Promise<CostPerRunResponse> {
		const { startDate, endDate } = this.daysToDateRange(days);
		const args = ['analytics', 'cost-per-run', '--start-date', startDate, '--end-date', endDate, '--limit', String(limit)];
		return await this.runCLI(args);
	}

	/**
	 * Get ROI summary with token savings value
	 */
	async getROISummary(days: number = 30): Promise<ROISummaryResponse> {
		const args = ['analytics', 'roi-summary'];
		return await this.runCLI(args);
	}

	/**
	 * Get daily cost trend
	 */
	async getDailyCosts(days: number = 30): Promise<DailyCostResponse> {
		const { startDate, endDate } = this.daysToDateRange(days);
		const args = ['analytics', 'daily-costs', '--start-date', startDate, '--end-date', endDate, '--limit', String(days)];
		return await this.runCLI(args);
	}

	/**
	 * Get top expensive workflows
	 */
	async getTopExpensiveWorkflows(days: number = 30, limit: number = 10): Promise<TopExpensiveResponse> {
		const args = ['analytics', 'top-expensive', '--limit', String(limit)];
		return await this.runCLI(args);
	}

	/**
	 * Execute CLI command and return parsed JSON result
	 */
	async runCLI(args: string[], options: { parseJson?: boolean } = {}): Promise<any> {
		const parseJson = options.parseJson !== false;
		const finalArgs = parseJson ? this.withJsonFormat(args) : args;

		return new Promise((resolve, reject) => {
			this.outputChannel.appendLine(`Running: ${this.cliPath} ${finalArgs.join(' ')}`);

			const childProcess: ChildProcess = spawn(this.cliPath, finalArgs, {
				shell: true,
				env: { ...process.env }
			});

			let stdout = '';
			let stderr = '';

			childProcess.stdout?.on('data', (data) => {
				stdout += data.toString();
			});

			childProcess.stderr?.on('data', (data) => {
				stderr += data.toString();
				this.outputChannel.appendLine(`stderr: ${data}`);
			});

			childProcess.on('close', (code) => {
				if (code !== 0) {
					this.outputChannel.appendLine(`Command failed with code ${code}`);
					this.outputChannel.appendLine(`stderr: ${stderr}`);
					reject(new Error(`CLI command failed: ${stderr || `exit code ${code}`}`));
					return;
				}

				if (!parseJson) {
					resolve(stdout);
					return;
				}

				try {
					const result = JSON.parse(stdout);
					resolve(result);
				} catch (error) {
					this.outputChannel.appendLine(`Failed to parse JSON: ${stdout}`);
					reject(new Error(`Failed to parse CLI output: ${error}`));
				}
			});

			childProcess.on('error', (error) => {
				this.outputChannel.appendLine(`Process error: ${error.message}`);
				reject(error);
			});
		});
	}

	private sendTelemetry(eventType: string, payload: Record<string, unknown>, options: TelemetryEmitOptions = {}): void {
		this.emitTelemetry(eventType, payload, options).catch((error) => {
			const message = error instanceof Error ? error.message : String(error);
			this.outputChannel.appendLine(`Telemetry error: ${message}`);
		});
	}

	async emitTelemetry(eventType: string, payload: Record<string, unknown>, options: TelemetryEmitOptions = {}): Promise<void> {
		if (!this.telemetryEnabled) {
			return;
		}

		const args = ['telemetry', 'emit', '--event-type', eventType, '--actor-id', this.telemetryActorId, '--actor-role', this.telemetryActorRole, '--actor-surface', this.telemetrySurface];

		const serializedPayload = JSON.stringify(payload ?? {});
		args.push('--payload', serializedPayload);

		if (options.runId) {
			args.push('--run-id', options.runId);
		}
		if (options.actionId) {
			args.push('--action-id', options.actionId);
		}
		const sessionId = options.sessionId ?? vscode.env.sessionId;
		if (sessionId) {
			args.push('--session-id', sessionId);
		}

		await this.runCLI(args);
	}

	private withJsonFormat(args: string[]): string[] {
		if (args.includes('--format')) {
			return args;
		}
		return [...args, '--format', 'json'];
	}

	private async cleanupTempDir(tmpDir: string): Promise<void> {
		try {
			await fs.rm(tmpDir, { recursive: true, force: true });
		} catch (error) {
			const message = error instanceof Error ? error.message : String(error);
			this.outputChannel.appendLine(`Failed to cleanup temp directory ${tmpDir}: ${message}`);
		}
	}

	dispose() {
		this.outputChannel.dispose();
	}
}
