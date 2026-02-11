"use strict";
/**
 * GuideAI VS Code Extension
 *
 * Complete IDE Integration including:
 * - Execution Tracker View (Epic 5.4)
 * - Compliance Review Panel (Epic 5.5)
 * - Authentication Flows (Epic 5.6)
 * - Settings Sync (Epic 5.7)
 * - Keyboard Shortcuts (Epic 5.8)
 * - VSIX Packaging (Epic 5.9)
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
exports.activate = activate;
exports.deactivate = deactivate;
const vscode = __importStar(require("vscode"));
const GuideAIClient_1 = require("./client/GuideAIClient");
const McpClient_1 = require("./client/McpClient");
const ExecutionTrackerDataProvider_1 = require("./providers/ExecutionTrackerDataProvider");
const ComplianceTreeDataProvider_1 = require("./providers/ComplianceTreeDataProvider");
const ActionTreeDataProvider_1 = require("./providers/ActionTreeDataProvider");
const CostTreeDataProvider_1 = require("./providers/CostTreeDataProvider");
const AuthProvider_1 = require("./providers/AuthProvider");
const SettingsSyncProvider_1 = require("./providers/SettingsSyncProvider");
const RunDetailPanel_1 = require("./panels/RunDetailPanel");
const ComplianceReviewPanel_1 = require("./panels/ComplianceReviewPanel");
const AmprealizePanel_1 = require("./panels/AmprealizePanel");
const ActionTimelinePanel_1 = require("./panels/ActionTimelinePanel");
const BehaviorAccuracyPanel_1 = require("./panels/BehaviorAccuracyPanel");
const GuideAIChatPanel_1 = require("./panels/GuideAIChatPanel");
const McpStatusBarProvider_1 = require("./providers/McpStatusBarProvider");
function activate(context) {
    console.log('GuideAI extension is now active');
    // Create output channel for extension logging
    const outputChannel = vscode.window.createOutputChannel('GuideAI Extension');
    outputChannel.appendLine('GuideAI extension activating...');
    try {
        // Initialize GuideAIClient
        const client = new GuideAIClient_1.GuideAIClient(context);
        // Initialize McpClient for MCP-based operations (behavior_prefer_mcp_tools)
        const mcpClient = new McpClient_1.McpClient(context);
        context.subscriptions.push({ dispose: () => mcpClient.dispose() });
        // Initialize MCP Status Bar Provider (Epic 6 - Connection Stability)
        const mcpStatusBarProvider = new McpStatusBarProvider_1.McpStatusBarProvider(mcpClient);
        context.subscriptions.push(mcpStatusBarProvider);
        // Register core commands early to avoid "command not found" if later init fails
        context.subscriptions.push(vscode.commands.registerCommand('guideai.openChat', () => {
            GuideAIChatPanel_1.GuideAIChatPanel.createOrShow(context.extensionUri, mcpClient);
        }), vscode.commands.registerCommand('guideai.mcp.showStatus', () => {
            mcpStatusBarProvider.showStatusQuickPick();
        }));
        // NOTE: Auto-connect disabled to prevent resource exhaustion
        // User must manually connect via command palette: "GuideAI: Connect to MCP Server"
        outputChannel.appendLine('GuideAI extension ready. Use "GuideAI: Connect to MCP Server" to connect.');
        // Register manual connect command
        context.subscriptions.push(vscode.commands.registerCommand('guideai.mcp.connect', async () => {
            try {
                outputChannel.appendLine('Connecting to MCP server...');
                await mcpClient.connect();
                outputChannel.appendLine('MCP client connected successfully');
                vscode.window.showInformationMessage('GuideAI MCP server connected');
            }
            catch (err) {
                const errorMsg = err instanceof Error ? err.message : String(err);
                outputChannel.appendLine(`Failed to connect MCP client: ${errorMsg}`);
                vscode.window.showErrorMessage(`GuideAI MCP connection failed: ${errorMsg}`);
            }
        }), vscode.commands.registerCommand('guideai.mcp.disconnect', () => {
            try {
                mcpClient.disconnect();
                outputChannel.appendLine('MCP client disconnected');
                vscode.window.showInformationMessage('GuideAI MCP server disconnected');
            }
            catch (err) {
                const errorMsg = err instanceof Error ? err.message : String(err);
                outputChannel.appendLine(`Failed to disconnect MCP client: ${errorMsg}`);
            }
        }));
        // Register tree data providers
        const executionTrackerProvider = new ExecutionTrackerDataProvider_1.ExecutionTrackerDataProvider(client);
        const complianceTrackerProvider = new ComplianceTreeDataProvider_1.ComplianceTreeDataProvider(client);
        const actionTrackerProvider = new ActionTreeDataProvider_1.ActionTreeDataProvider(mcpClient);
        const costTrackerProvider = new CostTreeDataProvider_1.CostTreeDataProvider(client);
        // Register authentication provider (Epic 5.6)
        const authProvider = new AuthProvider_1.AuthProvider(client, context, mcpClient);
        context.subscriptions.push(vscode.authentication.registerAuthenticationProvider('guideai', 'GuideAI', authProvider));
        // Register settings sync provider (Epic 5.7)
        const settingsSyncProvider = new SettingsSyncProvider_1.SettingsSyncProvider(context);
        context.subscriptions.push(vscode.workspace.registerFileSystemProvider('guideai-settings', settingsSyncProvider, { isCaseSensitive: true }));
        // Register tree views
        const executionTrackerView = vscode.window.registerTreeDataProvider('guideai.executionTracker', executionTrackerProvider);
        const complianceTrackerView = vscode.window.registerTreeDataProvider('guideai.complianceTracker', complianceTrackerProvider);
        const actionTrackerView = vscode.window.registerTreeDataProvider('guideai.actionTracker', actionTrackerProvider);
        const costTrackerView = vscode.window.registerTreeDataProvider('guideai.costTracker', costTrackerProvider);
        // Register commands
        const commands = [
            // Execution Tracker Commands (Epic 5.4)
            vscode.commands.registerCommand('guideai.refreshExecutionTracker', () => executionTrackerProvider.refresh()),
            vscode.commands.registerCommand('guideai.viewRunDetails', async (run) => {
                RunDetailPanel_1.RunDetailPanel.createOrShow(vscode.Uri.joinPath(context.extensionUri, 'src'), run);
            }),
            // Amprealize Orchestrator Commands (Epic 9.5)
            vscode.commands.registerCommand('guideai.openAmprealize', () => {
                AmprealizePanel_1.AmprealizePanel.createOrShow(context.extensionUri, client, mcpClient);
            }),
            // Compliance Tracker Commands (Epic 5.5)
            vscode.commands.registerCommand('guideai.refreshComplianceTracker', () => complianceTrackerProvider.refresh()),
            vscode.commands.registerCommand('guideai.openComplianceReview', async (checklist) => {
                ComplianceReviewPanel_1.ComplianceReviewPanel.createOrShow(vscode.Uri.joinPath(context.extensionUri, 'src'), client, checklist);
            }),
            vscode.commands.registerCommand('guideai.createComplianceChecklist', async () => {
                // TODO: Implement create compliance checklist
                vscode.window.showInformationMessage('Create compliance checklist - feature coming soon');
            }),
            // Authentication Commands (Epic 5.6)
            vscode.commands.registerCommand('guideai.auth.signIn', async () => {
                const session = await vscode.authentication.getSession('guideai', ['read', 'write'], { createIfNone: true });
                if (session) {
                    vscode.window.showInformationMessage(`Signed in as ${session.account.label}`);
                }
            }),
            vscode.commands.registerCommand('guideai.auth.signOut', async () => {
                // Note: Logout functionality depends on VS Code version
                vscode.window.showInformationMessage('Please use Settings > Accounts to sign out');
            }),
            vscode.commands.registerCommand('guideai.auth.status', async () => {
                const session = await vscode.authentication.getSession('guideai', ['read', 'write'], { createIfNone: false });
                if (session) {
                    vscode.window.showInformationMessage(`Signed in as ${session.account.label}`);
                }
                else {
                    vscode.window.showInformationMessage('Not signed in');
                }
            }),
            // Settings Sync Commands (Epic 5.7)
            vscode.commands.registerCommand('guideai.settings.sync', async () => {
                await settingsSyncProvider.syncSettings();
                vscode.window.showInformationMessage('Settings synchronized');
            }),
            vscode.commands.registerCommand('guideai.settings.export', async () => {
                await settingsSyncProvider.exportSettings();
            }),
            vscode.commands.registerCommand('guideai.settings.import', async () => {
                await settingsSyncProvider.importSettings();
            }),
            // Keyboard Shortcuts (Epic 5.8)
            vscode.commands.registerCommand('guideai.quickActions', async () => {
                const quickActions = [
                    'Refresh Execution Tracker',
                    'View Run Details',
                    'Open Compliance Review',
                    'Sync Settings',
                    'Sign In'
                ];
                const selected = await vscode.window.showQuickPick(quickActions, {
                    placeHolder: 'Select a GuideAI action'
                });
                if (selected) {
                    switch (selected) {
                        case 'Refresh Execution Tracker':
                            await executionTrackerProvider.refresh();
                            break;
                        case 'Sync Settings':
                            await settingsSyncProvider.syncSettings();
                            break;
                        case 'Sign In': {
                            const session = await vscode.authentication.getSession('guideai', ['read', 'write'], { createIfNone: true });
                            if (session) {
                                vscode.window.showInformationMessage(`Signed in as ${session.account.label}`);
                            }
                            break;
                        }
                    }
                }
            }),
            // General commands
            vscode.commands.registerCommand('guideai.showOutput', () => {
                client.dispose();
            }),
            // Context menu commands for tree view items
            vscode.commands.registerCommand('guideai.executionTracker.copyRunId', async (item) => {
                await vscode.env.clipboard.writeText(item.run.run_id);
                vscode.window.showInformationMessage('Run ID copied to clipboard');
            }),
            vscode.commands.registerCommand('guideai.executionTracker.refreshRun', async (item) => {
                await executionTrackerProvider.refresh();
            }),
            vscode.commands.registerCommand('guideai.complianceTracker.createChecklist', async () => {
                // TODO: Implement create checklist functionality
                vscode.window.showInformationMessage('Create checklist - feature coming soon');
            }),
            vscode.commands.registerCommand('guideai.complianceTracker.refreshChecklist', async (item) => {
                await complianceTrackerProvider.refresh();
            }),
            // Action Registry Commands (behavior_sanitize_action_registry)
            vscode.commands.registerCommand('guideai.refreshActionTracker', () => {
                actionTrackerProvider.refresh();
            }),
            vscode.commands.registerCommand('guideai.openActionTimeline', () => {
                ActionTimelinePanel_1.ActionTimelinePanel.createOrShow(context.extensionUri, mcpClient);
            }),
            vscode.commands.registerCommand('guideai.recordAction', async () => {
                // Quick action recording dialog
                const artifactPath = await vscode.window.showInputBox({
                    prompt: 'Artifact path (file, directory, or URL)',
                    placeHolder: 'e.g., src/services/ActionService.ts'
                });
                if (!artifactPath) {
                    return;
                }
                const summary = await vscode.window.showInputBox({
                    prompt: 'Action summary (max 160 chars)',
                    placeHolder: 'e.g., Added action replay functionality'
                });
                if (!summary) {
                    return;
                }
                const behaviorsInput = await vscode.window.showInputBox({
                    prompt: 'Behaviors cited (comma-separated)',
                    placeHolder: 'e.g., behavior_sanitize_action_registry, behavior_prefer_mcp_tools'
                });
                const behaviorsCited = behaviorsInput
                    ? behaviorsInput.split(',').map(b => b.trim()).filter(Boolean)
                    : [];
                try {
                    const result = await mcpClient.actionCreate({
                        artifactPath,
                        summary,
                        behaviorsCited
                    });
                    vscode.window.showInformationMessage(`Action recorded: ${result.action_id}`);
                    actionTrackerProvider.refresh();
                }
                catch (error) {
                    const errorMsg = error instanceof Error ? error.message : String(error);
                    vscode.window.showErrorMessage(`Failed to record action: ${errorMsg}`);
                }
            }),
            vscode.commands.registerCommand('guideai.listActions', async () => {
                try {
                    const result = await mcpClient.actionList({ limit: 20 });
                    if (result.actions.length === 0) {
                        vscode.window.showInformationMessage('No actions recorded yet');
                        return;
                    }
                    const items = result.actions.map(action => ({
                        label: action.summary,
                        description: action.artifact_path,
                        detail: `${action.timestamp} • ${action.behaviors_cited?.join(', ') || 'No behaviors'}`,
                        action
                    }));
                    const selected = await vscode.window.showQuickPick(items, {
                        placeHolder: 'Select an action to view details'
                    });
                    if (selected) {
                        ActionTimelinePanel_1.ActionTimelinePanel.createOrShow(context.extensionUri, mcpClient);
                    }
                }
                catch (error) {
                    const errorMsg = error instanceof Error ? error.message : String(error);
                    vscode.window.showErrorMessage(`Failed to list actions: ${errorMsg}`);
                }
            }),
            vscode.commands.registerCommand('guideai.replayAction', async (item) => {
                let actionId;
                if (item?.action) {
                    actionId = item.action.action_id;
                }
                else {
                    // Show quick pick to select action
                    try {
                        const result = await mcpClient.actionList({ limit: 50 });
                        if (result.actions.length === 0) {
                            vscode.window.showInformationMessage('No actions available to replay');
                            return;
                        }
                        const items = result.actions.map(action => ({
                            label: action.summary,
                            description: action.artifact_path,
                            detail: `Status: ${action.replay_status || 'NOT_STARTED'}`,
                            actionId: action.action_id
                        }));
                        const selected = await vscode.window.showQuickPick(items, {
                            placeHolder: 'Select an action to replay'
                        });
                        if (!selected) {
                            return;
                        }
                        actionId = selected.actionId;
                    }
                    catch (error) {
                        const errorMsg = error instanceof Error ? error.message : String(error);
                        vscode.window.showErrorMessage(`Failed to load actions: ${errorMsg}`);
                        return;
                    }
                }
                if (!actionId) {
                    return;
                }
                // Ask about dry run
                const dryRun = await vscode.window.showQuickPick([
                    { label: '▶ Execute Replay', description: 'Run the replay and apply changes', dryRun: false },
                    { label: '🔍 Dry Run', description: 'Simulate replay without making changes', dryRun: true }
                ], { placeHolder: 'Select replay mode' });
                if (!dryRun) {
                    return;
                }
                try {
                    const result = await mcpClient.actionReplay({
                        actionIds: [actionId],
                        strategy: 'SEQUENTIAL',
                        options: { dryRun: dryRun.dryRun }
                    });
                    vscode.window.showInformationMessage(dryRun.dryRun
                        ? `Dry run started: ${result.replay_id}`
                        : `Replay started: ${result.replay_id}`);
                    // Refresh action tracker to show updated status
                    actionTrackerProvider.refresh();
                }
                catch (error) {
                    const errorMsg = error instanceof Error ? error.message : String(error);
                    vscode.window.showErrorMessage(`Failed to start replay: ${errorMsg}`);
                }
            }),
            vscode.commands.registerCommand('guideai.viewActionDetail', async (item) => {
                if (!item?.action) {
                    return;
                }
                // Open action timeline and select this action
                ActionTimelinePanel_1.ActionTimelinePanel.createOrShow(context.extensionUri, mcpClient);
            }),
            vscode.commands.registerCommand('guideai.actionTracker.copyActionId', async (item) => {
                if (item?.action?.action_id) {
                    await vscode.env.clipboard.writeText(item.action.action_id);
                    vscode.window.showInformationMessage('Action ID copied to clipboard');
                }
            }),
            vscode.commands.registerCommand('guideai.actionTracker.filterByBehavior', async () => {
                const behaviorId = await vscode.window.showInputBox({
                    prompt: 'Filter by behavior ID',
                    placeHolder: 'e.g., behavior_sanitize_action_registry'
                });
                if (behaviorId) {
                    actionTrackerProvider.filterByBehavior(behaviorId);
                }
            }),
            vscode.commands.registerCommand('guideai.actionTracker.clearFilters', () => {
                actionTrackerProvider.clearFilters();
            }),
            // Cost Analytics Commands
            vscode.commands.registerCommand('guideai.refreshCostTracker', () => {
                costTrackerProvider.refresh();
            }),
            vscode.commands.registerCommand('guideai.costTracker.setPeriod7d', () => {
                costTrackerProvider.setPeriod(7);
                vscode.window.showInformationMessage('Cost analytics: showing last 7 days');
            }),
            vscode.commands.registerCommand('guideai.costTracker.setPeriod30d', () => {
                costTrackerProvider.setPeriod(30);
                vscode.window.showInformationMessage('Cost analytics: showing last 30 days');
            }),
            vscode.commands.registerCommand('guideai.costTracker.setPeriod90d', () => {
                costTrackerProvider.setPeriod(90);
                vscode.window.showInformationMessage('Cost analytics: showing last 90 days');
            }),
            // Behavior Accuracy Commands (behavior_curate_behavior_handbook)
            vscode.commands.registerCommand('guideai.openBehaviorAccuracy', () => {
                BehaviorAccuracyPanel_1.BehaviorAccuracyPanel.createOrShow(client, context.extensionUri);
            }),
            vscode.commands.registerCommand('guideai.submitBehaviorFeedback', async () => {
                // Quick feedback submission
                const behaviorId = await vscode.window.showInputBox({
                    prompt: 'Behavior ID',
                    placeHolder: 'e.g., behavior_prefer_mcp_tools'
                });
                if (!behaviorId) {
                    return;
                }
                const helpful = await vscode.window.showQuickPick([
                    { label: '👍 Yes, helpful', value: true },
                    { label: '👎 No, not helpful', value: false }
                ], { placeHolder: 'Was this behavior helpful?' });
                if (!helpful) {
                    return;
                }
                const rating = await vscode.window.showQuickPick(['1', '2', '3', '4', '5'], { placeHolder: 'Accuracy rating (1-5)' });
                if (!rating) {
                    return;
                }
                try {
                    await client.runCLI([
                        'behaviors', 'submit-feedback',
                        '--behavior-id', behaviorId,
                        '--helpful', helpful.value ? 'true' : 'false',
                        '--rating', rating
                    ]);
                    vscode.window.showInformationMessage('Feedback submitted successfully');
                }
                catch (error) {
                    vscode.window.showErrorMessage(`Failed to submit feedback: ${error}`);
                }
            })
        ];
        // Add all commands to subscriptions
        context.subscriptions.push(client, authProvider, settingsSyncProvider, executionTrackerProvider, complianceTrackerProvider, actionTrackerProvider, costTrackerProvider, executionTrackerView, complianceTrackerView, actionTrackerView, costTrackerView, mcpStatusBarProvider, ...commands);
    }
    catch (error) {
        const errorMsg = error instanceof Error ? error.message : String(error);
        outputChannel.appendLine(`Activation error: ${errorMsg}`);
        console.error('GuideAI extension activation failed:', error);
        vscode.window.showErrorMessage(`GuideAI extension activation failed: ${errorMsg}`);
    }
    // Show welcome message
    vscode.window.showInformationMessage('GuideAI IDE Integration complete! All features available: Execution Tracker, Compliance Review, Auth, Settings Sync.');
}
// This method is called when your extension is deactivated
function deactivate() {
    console.log('GuideAI extension is now deactivated');
}
//# sourceMappingURL=extension.js.map
