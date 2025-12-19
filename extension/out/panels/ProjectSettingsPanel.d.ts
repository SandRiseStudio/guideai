/**
 * Project Settings Panel
 *
 * Webview panel for configuring project settings:
 * - Local project path (with workspace auto-detection)
 * - GitHub repository URL
 * - GitHub branch selection
 */
import * as vscode from 'vscode';
import { GuideAIClient } from '../client/GuideAIClient';
export interface ProjectSettings {
    project_id: string;
    name: string;
    local_path?: string;
    github_repo?: string;
    github_branch?: string;
}
export interface GitHubValidationResult {
    valid: boolean;
    repo_name?: string;
    default_branch?: string;
    branches?: string[];
    error?: string;
}
export declare class ProjectSettingsPanel {
    static currentPanel: ProjectSettingsPanel | undefined;
    static readonly viewType = "guideai.projectSettings";
    private readonly _panel;
    private readonly _extensionUri;
    private readonly _client;
    private _disposables;
    private _projectId;
    private _settings;
    private _validatedGithub;
    private constructor();
    static createOrShow(extensionUri: vscode.Uri, client: GuideAIClient, projectId: string, projectName?: string): void;
    static revive(panel: vscode.WebviewPanel, extensionUri: vscode.Uri, client: GuideAIClient, projectId: string): void;
    private _loadSettings;
    private _detectWorkspace;
    private _validateGithub;
    private _saveSettings;
    private _update;
    private _getHtmlForWebview;
    dispose(): void;
}
//# sourceMappingURL=ProjectSettingsPanel.d.ts.map
