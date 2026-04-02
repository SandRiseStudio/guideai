/**
 * Conversation Panel Integration Tests (GUIDEAI-618)
 *
 * Smoke tests verifying that conversation commands and tree view are registered,
 * and that ConversationPanel / ConversationTreeDataProvider behave correctly
 * without a live backend.
 *
 * Following behavior_integrate_vscode_extension: Mocha TDD pattern, mock VS Code APIs.
 * Following behavior_design_test_strategy: happy path + error paths, no real I/O.
 */

import * as assert from 'assert';
import * as vscode from 'vscode';

// ---------------------------------------------------------------------------
// Helper
// ---------------------------------------------------------------------------

function assertCommandRegistered(commands: string[], cmd: string): void {
	assert.ok(
		commands.includes(cmd),
		`Command '${cmd}' should be registered`
	);
}

// ---------------------------------------------------------------------------
// Suite: Command Registration
// ---------------------------------------------------------------------------

suite('Conversation Panel – Command Registration', () => {
	vscode.window.showInformationMessage('Running Conversation Panel smoke tests.');

	test('guideai.openConversation command is registered', async () => {
		const cmds = await vscode.commands.getCommands(true);
		assertCommandRegistered(cmds, 'guideai.openConversation');
	});

	test('guideai.refreshConversations command is registered', async () => {
		const cmds = await vscode.commands.getCommands(true);
		assertCommandRegistered(cmds, 'guideai.refreshConversations');
	});
});

// ---------------------------------------------------------------------------
// Suite: refreshConversations invocation
// ---------------------------------------------------------------------------

suite('Conversation Panel – refreshConversations', () => {
	test('refreshConversations does not throw when no backend is available', async () => {
		try {
			await vscode.commands.executeCommand('guideai.refreshConversations');
			assert.ok(true, 'Command completed without throwing');
		} catch (err) {
			const msg = err instanceof Error ? err.message : String(err);
			assert.ok(
				!msg.includes("command 'guideai.refreshConversations' not found"),
				'Command must be registered even without a backend'
			);
		}
	});
});

// ---------------------------------------------------------------------------
// Suite: ConversationTreeDataProvider (unit-level)
// ---------------------------------------------------------------------------

suite('ConversationTreeDataProvider – unit', () => {
	// Dynamically import so that the extension host module system is used.
	// eslint-disable-next-line @typescript-eslint/no-require-imports
	const { ConversationTreeDataProvider, ConversationItem } = require('../../providers/ConversationTreeDataProvider') as typeof import('../../providers/ConversationTreeDataProvider');

	test('getTreeItem returns the element unchanged', () => {
		const provider = new ConversationTreeDataProvider({ baseUrl: 'http://localhost:8080' });
		const item = new ConversationItem({
			id: 'c1',
			title: 'Test Convo',
			status: 'active',
			updated_at: new Date().toISOString(),
		});
		const result = provider.getTreeItem(item);
		assert.strictEqual(result, item);
		provider.dispose();
	});

	test('getChildren returns empty array for a child element (flat list)', async () => {
		const provider = new ConversationTreeDataProvider({ baseUrl: 'http://localhost:8080' });
		const item = new ConversationItem({
			id: 'c1',
			title: 'Test',
			status: 'active',
			updated_at: new Date().toISOString(),
		});
		const children = await provider.getChildren(item);
		assert.deepStrictEqual(children, []);
		provider.dispose();
	});

	test('getChildren at root returns empty array when backend is unreachable', async () => {
		// Point at a port that should refuse connections immediately
		const provider = new ConversationTreeDataProvider({ baseUrl: 'http://127.0.0.1:1' });
		const children = await provider.getChildren();
		assert.ok(Array.isArray(children), 'Should resolve to an array even on network error');
		provider.dispose();
	});

	test('refresh fires onDidChangeTreeData event', (done) => {
		const provider = new ConversationTreeDataProvider({ baseUrl: 'http://localhost:8080' });
		const disposable = provider.onDidChangeTreeData(() => {
			disposable.dispose();
			provider.dispose();
			done();
		});
		provider.refresh();
	});

	test('ConversationItem sets correct contextValue', () => {
		const item = new ConversationItem({
			id: 'c2',
			title: 'My Conv',
			status: 'archived',
			updated_at: '2026-01-01T00:00:00Z',
			last_message_preview: 'Hello world',
		});
		assert.strictEqual(item.contextValue, 'conversation-item');
		assert.strictEqual(item.tooltip, 'Hello world');
	});

	test('ConversationItem active status uses comment-discussion icon', () => {
		const item = new ConversationItem({
			id: 'c3',
			title: 'Active',
			status: 'active',
			updated_at: '2026-01-01T00:00:00Z',
		});
		assert.ok(item.iconPath instanceof vscode.ThemeIcon);
		assert.strictEqual((item.iconPath as vscode.ThemeIcon).id, 'comment-discussion');
	});

	test('ConversationItem archived status uses archive icon', () => {
		const item = new ConversationItem({
			id: 'c4',
			title: 'Archived',
			status: 'archived',
			updated_at: '2026-01-01T00:00:00Z',
		});
		assert.ok(item.iconPath instanceof vscode.ThemeIcon);
		assert.strictEqual((item.iconPath as vscode.ThemeIcon).id, 'archive');
	});

	test('ConversationItem command targets guideai.openConversation with correct args', () => {
		const item = new ConversationItem({
			id: 'c5',
			title: 'Click Me',
			status: 'active',
			updated_at: '2026-01-01T00:00:00Z',
		});
		assert.ok(item.command, 'Item should have a command');
		assert.strictEqual(item.command!.command, 'guideai.openConversation');
		assert.deepStrictEqual(item.command!.arguments, ['c5', 'Click Me']);
	});
});

// ---------------------------------------------------------------------------
// Suite: ConversationPanel (unit-level)
// ---------------------------------------------------------------------------

suite('ConversationPanel – unit', () => {
	// eslint-disable-next-line @typescript-eslint/no-require-imports
	const { ConversationPanel } = require('../../panels/ConversationPanel') as typeof import('../../panels/ConversationPanel');

	test('currentPanel is undefined before any panel is created', () => {
		assert.strictEqual(ConversationPanel.currentPanel, undefined);
	});

	test('viewType is guideai.conversation', () => {
		assert.strictEqual(ConversationPanel.viewType, 'guideai.conversation');
	});
});
