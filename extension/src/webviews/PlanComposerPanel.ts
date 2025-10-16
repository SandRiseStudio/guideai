import * as vscode from 'vscode';
import { GuideAIClient, WorkflowTemplate, Behavior } from '../client/GuideAIClient';

export class PlanComposerPanel {
    public static currentPanel: PlanComposerPanel | undefined;
    private readonly _panel: vscode.WebviewPanel;
    private _disposables: vscode.Disposable[] = [];
    private workflows: WorkflowTemplate[] = [];
    private behaviors: Behavior[] = [];

    private constructor(
        panel: vscode.WebviewPanel,
        private client: GuideAIClient,
        private templateId?: string
    ) {
        this._panel = panel;
        this._panel.onDidDispose(() => this.dispose(), null, this._disposables);
        this._panel.webview.onDidReceiveMessage(
            message => this.handleMessage(message),
            null,
            this._disposables
        );
        this.initialize();
    }

    public static async createOrShow(extensionUri: vscode.Uri, client: GuideAIClient, template?: any): Promise<void> {
        const templateId = template?.template_id || template;
        const column = vscode.window.activeTextEditor
            ? vscode.window.activeTextEditor.viewColumn
            : undefined;

        // If panel exists, reveal it
        if (PlanComposerPanel.currentPanel) {
            PlanComposerPanel.currentPanel._panel.reveal(column);
            if (templateId) {
                PlanComposerPanel.currentPanel.templateId = templateId;
                PlanComposerPanel.currentPanel.initialize();
            }
            return;
        }

        // Create new panel
        const panel = vscode.window.createWebviewPanel(
            'planComposer',
            'Plan Composer',
            column || vscode.ViewColumn.One,
            {
                enableScripts: true,
                retainContextWhenHidden: true
            }
        );

        PlanComposerPanel.currentPanel = new PlanComposerPanel(panel, client, templateId);
        void client.emitTelemetry('plan_composer_opened', {
            source: 'plan_composer.open',
            template_id: templateId || null
        }).catch(() => undefined);
    }

    private async initialize(): Promise<void> {
        this._panel.webview.html = '<p>Loading composer...</p>';

        try {
            // Load workflows and behaviors
            this.workflows = await this.client.listWorkflowTemplates(undefined, { source: 'plan_composer.load_workflows' });
            this.behaviors = await this.client.listBehaviors({}, { source: 'plan_composer.load_behaviors' });

            this._panel.webview.html = this.getWebviewContent();
            this.emitTelemetry('plan_composer_loaded', {
                template_id: this.templateId || null,
                workflow_template_count: this.workflows.length,
                behavior_count: this.behaviors.length
            });
        } catch (error) {
            this._panel.webview.html = `<p style="color: red;">Error loading composer: ${error}</p>`;
            this.emitTelemetry('plan_composer_load_failed', {
                template_id: this.templateId || null,
                error: error instanceof Error ? error.message : String(error)
            });
        }
    }

