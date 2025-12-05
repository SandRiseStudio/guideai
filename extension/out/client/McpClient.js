"use strict";
/**
 * MCP Client for GuideAI Extension
 *
 * Provides direct MCP protocol communication with the guideai MCP server.
 * Used for real-time operations like device flow auth, consent management,
 * and streaming progress updates.
 *
 * Advantages over CLI:
 * - Persistent connection (lower latency after connect)
 * - Streaming responses for long operations
 * - Bidirectional communication
 * - Native MCP protocol (consistent with Claude Desktop, Cursor, etc.)
 */
var __createBinding = (this && this.__createBinding) || (Object.create ? (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    var desc = Object.getOwnPropertyDescriptor(m, k);
    if (!desc || ("get" in desc ? !m.__esModule : desc.writable || desc.configurable)) {
      desc = { enumerable: true, get: function() { return m[k]; } };
    }
    Object.defineProperty(o, k2, desc);
}) : (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    o[k2] = m[k];
}));
var __setModuleDefault = (this && this.__setModuleDefault) || (Object.create ? (function(o, v) {
    Object.defineProperty(o, "default", { enumerable: true, value: v });
}) : function(o, v) {
    o["default"] = v;
});
var __importStar = (this && this.__importStar) || (function () {
    var ownKeys = function(o) {
        ownKeys = Object.getOwnPropertyNames || function (o) {
            var ar = [];
            for (var k in o) if (Object.prototype.hasOwnProperty.call(o, k)) ar[ar.length] = k;
            return ar;
        };
        return ownKeys(o);
    };
    return function (mod) {
        if (mod && mod.__esModule) return mod;
        var result = {};
        if (mod != null) for (var k = ownKeys(mod), i = 0; i < k.length; i++) if (k[i] !== "default") __createBinding(result, mod, k[i]);
        __setModuleDefault(result, mod);
        return result;
    };
})();
Object.defineProperty(exports, "__esModule", { value: true });
exports.McpClient = void 0;
const vscode = __importStar(require("vscode"));
const child_process_1 = require("child_process");
const events_1 = require("events");
const RazeClient_1 = require("./RazeClient");
// ============================================
// MCP Client
// ============================================
class McpClient extends events_1.EventEmitter {
    constructor(context) {
        super();
        this.context = context;
        this.process = null;
        this.pendingRequests = new Map();
        this.requestId = 0;
        this.buffer = '';
        this.isConnected = false;
        this.connectionPromise = null;
        // Stability features
        this.connectionState = 'disconnected';
        this.heartbeatInterval = null;
        this.reconnectAttempts = 0;
        this.requestQueue = [];
        // Telemetry (behavior_use_raze_for_logging)
        this.razeClient = null;
        const config = vscode.workspace.getConfiguration('guideai');
        this.pythonPath = config.get('pythonPath', 'python');
        this.outputChannel = vscode.window.createOutputChannel('GuideAI MCP');
        // Load stability configuration
        this.requestTimeoutMs = config.get('mcpRequestTimeout', 30000);
        this.heartbeatIntervalMs = config.get('mcpHeartbeatInterval', 30000);
        this.maxReconnectAttempts = config.get('mcpMaxReconnectAttempts', 10);
        this.autoReconnect = config.get('mcpAutoReconnect', true);
        // Initialize telemetry (behavior_use_raze_for_logging)
        this.telemetryEnabled = config.get('telemetryEnabled', false);
        if (this.telemetryEnabled) {
            this.razeClient = new RazeClient_1.RazeClient(context, {
                serviceName: 'guideai-mcp-client',
            });
        }
        // Listen for configuration changes
        vscode.workspace.onDidChangeConfiguration(e => {
            if (e.affectsConfiguration('guideai')) {
                const newConfig = vscode.workspace.getConfiguration('guideai');
                this.requestTimeoutMs = newConfig.get('mcpRequestTimeout', 30000);
                this.heartbeatIntervalMs = newConfig.get('mcpHeartbeatInterval', 30000);
                this.maxReconnectAttempts = newConfig.get('mcpMaxReconnectAttempts', 10);
                this.autoReconnect = newConfig.get('mcpAutoReconnect', true);
                // Handle telemetry configuration changes
                const newTelemetryEnabled = newConfig.get('telemetryEnabled', false);
                if (newTelemetryEnabled && !this.razeClient) {
                    this.razeClient = new RazeClient_1.RazeClient(context, {
                        serviceName: 'guideai-mcp-client',
                    });
                }
                this.telemetryEnabled = newTelemetryEnabled;
            }
        });
    }
    // ============================================
    // Connection Management
    // ============================================
    /**
     * Get current connection status for UI display
     */
    getConnectionStatus() {
        return {
            state: this.connectionState,
            lastHeartbeat: this.lastHeartbeat,
            reconnectAttempts: this.reconnectAttempts,
            lastError: this.lastError
        };
    }
    /**
     * Connect to the MCP server (spawns guideai.mcp_server as subprocess)
     */
    async connect() {
        if (this.isConnected) {
            return;
        }
        if (this.connectionPromise) {
            return this.connectionPromise;
        }
        this.setConnectionState('connecting');
        this.connectionPromise = this.doConnect();
        try {
            await this.connectionPromise;
            this.reconnectAttempts = 0;
            this.lastError = undefined;
            this.startHeartbeat();
        }
        catch (error) {
            this.lastError = error instanceof Error ? error.message : String(error);
            throw error;
        }
        finally {
            this.connectionPromise = null;
        }
    }
    async doConnect() {
        return new Promise((resolve, reject) => {
            this.outputChannel.appendLine('Starting MCP server...');
            this.process = (0, child_process_1.spawn)(this.pythonPath, ['-m', 'guideai.mcp_server'], {
                stdio: ['pipe', 'pipe', 'pipe'],
                env: { ...process.env }
            });
            // Handle stdout (MCP responses)
            this.process.stdout?.on('data', (data) => {
                this.handleData(data.toString());
            });
            // Handle stderr (logs)
            this.process.stderr?.on('data', (data) => {
                const text = data.toString();
                this.outputChannel.appendLine(`[stderr] ${text}`);
            });
            // Handle process exit
            this.process.on('close', (code) => {
                this.outputChannel.appendLine(`MCP server exited with code ${code}`);
                this.isConnected = false;
                this.stopHeartbeat();
                this.setConnectionState('disconnected');
                this.rejectAllPending(new Error(`MCP server exited with code ${code}`));
                this.emit('disconnected', code);
                // Attempt auto-reconnect if enabled and not intentionally disconnected
                if (this.autoReconnect && code !== 0) {
                    this.scheduleReconnect();
                }
            });
            this.process.on('error', (err) => {
                this.outputChannel.appendLine(`MCP server error: ${err.message}`);
                this.isConnected = false;
                this.lastError = err.message;
                this.setConnectionState('disconnected');
                reject(err);
            });
            // Send initialize request
            setTimeout(async () => {
                try {
                    await this.sendRequestWithTimeout('initialize', {
                        protocolVersion: '2024-11-05',
                        capabilities: {},
                        clientInfo: {
                            name: 'guideai-vscode',
                            version: '1.0.0'
                        }
                    }, 10000); // 10s timeout for initialization
                    // Send initialized notification
                    this.sendNotification('notifications/initialized', {});
                    this.isConnected = true;
                    this.setConnectionState('connected');
                    this.outputChannel.appendLine('MCP connection established');
                    this.emit('connected');
                    // Flush queued requests
                    this.flushRequestQueue();
                    resolve();
                }
                catch (err) {
                    this.lastError = err instanceof Error ? err.message : String(err);
                    reject(err);
                }
            }, 100); // Small delay to let process start
        });
    }
    /**
     * Disconnect from the MCP server
     */
    disconnect() {
        // Disable auto-reconnect when explicitly disconnecting
        const savedAutoReconnect = this.autoReconnect;
        this.autoReconnect = false;
        this.stopHeartbeat();
        if (this.process) {
            this.process.kill();
            this.process = null;
        }
        this.isConnected = false;
        this.setConnectionState('disconnected');
        this.rejectAllPending(new Error('Client disconnected'));
        // Restore auto-reconnect setting
        this.autoReconnect = savedAutoReconnect;
    }
    /**
     * Check if connected
     */
    get connected() {
        return this.isConnected;
    }
    // ============================================
    // Heartbeat & Reconnection
    // ============================================
    setConnectionState(state) {
        const previousState = this.connectionState;
        this.connectionState = state;
        if (previousState !== state) {
            this.emit('connectionStateChanged', { previousState, currentState: state });
            // Log telemetry for state changes (behavior_use_raze_for_logging)
            this.logTelemetry('info', `MCP connection state changed: ${previousState} -> ${state}`, {
                previousState,
                currentState: state,
                reconnectAttempts: this.reconnectAttempts,
            });
        }
    }
    /**
     * Log telemetry event using Raze (behavior_use_raze_for_logging)
     */
    logTelemetry(level, message, context) {
        if (this.telemetryEnabled && this.razeClient) {
            this.razeClient.log(level, message, {
                ...context,
                component: 'McpClient',
                actor_surface: 'MCP', // IDE-agnostic: works across VS Code, Cursor, Claude Desktop
            });
        }
    }
    startHeartbeat() {
        this.stopHeartbeat();
        this.heartbeatInterval = setInterval(async () => {
            if (!this.isConnected) {
                return;
            }
            try {
                await this.ping();
                this.lastHeartbeat = new Date();
                this.emit('heartbeat', { timestamp: this.lastHeartbeat });
                // Log heartbeat telemetry (behavior_use_raze_for_logging)
                this.logTelemetry('debug', 'MCP heartbeat successful', {
                    timestamp: this.lastHeartbeat.toISOString(),
                });
            }
            catch (error) {
                const errorMessage = error instanceof Error ? error.message : String(error);
                this.outputChannel.appendLine(`Heartbeat failed: ${errorMessage}`);
                this.emit('heartbeatFailed', { error });
                // Log heartbeat failure telemetry (behavior_use_raze_for_logging)
                this.logTelemetry('warning', 'MCP heartbeat failed', {
                    error: errorMessage,
                    autoReconnect: this.autoReconnect,
                });
                // Heartbeat failure - server may be unresponsive, trigger reconnect
                if (this.autoReconnect) {
                    this.outputChannel.appendLine('Heartbeat failed, initiating reconnect...');
                    this.disconnect();
                }
            }
        }, this.heartbeatIntervalMs);
    }
    stopHeartbeat() {
        if (this.heartbeatInterval) {
            clearInterval(this.heartbeatInterval);
            this.heartbeatInterval = null;
        }
    }
    scheduleReconnect() {
        if (this.reconnectAttempts >= this.maxReconnectAttempts) {
            this.outputChannel.appendLine(`Max reconnect attempts (${this.maxReconnectAttempts}) reached, giving up`);
            this.emit('reconnectFailed', { attempts: this.reconnectAttempts });
            // Log reconnection failure telemetry (behavior_use_raze_for_logging)
            this.logTelemetry('error', 'MCP reconnection failed - max attempts reached', {
                maxAttempts: this.maxReconnectAttempts,
                totalAttempts: this.reconnectAttempts,
            });
            return;
        }
        // Exponential backoff: 1s, 2s, 4s, 8s, 16s, max 30s
        const backoffMs = Math.min(1000 * Math.pow(2, this.reconnectAttempts), 30000);
        this.reconnectAttempts++;
        this.outputChannel.appendLine(`Scheduling reconnect attempt ${this.reconnectAttempts} in ${backoffMs}ms`);
        this.setConnectionState('reconnecting');
        this.emit('reconnecting', { attempt: this.reconnectAttempts, backoffMs });
        // Log reconnection attempt telemetry (behavior_use_raze_for_logging)
        this.logTelemetry('info', 'MCP scheduling reconnection attempt', {
            attempt: this.reconnectAttempts,
            backoffMs,
            maxAttempts: this.maxReconnectAttempts,
        });
        setTimeout(async () => {
            try {
                this.outputChannel.appendLine(`Reconnect attempt ${this.reconnectAttempts}...`);
                await this.connect();
                this.outputChannel.appendLine('Reconnect successful');
                this.emit('reconnected', { attempts: this.reconnectAttempts });
                // Log successful reconnection telemetry (behavior_use_raze_for_logging)
                this.logTelemetry('info', 'MCP reconnection successful', {
                    totalAttempts: this.reconnectAttempts,
                });
            }
            catch (error) {
                const errorMessage = error instanceof Error ? error.message : String(error);
                this.outputChannel.appendLine(`Reconnect attempt ${this.reconnectAttempts} failed: ${errorMessage}`);
                // Log reconnection failure telemetry (behavior_use_raze_for_logging)
                this.logTelemetry('warning', 'MCP reconnection attempt failed', {
                    attempt: this.reconnectAttempts,
                    error: errorMessage,
                });
                // Next reconnect will be scheduled by the 'close' event handler
            }
        }, backoffMs);
    }
    /**
     * Send a ping to check server health
     */
    async ping() {
        const result = await this.sendRequestWithTimeout('ping', {}, 5000);
        return result;
    }
    async flushRequestQueue() {
        const queue = [...this.requestQueue];
        this.requestQueue = [];
        for (const queuedRequest of queue) {
            try {
                const result = await this.sendRequest(queuedRequest.method, queuedRequest.params);
                queuedRequest.resolve(result);
            }
            catch (error) {
                queuedRequest.reject(error instanceof Error ? error : new Error(String(error)));
            }
        }
    }
    // ============================================
    // Low-level MCP Protocol
    // ============================================
    handleData(data) {
        this.buffer += data;
        // Parse line-delimited JSON
        const lines = this.buffer.split('\n');
        this.buffer = lines.pop() || '';
        for (const line of lines) {
            if (!line.trim()) {
                continue;
            }
            try {
                const response = JSON.parse(line);
                this.outputChannel.appendLine(`[recv] ${line.substring(0, 200)}...`);
                if (response.id !== undefined) {
                    const pending = this.pendingRequests.get(response.id);
                    if (pending) {
                        clearTimeout(pending.timeout);
                        this.pendingRequests.delete(response.id);
                        if (response.error) {
                            pending.reject(new Error(response.error.message));
                        }
                        else {
                            pending.resolve(response.result);
                        }
                    }
                }
            }
            catch (err) {
                this.outputChannel.appendLine(`Failed to parse: ${line}`);
            }
        }
    }
    sendRequest(method, params) {
        return this.sendRequestWithTimeout(method, params, this.requestTimeoutMs);
    }
    sendRequestWithTimeout(method, params, timeoutMs) {
        return new Promise((resolve, reject) => {
            // If not connected and reconnecting, queue the request
            if (!this.process?.stdin || !this.isConnected) {
                if (this.connectionState === 'reconnecting') {
                    this.outputChannel.appendLine(`Queuing request during reconnect: ${method}`);
                    this.requestQueue.push({ method, params, resolve, reject });
                    return;
                }
                reject(new Error('MCP server not connected'));
                return;
            }
            const id = ++this.requestId;
            const request = {
                jsonrpc: '2.0',
                id,
                method,
                params
            };
            // Setup timeout
            const timeout = setTimeout(() => {
                const pending = this.pendingRequests.get(id);
                if (pending) {
                    this.pendingRequests.delete(id);
                    pending.reject(new Error(`Request timeout after ${timeoutMs}ms: ${method}`));
                }
            }, timeoutMs);
            this.pendingRequests.set(id, { resolve, reject, timeout });
            const json = JSON.stringify(request);
            this.outputChannel.appendLine(`[send] ${json.substring(0, 200)}...`);
            this.process.stdin.write(json + '\n');
        });
    }
    sendNotification(method, params) {
        if (!this.process?.stdin) {
            return;
        }
        const notification = {
            jsonrpc: '2.0',
            method,
            params
        };
        const json = JSON.stringify(notification);
        this.process.stdin.write(json + '\n');
    }
    rejectAllPending(error) {
        for (const [, pending] of this.pendingRequests) {
            clearTimeout(pending.timeout);
            pending.reject(error);
        }
        this.pendingRequests.clear();
        // Also reject queued requests
        for (const queuedRequest of this.requestQueue) {
            queuedRequest.reject(error);
        }
        this.requestQueue = [];
    }
    // ============================================
    // Tool Invocation
    // ============================================
    /**
     * Call an MCP tool by name
     */
    async callTool(toolName, args = {}) {
        if (!this.isConnected) {
            await this.connect();
        }
        const result = await this.sendRequest('tools/call', {
            name: toolName,
            arguments: args
        });
        // Parse the text content
        if (result.content && result.content.length > 0) {
            const textContent = result.content.find(c => c.type === 'text');
            if (textContent) {
                try {
                    return JSON.parse(textContent.text);
                }
                catch {
                    return textContent.text;
                }
            }
        }
        if (result.isError) {
            throw new Error('Tool returned an error');
        }
        return result;
    }
    /**
     * List available tools
     */
    async listTools() {
        if (!this.isConnected) {
            await this.connect();
        }
        const result = await this.sendRequest('tools/list', {});
        return result.tools;
    }
    // ============================================
    // Device Flow Authentication
    // ============================================
    /**
     * Initialize device authorization flow
     */
    async deviceInit(params = {}) {
        return this.callTool('auth.deviceInit', {
            client_id: params.clientId || 'guideai-vscode',
            scopes: params.scopes || ['actions:read', 'actions:write', 'behaviors:read']
        });
    }
    /**
     * Poll device authorization status
     */
    async devicePoll(params) {
        return this.callTool('auth.devicePoll', {
            device_code: params.deviceCode,
            client_id: params.clientId || 'guideai-vscode'
        });
    }
    /**
     * Refresh access token
     */
    async authRefresh(params) {
        return this.callTool('auth.refresh', {
            refresh_token: params.refreshToken,
            client_id: params.clientId || 'guideai-vscode'
        });
    }
    // ============================================
    // Consent Management
    // ============================================
    /**
     * Look up consent status by user code
     */
    async consentLookup(userCode) {
        return this.callTool('consent.lookup', {
            user_code: userCode
        });
    }
    /**
     * Approve consent request
     */
    async consentApprove(params) {
        return this.callTool('consent.approve', {
            user_code: params.userCode,
            scopes: params.scopes
        });
    }
    /**
     * Deny consent request
     */
    async consentDeny(params) {
        return this.callTool('consent.deny', {
            user_code: params.userCode,
            reason: params.reason
        });
    }
    // ============================================
    // Behaviors (example of migrating from CLI)
    // ============================================
    /**
     * Retrieve behaviors using BCI
     */
    async bciRetrieve(params) {
        return this.callTool('bci.retrieve', {
            query: params.query,
            top_k: params.topK || 5,
            strategy: params.strategy || 'hybrid',
            role_focus: params.roleFocus,
            tags: params.tags
        });
    }
    // ============================================
    // Amprealize Environment Orchestration
    // ============================================
    /**
     * Plan an amprealize environment from a blueprint
     */
    async amprealizePlan(params) {
        return this.callTool('amprealize.plan', {
            blueprint_id: params.blueprintId,
            environment: params.environment || 'development',
            checklist_id: params.checklistId,
            lifetime: params.lifetime || '90m',
            compliance_tier: params.complianceTier || 'dev',
            behaviors: params.behaviors,
            variables: params.variables
        });
    }
    /**
     * Apply an amprealize plan to create resources
     */
    async amprealizeApply(params) {
        return this.callTool('amprealize.apply', {
            plan_id: params.planId,
            manifest_file: params.manifestFile,
            watch: params.watch ?? false,
            resume: params.resume ?? false
        });
    }
    /**
     * Get status of an amprealize run
     */
    async amprealizeStatus(runId) {
        return this.callTool('amprealize.status', {
            run_id: runId
        });
    }
    /**
     * Destroy resources from an amprealize run
     */
    async amprealizeDestroy(params) {
        return this.callTool('amprealize.destroy', {
            run_id: params.runId,
            cascade: params.cascade ?? true,
            reason: params.reason || 'MANUAL'
        });
    }
    /**
     * List available blueprints
     */
    async amprealizeListBlueprints(params) {
        return this.callTool('amprealize.listBlueprints', {
            source: params?.source || 'all'
        });
    }
    /**
     * List active environments
     */
    async amprealizeListEnvironments(params) {
        return this.callTool('amprealize.listEnvironments', {
            phase: params?.phase || 'all'
        });
    }
    /**
     * Configure amprealize in a directory
     */
    async amprealizeConfigure(params) {
        return this.callTool('amprealize.configure', {
            config_dir: params?.configDir,
            include_blueprints: params?.includeBlueprints ?? false,
            blueprints: params?.blueprints,
            force: params?.force ?? false
        });
    }
    // ============================================
    // Action Registry (behavior_sanitize_action_registry)
    // ============================================
    /**
     * Record a new build action for reproducibility tracking
     */
    async actionCreate(params) {
        const config = vscode.workspace.getConfiguration('guideai');
        const actorId = config.get('telemetryActorId', 'vscode-user');
        const actorRole = config.get('telemetryActorRole', 'STUDENT');
        return this.callTool('actions.create', {
            artifact_path: params.artifactPath,
            summary: params.summary,
            behaviors_cited: params.behaviorsCited,
            metadata: params.metadata ? {
                commands: params.metadata.commands,
                validation_output: params.metadata.validationOutput,
                related_links: params.metadata.relatedLinks
            } : undefined,
            related_run_id: params.relatedRunId,
            checksum: params.checksum,
            tier: params.tier,
            actor: {
                id: params.actor?.id || actorId,
                role: params.actor?.role || actorRole,
                surface: 'MCP'
            }
        });
    }
    /**
     * List recorded build actions with optional filtering
     */
    async actionList(params) {
        const config = vscode.workspace.getConfiguration('guideai');
        const actorId = config.get('telemetryActorId', 'vscode-user');
        const actorRole = config.get('telemetryActorRole', 'STUDENT');
        return this.callTool('actions.list', {
            artifact_path_filter: params?.artifactPathFilter,
            behavior_id: params?.behaviorId,
            related_run_id: params?.relatedRunId,
            limit: params?.limit || 20,
            actor: {
                id: params?.actor?.id || actorId,
                role: params?.actor?.role || actorRole,
                surface: 'MCP'
            }
        });
    }
    /**
     * Get details of a specific action
     */
    async actionGet(actionId) {
        const config = vscode.workspace.getConfiguration('guideai');
        const actorId = config.get('telemetryActorId', 'vscode-user');
        const actorRole = config.get('telemetryActorRole', 'STUDENT');
        return this.callTool('actions.get', {
            action_id: actionId,
            actor: {
                id: actorId,
                role: actorRole,
                surface: 'MCP'
            }
        });
    }
    /**
     * Launch a replay job to reproduce one or more actions
     */
    async actionReplay(params) {
        const config = vscode.workspace.getConfiguration('guideai');
        const actorId = config.get('telemetryActorId', 'vscode-user');
        return this.callTool('actions.replay', {
            action_ids: params.actionIds,
            strategy: params.strategy || 'SEQUENTIAL',
            options: params.options ? {
                skip_existing: params.options.skipExisting ?? false,
                dry_run: params.options.dryRun ?? false
            } : undefined,
            tier: params.tier,
            actor: {
                id: actorId,
                role: 'STRATEGIST', // Replay requires STRATEGIST or ADMIN
                surface: 'MCP'
            }
        });
    }
    /**
     * Get status of a replay job
     */
    async actionReplayStatus(replayId) {
        const config = vscode.workspace.getConfiguration('guideai');
        const actorId = config.get('telemetryActorId', 'vscode-user');
        const actorRole = config.get('telemetryActorRole', 'STUDENT');
        return this.callTool('actions.replayStatus', {
            replay_id: replayId,
            actor: {
                id: actorId,
                role: actorRole,
                surface: 'MCP'
            }
        });
    }
    // ============================================
    // Lifecycle
    // ============================================
    dispose() {
        this.stopHeartbeat();
        this.disconnect();
        this.outputChannel.dispose();
    }
}
exports.McpClient = McpClient;
//# sourceMappingURL=McpClient.js.map
