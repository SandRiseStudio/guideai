import * as vscode from 'vscode';
import { GuideAIClient, WorkflowTemplate } from '../client/GuideAIClient';
type WorkflowNode = WorkflowTreeItem | RoleTreeItem | MessageTreeItem;
export declare class WorkflowTreeDataProvider implements vscode.TreeDataProvider<WorkflowNode> {
    private client;
    private _onDidChangeTreeData;
    readonly onDidChangeTreeData: vscode.Event<WorkflowNode | undefined | null | void>;
    private workflows;
    private searchQuery;
    constructor(client: GuideAIClient);
    refresh(): void;
    search(query: string): Promise<void>;
    private loadWorkflows;
    getTreeItem(element: WorkflowNode): vscode.TreeItem;
    getChildren(element?: WorkflowNode): Promise<WorkflowNode[]>;
    private getTemplateRole;
}
declare class RoleTreeItem extends vscode.TreeItem {
    readonly label: string;
    readonly role: string;
    constructor(label: string, role: string);
}
declare class WorkflowTreeItem extends vscode.TreeItem {
    readonly workflow: WorkflowTemplate;
    readonly collapsibleState: vscode.TreeItemCollapsibleState;
    constructor(workflow: WorkflowTemplate, collapsibleState: vscode.TreeItemCollapsibleState);
}
declare class MessageTreeItem extends vscode.TreeItem {
    constructor(label: string, tooltip?: string);
}
export {};
//# sourceMappingURL=WorkflowTreeDataProvider.d.ts.map