    private getWebviewContent(): string {
        const workflowOptions = this.workflows.map(w =>
            `<option value="${w.template_id}" ${w.template_id === this.templateId ? 'selected' : ''}>
                ${this.escapeHtml(w.name)} (${w.role_focus || w.role})
            </option>`
        ).join('');

        const behaviorOptions = this.behaviors.map(b =>
            `<option value="${b.behavior_id}">${this.escapeHtml(b.name)}</option>`
        ).join('');

        return `<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Plan Composer</title>
    <style>
        body {
            font-family: var(--vscode-font-family);
            padding: 20px;
            color: var(--vscode-foreground);
            background-color: var(--vscode-editor-background);
        }
        h1, h2 { color: var(--vscode-titleBar-activeForeground); }
        .form-group {
            margin: 20px 0;
        }
        label {
            display: block;
            margin-bottom: 8px;
            font-weight: bold;
        }
        select, input, textarea {
            width: 100%;
            padding: 8px;
            background-color: var(--vscode-input-background);
            color: var(--vscode-input-foreground);
            border: 1px solid var(--vscode-input-border);
            border-radius: 4px;
            font-family: var(--vscode-font-family);
        }
        textarea {
            min-height: 100px;
            font-family: var(--vscode-editor-font-family);
        }
        button {
            background-color: var(--vscode-button-background);
            color: var(--vscode-button-foreground);
            border: none;
            padding: 10px 20px;
            cursor: pointer;
            border-radius: 4px;
            margin: 5px 5px 5px 0;
            font-size: 14px;
        }
        button:hover {
            background-color: var(--vscode-button-hoverBackground);
        }
        button.secondary {
            background-color: var(--vscode-button-secondaryBackground);
            color: var(--vscode-button-secondaryForeground);
        }
        button.secondary:hover {
            background-color: var(--vscode-button-secondaryHoverBackground);
        }
        .workflow-info {
            background-color: var(--vscode-editor-inactiveSelectionBackground);
            padding: 15px;
            border-radius: 4px;
            margin: 15px 0;
        }
        .step-list {
            list-style: none;
            padding: 0;
        }
        .step-item {
            background-color: var(--vscode-list-hoverBackground);
            padding: 10px;
            margin: 8px 0;
            border-radius: 4px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .step-number {
            font-weight: bold;
            margin-right: 10px;
        }
        .behavior-injection {
            background-color: var(--vscode-textBlockQuote-background);
            border-left: 4px solid var(--vscode-textBlockQuote-border);
            padding: 15px;
            margin: 15px 0;
        }
        .info-text {
            color: var(--vscode-descriptionForeground);
            font-size: 0.9em;
            margin-top: 5px;
        }
    </style>
</head>
<body>
    <h1>Plan Composer</h1>
    <p class="info-text">Create and execute behavior-conditioned workflows</p>

    <div class="form-group">
        <label for="workflow-select">Select Workflow Template</label>
        <select id="workflow-select" onchange="onWorkflowChange()">
            <option value="">-- Select a template --</option>
            ${workflowOptions}
        </select>
    </div>

    <div id="workflow-details" style="display: none;">
        <div class="workflow-info">
            <h2 id="workflow-name"></h2>
            <p id="workflow-description"></p>
            <p><strong>Role:</strong> <span id="workflow-role"></span></p>
        </div>

        <div class="form-group">
            <label for="context-input">Context / Variables (JSON)</label>
            <textarea id="context-input" placeholder='{"variable": "value"}'>{}</textarea>
            <p class="info-text">Optional: Provide context variables for the workflow</p>
        </div>

        <div class="behavior-injection">
            <h2>Behavior Injection</h2>
            <div class="form-group">
                <label for="behavior-select">Add Behavior to Workflow</label>
                <select id="behavior-select">
                    <option value="">-- Select a behavior --</option>
                    ${behaviorOptions}
                </select>
                <button onclick="addBehavior()" class="secondary">+ Add Behavior</button>
            </div>

            <div id="selected-behaviors">
                <h3>Selected Behaviors</h3>
                <ul id="behavior-list" class="step-list">
                    <li class="info-text">No behaviors selected yet</li>
                </ul>
            </div>
        </div>

        <div class="form-group">
            <h2>Workflow Steps</h2>
            <ul id="step-list" class="step-list"></ul>
        </div>

        <div style="margin-top: 30px;">
            <button onclick="runWorkflow()">▶ Run Workflow</button>
            <button onclick="saveWorkflow()" class="secondary">💾 Save as New Template</button>
        </div>
    </div>

    <script>
        const vscode = acquireVsCodeApi();
        const workflows = ${JSON.stringify(this.workflows)};
        const selectedBehaviors = [];

        function onWorkflowChange() {
            const select = document.getElementById('workflow-select');
            const workflowId = select.value;

            if (!workflowId) {
                document.getElementById('workflow-details').style.display = 'none';
                return;
            }

            const workflow = workflows.find(w => w.template_id === workflowId);
            if (!workflow) return;

            document.getElementById('workflow-name').textContent = workflow.name;
            document.getElementById('workflow-description').textContent = workflow.description || '';
            document.getElementById('workflow-role').textContent = workflow.role_focus;

            // Display steps
            const stepList = document.getElementById('step-list');
            stepList.innerHTML = workflow.steps.map((step, i) =>
                \`<li class="step-item">
                    <span><span class="step-number">Step \${i + 1}:</span> \${step.action || step.instruction || 'Untitled step'}</span>
                </li>\`
            ).join('');

            document.getElementById('workflow-details').style.display = 'block';
        }

        function addBehavior() {
            const select = document.getElementById('behavior-select');
            const behaviorId = select.value;
            const behaviorName = select.options[select.selectedIndex].text;

            if (!behaviorId) {
                vscode.postMessage({ command: 'showWarning', text: 'Please select a behavior' });
                return;
            }

            if (selectedBehaviors.find(b => b.id === behaviorId)) {
                vscode.postMessage({ command: 'showWarning', text: 'Behavior already added' });
                return;
            }

            selectedBehaviors.push({ id: behaviorId, name: behaviorName });
            updateBehaviorList();
        }

        function removeBehavior(behaviorId) {
            const index = selectedBehaviors.findIndex(b => b.id === behaviorId);
            if (index > -1) {
                selectedBehaviors.splice(index, 1);
                updateBehaviorList();
            }
        }

        function updateBehaviorList() {
            const list = document.getElementById('behavior-list');
            if (selectedBehaviors.length === 0) {
                list.innerHTML = '<li class="info-text">No behaviors selected yet</li>';
            } else {
                list.innerHTML = selectedBehaviors.map(b =>
                    \`<li class="step-item">
                        <span>\${b.name}</span>
                        <button onclick="removeBehavior('\${b.id}')" class="secondary">Remove</button>
                    </li>\`
                ).join('');
            }
        }

        function runWorkflow() {
            const workflowId = document.getElementById('workflow-select').value;
            const contextInput = document.getElementById('context-input').value;

            if (!workflowId) {
                vscode.postMessage({ command: 'showWarning', text: 'Please select a workflow template' });
                return;
            }

            let context = {};
            try {
                context = JSON.parse(contextInput);
            } catch (e) {
                vscode.postMessage({ command: 'showWarning', text: 'Invalid JSON in context field' });
                return;
            }

            // Add selected behaviors to context
            if (selectedBehaviors.length > 0) {
                context.behaviors = selectedBehaviors.map(b => b.id);
            }

            vscode.postMessage({
                command: 'runWorkflow',
                workflowId: workflowId,
                context: context
            });
        }

        function saveWorkflow() {
            vscode.postMessage({ command: 'showInfo', text: 'Save feature coming soon!' });
        }

        // Auto-select if templateId provided
        window.addEventListener('load', () => {
            const select = document.getElementById('workflow-select');
            if (select.value) {
                onWorkflowChange();
            }
        });
    </script>
</body>
</html>`;
    }

