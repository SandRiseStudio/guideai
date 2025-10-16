# GuideAI VS Code Extension

Behavior-conditioned inference for AI agents directly in your IDE. Access your behavior handbook, compose workflows, track execution, and ensure compliance without leaving VS Code.

## Features

### 🎯 Behavior Sidebar
Browse and search your organization's behavior handbook:
- **Hierarchical view** by role (Strategist/Teacher/Student)
- **Semantic search** to find relevant behaviors
- **One-click insertion** of behavior references into code
- **Detailed view** with examples, metadata, and usage instructions

### 📋 Plan Composer
Create and execute workflows using pre-built templates:
- **Strategist templates** for planning and decomposition
- **Teacher templates** for explanation and guidance
- **Student templates** for execution and reporting
- **Behavior injection** - automatically include relevant behaviors in workflow steps

### 🚀 Quick Actions
- Refresh behaviors from the handbook
- Search by natural language query
- Insert behavior references at cursor
- Run workflows with progress tracking

## Requirements

- VS Code 1.85.0 or higher
- Python 3.10+ with `guideai` CLI installed
- Active GuideAI account (for authentication)

## Installation

### From VSIX (Development)

```bash
# Navigate to extension directory
cd extension

# Install dependencies
npm install

# Compile TypeScript
npm run compile

# Package extension
npm run package

# Install in VS Code
code --install-extension guideai-vscode-0.1.0.vsix
```

### From Marketplace (Future)

Search for "GuideAI" in the VS Code Extensions marketplace.

## Setup

1. **Configure Python Path**
   ```json
   {
     "guideai.pythonPath": "/path/to/python",
     "guideai.cliPath": "guideai"
   }
   ```

2. **Authenticate**
   - Open Command Palette (`Cmd+Shift+P` / `Ctrl+Shift+P`)
   - Run `GuideAI: Authenticate`
   - Follow device flow instructions

3. **Open Sidebar**
   - Click the GuideAI icon in the Activity Bar
   - Or run `GuideAI: Open Behavior Sidebar`

## Usage

### Browsing Behaviors

1. Open the GuideAI sidebar
2. Expand role categories (Strategist/Teacher/Student)
3. Click any behavior to view full details
4. Use the search icon to find behaviors by query

### Inserting Behaviors

1. Place cursor where you want the reference
2. Right-click a behavior in the sidebar
3. Select "Insert Behavior Reference"
4. Behavior ID and description will be inserted

### Creating Workflows

1. Click the Plan Composer icon in the Workflow Templates view
2. Select a template (Strategist/Teacher/Student)
3. Configure steps and behavior injection
4. Click "Create Workflow" to save
5. Click "Run" to execute

### Monitoring Runs

- Open the Output panel (`View > Output`)
- Select "GuideAI" from the dropdown
- View real-time progress, behavior usage, and token accounting

## Extension Settings

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `guideai.pythonPath` | string | `"python"` | Path to Python interpreter |
| `guideai.cliPath` | string | `"guideai"` | Path to guideai CLI |
| `guideai.autoRefresh` | boolean | `true` | Auto-refresh on handbook changes |
| `guideai.defaultRole` | string | `"STRATEGIST"` | Default role filter |

## Commands

| Command | Keybinding | Description |
|---------|------------|-------------|
| `GuideAI: Refresh Behaviors` | - | Reload behavior handbook |
| `GuideAI: Search Behaviors` | - | Search by natural language |
| `GuideAI: Open Plan Composer` | - | Create workflow from template |
| `GuideAI: Insert Behavior` | - | Insert behavior reference at cursor |

## Development

### Running Locally

```bash
# Install dependencies
npm install

# Watch mode (auto-recompile)
npm run watch

# In VS Code, press F5 to launch Extension Development Host
```

### Testing

```bash
# Compile tests
npm run compile-tests

# Run tests
npm test
```

### Project Structure

```
extension/
├── src/
│   ├── extension.ts              # Entry point
│   ├── client/
│   │   └── GuideAIClient.ts      # Python CLI communication
│   ├── providers/
│   │   ├── BehaviorTreeDataProvider.ts
│   │   └── WorkflowTreeDataProvider.ts
│   └── webviews/
│       ├── BehaviorDetailPanel.ts
│       └── PlanComposerPanel.ts
├── resources/                     # Icons and assets
├── package.json                   # Extension manifest
└── tsconfig.json                  # TypeScript config
```

## Troubleshooting

### "Cannot find guideai CLI"
- Ensure `guideai` is installed: `pip install guideai`
- Configure correct path in settings
- Verify with: `guideai --version`

### "Authentication failed"
- Run `guideai auth login` in terminal first
- Ensure device flow completes successfully
- Check `guideai auth status`

### "No behaviors showing"
- Verify handbook is populated: `guideai behaviors list`
- Click refresh button in sidebar
- Check Output panel for errors

## Related Documentation

- [BehaviorService API](../docs/BEHAVIOR_VERSIONING.md)
- [WorkflowService Contract](../WORKFLOW_SERVICE_CONTRACT.md)
- [MCP Tools Reference](../mcp/tools/)
- [Parity Enforcement](../docs/PARITY_ENFORCEMENT_CHECKLIST.md)

## Contributing

Contributions welcome! Please read the [development guidelines](../docs/AGENT_DX.md) and ensure:
- All features have cross-surface parity (CLI/REST/MCP)
- Integration tests pass
- Documentation is updated

## License

MIT - See [LICENSE](../LICENSE) for details

## Support

- Documentation: [https://docs.guideai.dev](https://docs.guideai.dev)
- Issues: [GitHub Issues](https://github.com/Nas4146/guideai/issues)
- Community: [Discord](https://discord.gg/guideai)
