# GuideAI CLI

AI-powered developer tooling and task orchestration.

## Installation

```bash
npm install -g guideai
```

This npm package is a wrapper that manages the Python-based GuideAI CLI. Python 3.10+ is required and will be detected automatically.

### Prerequisites

- **Node.js** 18+ (for the npm wrapper)
- **Python** 3.10+ (for GuideAI itself)

The wrapper will automatically install the Python package on first use if not already present.

## Usage

```bash
# Initialize a new project
guideai init

# Check installation health
guideai doctor

# Start the MCP server for VS Code/Cursor integration
guideai mcp-server

# Show help
guideai --help
```

## VS Code / Cursor Integration

Add to your VS Code settings.json:

```json
{
  "github.copilot.chat.mcpServers": {
    "guideai": {
      "command": "guideai",
      "args": ["mcp-server"]
    }
  }
}
```

## Alternative Installation Methods

### pip (Python)

```bash
pip install guideai
```

### Homebrew (macOS)

Requires a published tap repository (for example `SandRiseStudio/homebrew-guideai`; see `packages/homebrew/README.md`).

```bash
brew tap sandrisestudio/guideai
brew install guideai
```

## Configuration

Configuration is stored in YAML format:

- `~/.guideai/config.yaml` - User-level configuration
- `.guideai/config.yaml` - Project-level configuration

Run `guideai init` to create a configuration file interactively.

## Links

- [Documentation](https://amprealize.ai/docs)
- [GitHub](https://github.com/SandRiseStudio/guideai)
- [PyPI](https://pypi.org/project/guideai/)

## License

Apache-2.0