    private async handleMessage(message: any): Promise<void> {
        switch (message.command) {
            case 'runWorkflow':
                try {
                    const result = await this.client.runWorkflow(
                        message.workflowId,
                        message.context,
                        { source: 'plan_composer.run' }
                    );
                    vscode.window.showInformationMessage(
                        `Workflow started! Run ID: ${result.run_id}`,
                        'View Status'
                    ).then(selection => {
                        if (selection === 'View Status') {
                            vscode.commands.executeCommand('guideai.viewWorkflowStatus', result.run_id);
                        }
                    });
                } catch (error) {
                    vscode.window.showErrorMessage(`Failed to run workflow: ${error}`);
                    this.emitTelemetry('plan_composer_run_failed', {
                        template_id: message.workflowId,
                        error: error instanceof Error ? error.message : String(error)
                    });
                }
                break;
            case 'showInfo':
                vscode.window.showInformationMessage(message.text);
                break;
            case 'showWarning':
                vscode.window.showWarningMessage(message.text);
                break;
        }
    }

    private emitTelemetry(eventType: string, payload: Record<string, unknown>): void {
        void this.client.emitTelemetry(eventType, payload).catch(() => undefined);
    }

    private escapeHtml(text: string): string {
        return text
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

    public dispose(): void {
        PlanComposerPanel.currentPanel = undefined;
        this._panel.dispose();
        while (this._disposables.length) {
            const disposable = this._disposables.pop();
            if (disposable) {
                disposable.dispose();
            }
        }
    }
}
