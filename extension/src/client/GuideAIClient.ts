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

export class GuideAIClient {
	private pythonPath: string;
	private cliPath: string;
	private outputChannel: vscode.OutputChannel;
	private telemetryEnabled: boolean;
	private telemetryActorId: string;
	private telemetryActorRole: string;
	private readonly telemetrySurface = 'VSCODE';

	constructor(private context: vscode.ExtensionContext) {
		const config = vscode.workspace.getConfiguration('guideai');
		this.pythonPath = config.get('pythonPath', 'python');
		this.cliPath = config.get('cliPath', 'guideai');
		this.outputChannel = vscode.window.createOutputChannel('GuideAI');
		this.telemetryEnabled = config.get('telemetryEnabled', true);
		this.telemetryActorId = config.get('telemetryActorId', 'vscode-user');
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

	/**
	 * Execute CLI command and return parsed JSON result
	 */
	private async runCLI(args: string[], options: { parseJson?: boolean } = {}): Promise<any> {
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
