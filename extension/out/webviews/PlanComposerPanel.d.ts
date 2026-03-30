import * as vscode from 'vscode';
import { GuideAIClient } from '../client/GuideAIClient';
export declare class PlanComposerPanel {
    private client;
    private templateId?;
    static currentPanel: PlanComposerPanel | undefined;
    private readonly _panel;
    private _disposables;
    private workflows;
    private behaviors;
    private constructor();
    static createOrShow(extensionUri: vscode.Uri, client: GuideAIClient, template?: any): Promise<void>;
    private initialize;
    private getWebviewContent;
    private handleMessage;
    private handleBCIRetrieve;
    private handleBCIValidate;
    private emitTelemetry;
    private escapeHtml;
    dispose(): void;
}
//# sourceMappingURL=PlanComposerPanel.d.ts.map