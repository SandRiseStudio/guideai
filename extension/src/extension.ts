/**
 * GuideAI VS Code Extension
 *
 * Brings behavior-conditioned inference to the IDE:
 * - Behavior Sidebar: Browse and search the behavior handbook
 * - Plan Composer: Create workflows using Strategist/Teacher/Student templates
 * - Execution Tracker: Monitor workflow runs (future)
 * - Compliance Review: Capture evidence and validate checklists (future)
 */

import * as vscode from 'vscode';
import { BehaviorTreeDataProvider } from './providers/BehaviorTreeDataProvider';
import { WorkflowTreeDataProvider } from './providers/WorkflowTreeDataProvider';
import { GuideAIClient } from './client/GuideAIClient';
import { BehaviorDetailPanel } from './webviews/BehaviorDetailPanel';
import { PlanComposerPanel } from './webviews/PlanComposerPanel';

export function activate(context: vscode.ExtensionContext) {
	console.log('GuideAI extension is now active');

	// Initialize client for Python backend communication
	const client = new GuideAIClient(context);

	// Register Behavior Sidebar TreeView
	const behaviorProvider = new BehaviorTreeDataProvider(client);
	const behaviorTreeView = vscode.window.createTreeView('guideai.behaviorSidebar', {
		treeDataProvider: behaviorProvider,
		showCollapseAll: true
	});

	// Register Workflow Explorer TreeView
	const workflowProvider = new WorkflowTreeDataProvider(client);
	const workflowTreeView = vscode.window.createTreeView('guideai.workflowExplorer', {
		treeDataProvider: workflowProvider,
		showCollapseAll: true
	});

	// Command: Refresh Behaviors
	context.subscriptions.push(
		vscode.commands.registerCommand('guideai.refreshBehaviors', () => {
			behaviorProvider.refresh();
			vscode.window.showInformationMessage('GuideAI: Behaviors refreshed');
		})
	);

	// Command: Search Behaviors
	context.subscriptions.push(
		vscode.commands.registerCommand('guideai.searchBehaviors', async () => {
			const query = await vscode.window.showInputBox({
				prompt: 'Enter search query for behaviors',
				placeHolder: 'e.g., "handle API errors", "validate input", etc.'
			});
			if (query) {
				await behaviorProvider.search(query);
			}
		})
	);

	// Command: View Behavior Detail
	context.subscriptions.push(
		vscode.commands.registerCommand('guideai.viewBehaviorDetail', async (behaviorItem: any) => {
			await BehaviorDetailPanel.createOrShow(context.extensionUri, client, behaviorItem.behavior);
		})
	);

	// Command: Insert Behavior Reference
	context.subscriptions.push(
		vscode.commands.registerCommand('guideai.insertBehavior', async (behaviorItem: any) => {
			const editor = vscode.window.activeTextEditor;
			if (!editor) {
				vscode.window.showWarningMessage('No active editor found');
				return;
			}

			const behavior = behaviorItem.behavior;
			const reference = `# Behavior: ${behavior.name}\n# ${behavior.description}\n# ID: ${behavior.behavior_id}\n`;

			editor.edit(editBuilder => {
				editBuilder.insert(editor.selection.active, reference);
			});

			vscode.window.showInformationMessage(`Inserted behavior: ${behavior.name}`);
		})
	);

	// Command: Open Plan Composer
	context.subscriptions.push(
		vscode.commands.registerCommand('guideai.openPlanComposer', async () => {
			await PlanComposerPanel.createOrShow(context.extensionUri, client);
		})
	);

	// Command: Create Workflow from Template
	context.subscriptions.push(
		vscode.commands.registerCommand('guideai.createWorkflow', async (workflowItem: any) => {
			await PlanComposerPanel.createOrShow(context.extensionUri, client, workflowItem.template);
		})
	);

	// Command: Run Workflow
	context.subscriptions.push(
		vscode.commands.registerCommand('guideai.runWorkflow', async (workflowItem: any) => {
			const result = await vscode.window.showInformationMessage(
				`Run workflow: ${workflowItem.template.name}?`,
				'Run', 'Cancel'
			);

			if (result === 'Run') {
				vscode.window.withProgress({
					location: vscode.ProgressLocation.Notification,
					title: `Running workflow: ${workflowItem.template.name}`,
					cancellable: false
				}, async (progress) => {
					try {
						progress.report({ message: 'Starting workflow...' });
						const runResult = await client.runWorkflow(workflowItem.template.template_id);

						progress.report({ message: 'Workflow started', increment: 100 });
						vscode.window.showInformationMessage(
							`Workflow started: ${runResult.run_id}. Check output panel for progress.`
						);
					} catch (error) {
						vscode.window.showErrorMessage(`Failed to run workflow: ${error}`);
					}
				});
			}
		})
	);

	// Register webview panels
	context.subscriptions.push(behaviorTreeView, workflowTreeView);

	// Show welcome message on first activation
	const hasShownWelcome = context.globalState.get<boolean>('guideai.hasShownWelcome');
	if (!hasShownWelcome) {
		vscode.window.showInformationMessage(
			'Welcome to GuideAI! Browse behaviors in the sidebar or open the Plan Composer to get started.',
			'Open Sidebar', 'Open Composer'
		).then(selection => {
			if (selection === 'Open Sidebar') {
				vscode.commands.executeCommand('guideai.behaviorSidebar.focus');
			} else if (selection === 'Open Composer') {
				vscode.commands.executeCommand('guideai.openPlanComposer');
			}
		});
		context.globalState.update('guideai.hasShownWelcome', true);
	}
}

export function deactivate() {
	console.log('GuideAI extension is now deactivated');
}
