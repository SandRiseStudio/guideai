/**
 * Project Settings Panel
 *
 * Webview panel for configuring project settings:
 * - Local project path (with workspace auto-detection)
 * - GitHub repository URL
 * - GitHub branch selection
 * - Execution mode (local, github_pr, local_and_pr)
 * - GitHub Credential linking (per-user)
 */
import * as vscode from 'vscode';
import { GuideAIClient, ProjectSettings as ClientProjectSettings, LLMCredential as ClientLLMCredential } from '../client/GuideAIClient';
export type ExecutionMode = 'local' | 'github_pr' | 'local_and_pr';
export interface ProjectSettings extends ClientProjectSettings {
    project_id?: string;
    local_path?: string;
    github_branch?: string;
    execution_mode?: ExecutionMode;
}
export interface GitHubValidationResult {
    valid: boolean;
    repo_name?: string;
    default_branch?: string;
    branches?: string[];
    error?: string;
}
export type LLMCredential = ClientLLMCredential;
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
    private _credentials;
    private _githubLink;
    private _githubResolution;
    private _myGitHubCredentials;
    private _myGitHubAppInstallations;
    private constructor();
    static createOrShow(extensionUri: vscode.Uri, client: GuideAIClient, projectId: string, projectName?: string): void;
    static revive(panel: vscode.WebviewPanel, extensionUri: vscode.Uri, client: GuideAIClient, projectId: string): void;
    private _loadSettings;
    private _detectWorkspace;
    private _validateGithub;
    private _saveSettings;
    private _addCredential;
    private _deleteCredential;
    private _reEnableCredential;
    private _linkGitHubPAT;
    private _linkGitHubApp;
    private _unlinkGitHub;
    private _update;
    private _renderGitHubResolutionStatus;
    private _renderGitHubLinkSection;
    private _getHtmlForWebview;
    dispose(): void;
}
//# sourceMappingURL=ProjectSettingsPanel.d.ts.map
