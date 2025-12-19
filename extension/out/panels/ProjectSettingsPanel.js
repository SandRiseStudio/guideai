"use strict";
/**
 * Project Settings Panel
 *
 * Webview panel for configuring project settings:
 * - Local project path (with workspace auto-detection)
 * - GitHub repository URL
 * - GitHub branch selection
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
exports.ProjectSettingsPanel = void 0;
const vscode = __importStar(require("vscode"));
class ProjectSettingsPanel {
    constructor(panel, extensionUri, client, projectId) {
        this._disposables = [];
        this._settings = null;
        this._validatedGithub = null;
        this._panel = panel;
        this._extensionUri = extensionUri;
        this._client = client;
        this._projectId = projectId;
        this._update();
        this._panel.onDidDispose(() => this.dispose(), null, this._disposables);
        this._panel.webview.onDidReceiveMessage(async (message) => {
            switch (message.type) {
                case 'detectWorkspace':
                    await this._detectWorkspace();
                    return;
                case 'validateGithub':
                    await this._validateGithub(message.url);
                    return;
                case 'saveSettings':
                    await this._saveSettings(message.settings);
                    return;
                case 'refresh':
                    await this._loadSettings();
                    return;
            }
        }, null, this._disposables);
        // Load settings on init
        void this._loadSettings();
    }
    static createOrShow(extensionUri, client, projectId, projectName) {
        const column = vscode.ViewColumn.One;
        if (ProjectSettingsPanel.currentPanel) {
            ProjectSettingsPanel.currentPanel._panel.reveal(column);
            ProjectSettingsPanel.currentPanel._projectId = projectId;
            void ProjectSettingsPanel.currentPanel._loadSettings();
            return;
        }
        const panel = vscode.window.createWebviewPanel(ProjectSettingsPanel.viewType, `Settings: ${projectName || 'Project'}`, column || vscode.ViewColumn.One, {
            enableScripts: true,
            localResourceRoots: [
                vscode.Uri.joinPath(extensionUri, 'out'),
                vscode.Uri.joinPath(extensionUri, 'src', 'styles')
            ]
        });
        ProjectSettingsPanel.currentPanel = new ProjectSettingsPanel(panel, extensionUri, client, projectId);
    }
    static revive(panel, extensionUri, client, projectId) {
        ProjectSettingsPanel.currentPanel = new ProjectSettingsPanel(panel, extensionUri, client, projectId);
    }
    async _loadSettings() {
        try {
            this._settings = await this._client.getProjectSettings(this._projectId);
            this._update();
        }
        catch (error) {
            console.error('Failed to load project settings:', error);
            vscode.window.showErrorMessage(`Failed to load settings: ${error}`);
        }
    }
    async _detectWorkspace() {
        const workspaceFolders = vscode.workspace.workspaceFolders;
        if (!workspaceFolders || workspaceFolders.length === 0) {
            vscode.window.showWarningMessage('No workspace folder is currently open.');
            return;
        }
        if (workspaceFolders.length === 1) {
            // Single workspace - use it directly
            const localPath = workspaceFolders[0].uri.fsPath;
            this._panel.webview.postMessage({
                type: 'workspaceDetected',
                path: localPath
            });
        }
        else {
            // Multiple workspaces - let user pick
            const items = workspaceFolders.map(folder => ({
                label: folder.name,
                description: folder.uri.fsPath,
                path: folder.uri.fsPath
            }));
            const selected = await vscode.window.showQuickPick(items, {
                placeHolder: 'Select a workspace folder',
                title: 'Choose Project Location'
            });
            if (selected) {
                this._panel.webview.postMessage({
                    type: 'workspaceDetected',
                    path: selected.path
                });
            }
        }
    }
    async _validateGithub(url) {
        try {
            this._panel.webview.postMessage({
                type: 'validationStarted'
            });
            const result = await this._client.validateGithubRepo(this._projectId, url);
            this._validatedGithub = result;
            this._panel.webview.postMessage({
                type: 'validationResult',
                result
            });
            if (result.valid) {
                vscode.window.showInformationMessage(`Repository validated: ${result.repo_name}`);
            }
            else {
                vscode.window.showWarningMessage(result.error || 'Failed to validate repository');
            }
        }
        catch (error) {
            console.error('GitHub validation failed:', error);
            this._panel.webview.postMessage({
                type: 'validationResult',
                result: { valid: false, error: String(error) }
            });
            vscode.window.showErrorMessage(`Validation failed: ${error}`);
        }
    }
    async _saveSettings(settings) {
        try {
            await this._client.updateProjectSettings(this._projectId, settings);
            vscode.window.showInformationMessage('Project settings saved successfully');
            await this._loadSettings();
        }
        catch (error) {
            console.error('Failed to save settings:', error);
            vscode.window.showErrorMessage(`Failed to save settings: ${error}`);
        }
    }
    _update() {
        this._panel.webview.html = this._getHtmlForWebview();
    }
    _getHtmlForWebview() {
        const webview = this._panel.webview;
        const styleResetUri = webview.asWebviewUri(vscode.Uri.joinPath(this._extensionUri, 'out', 'viewExplorer.css'));
        const styleMainUri = webview.asWebviewUri(vscode.Uri.joinPath(this._extensionUri, 'src', 'styles', 'ProjectSettingsPanel.css'));
        const nonce = getNonce();
        const settings = this._settings;
        const localPath = settings?.local_path || '';
        const githubRepo = settings?.github_repo || '';
        const githubBranch = settings?.github_branch || '';
        // Generate branch options if we have validated github
        let branchOptions = '';
        if (this._validatedGithub?.branches) {
            branchOptions = this._validatedGithub.branches
                .map(b => `<option value="${b}" ${b === githubBranch ? 'selected' : ''}>${b}</option>`)
                .join('');
        }
        else if (githubBranch) {
            branchOptions = `<option value="${githubBranch}" selected>${githubBranch}</option>`;
        }
        return `<!DOCTYPE html>
<html lang="en">
<head>
	<meta charset="UTF-8">
	<meta name="viewport" content="width=device-width, initial-scale=1.0">
	<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src ${webview.cspSource}; script-src 'nonce-${nonce}';">
	<link href="${styleResetUri}" rel="stylesheet">
	<link href="${styleMainUri}" rel="stylesheet">
	<title>Project Settings</title>
</head>
<body>
	<div class="container">
		<header class="panel-header">
			<h1>Project Settings</h1>
			<p class="subtitle">${settings?.name || 'Configure your project'}</p>
		</header>

		<section class="settings-section">
			<h2>Local Path</h2>
			<p class="section-description">
				Path to your project folder on this machine. Used for IDE integrations.
			</p>
			<div class="input-group">
				<input
					type="text"
					id="localPath"
					class="text-input"
					value="${escapeHtml(localPath)}"
					placeholder="/path/to/your/project"
				/>
				<button class="secondary-btn" id="detectBtn">
					Detect Workspace
				</button>
			</div>
		</section>

		<section class="settings-section">
			<h2>GitHub Repository</h2>
			<p class="section-description">
				Link this project to a GitHub repository for enhanced collaboration features.
			</p>
			<div class="input-group">
				<input
					type="text"
					id="githubRepo"
					class="text-input"
					value="${escapeHtml(githubRepo)}"
					placeholder="https://github.com/owner/repo"
				/>
				<button class="secondary-btn" id="validateBtn">
					Validate
				</button>
			</div>
			<div id="validationStatus" class="validation-status"></div>

			<div class="branch-section ${branchOptions ? '' : 'hidden'}" id="branchSection">
				<label for="githubBranch" class="field-label">Default Branch</label>
				<select id="githubBranch" class="select-input">
					<option value="">Select a branch</option>
					${branchOptions}
				</select>
			</div>
		</section>

		<div class="actions">
			<button class="primary-btn" id="saveBtn">Save Settings</button>
		</div>
	</div>

	<script nonce="${nonce}">
		(function() {
			const vscode = acquireVsCodeApi();

			const localPathInput = document.getElementById('localPath');
			const githubRepoInput = document.getElementById('githubRepo');
			const githubBranchSelect = document.getElementById('githubBranch');
			const detectBtn = document.getElementById('detectBtn');
			const validateBtn = document.getElementById('validateBtn');
			const saveBtn = document.getElementById('saveBtn');
			const validationStatus = document.getElementById('validationStatus');
			const branchSection = document.getElementById('branchSection');

			detectBtn.addEventListener('click', () => {
				vscode.postMessage({ type: 'detectWorkspace' });
			});

			validateBtn.addEventListener('click', () => {
				const url = githubRepoInput.value.trim();
				if (url) {
					vscode.postMessage({ type: 'validateGithub', url });
				}
			});

			saveBtn.addEventListener('click', () => {
				vscode.postMessage({
					type: 'saveSettings',
					settings: {
						local_path: localPathInput.value.trim() || null,
						github_repo: githubRepoInput.value.trim() || null,
						github_branch: githubBranchSelect.value || null
					}
				});
			});

			window.addEventListener('message', event => {
				const message = event.data;
				switch (message.type) {
					case 'workspaceDetected':
						localPathInput.value = message.path;
						break;
					case 'validationStarted':
						validationStatus.textContent = 'Validating...';
						validationStatus.className = 'validation-status loading';
						break;
					case 'validationResult':
						if (message.result.valid) {
							validationStatus.textContent = '✓ Repository validated: ' + message.result.repo_name;
							validationStatus.className = 'validation-status success';

							if (message.result.branches && message.result.branches.length > 0) {
								branchSection.classList.remove('hidden');
								githubBranchSelect.innerHTML = '<option value="">Select a branch</option>' +
									message.result.branches.map(b =>
										'<option value="' + b + '"' +
										(b === message.result.default_branch ? ' selected' : '') +
										'>' + b + '</option>'
									).join('');
							}
						} else {
							validationStatus.textContent = '✗ ' + (message.result.error || 'Validation failed');
							validationStatus.className = 'validation-status error';
							branchSection.classList.add('hidden');
						}
						break;
				}
			});
		})();
	</script>
</body>
</html>`;
    }
    dispose() {
        ProjectSettingsPanel.currentPanel = undefined;
        this._panel.dispose();
        while (this._disposables.length) {
            const x = this._disposables.pop();
            if (x) {
                x.dispose();
            }
        }
    }
}
exports.ProjectSettingsPanel = ProjectSettingsPanel;
ProjectSettingsPanel.viewType = 'guideai.projectSettings';
function getNonce() {
    let text = '';
    const possible = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
    for (let i = 0; i < 32; i++) {
        text += possible.charAt(Math.floor(Math.random() * possible.length));
    }
    return text;
}
function escapeHtml(unsafe) {
    return unsafe
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}
//# sourceMappingURL=ProjectSettingsPanel.js.map
