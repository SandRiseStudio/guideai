# GuideAI IDE Extension

<div align="center">

![GuideAI Logo](resources/icon.png)

**Transform your IDE into an intelligent development companion with AI agent orchestration, real-time monitoring, and compliance validation.**

[![Version](https://img.shields.io/github/v/release/guideai/guideai?label=version)](https://github.com/guideai/guideai/releases)
[![Build Status](https://img.shields.io/github/workflow/status/guideai/guideai/CI?label=build)](https://github.com/guideai/guideai/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-MIT-green)](https://github.com/guideai/guideai/blob/main/LICENSE)
[![VSCode Marketplace](https://img.shields.io/badge/vscode-marketplace-blue)](https://marketplace.visualstudio.com/items?itemName=guideai.guideai-ide-extension)

</div>

## 🚀 What is GuideAI?

GuideAI is a comprehensive AI agent orchestration platform that brings intelligent automation directly into your development workflow. The VSCode extension provides real-time monitoring, compliance management, and AI-powered development assistance.

## ✨ Key Features

### 🧠 **Execution Tracker**
- **Real-time monitoring** of AI agent runs with auto-refresh every 5 seconds
- **Visual status indicators** showing progress, completion, and errors
- **Detailed run information** with comprehensive step-by-step tracking
- **Error highlighting** with actionable insights and debugging support

### ✅ **Compliance Tracker**
- **Interactive checklists** for development processes and standards
- **Coverage progress tracking** with visual progress indicators
- **Evidence attachment** capabilities for audit trail maintenance
- **Approval workflows** with comments and decision tracking

### 🤖 **AI Agent Orchestration**
- **220 MCP Tools** for comprehensive AI agent management (works natively in VS Code Copilot Chat!)
- **Behavior management** with semantic search and categorization
- **Workflow templates** for common development patterns
- **Multi-agent coordination** for complex development tasks

### 🔐 **Enterprise-Ready**
- **OAuth2 Device Flow** authentication with secure token management
- **Multi-tenant support** for team and organization usage
- **Compliance coverage** with SOC2-ready audit logging
- **Real-time telemetry** for performance monitoring

## 🎯 Who Should Use This?

- **Development Teams** wanting to implement AI agent workflows
- **Organizations** requiring compliance tracking and audit trails
- **Developers** seeking intelligent automation in their IDE
- **Teams** managing complex AI agent orchestration
- **Enterprises** needing enterprise-grade development tooling

## 🛠️ Quick Start

1. **Install the Extension**
   ```bash
   code --install-extension guideai.guideai-ide-extension
   ```

2. **Authenticate with GuideAI**
   - Run the command `GuideAI: Sign In` from the command palette
   - Follow the OAuth2 device flow authentication process

3. **Explore the Features**
   - Open the **Execution Tracker** in the Explorer panel
   - Access the **Compliance Tracker** for validation workflows
   - Use command palette for all GuideAI operations

## 📊 Platform Overview

| Component | Status | Performance |
|-----------|--------|-------------|
| **Backend Services** | 17/17 Operational | P95 <100ms |
| **MCP Tools** | 220/220 Available | 100% Coverage |
| **Test Suite** | 450+ Passing Tests | 95%+ Coverage |
| **Compliance** | SOC2 Ready | Audit Trail Complete |
| **Authentication** | OAuth2 Device Flow | Enterprise Grade |

## 🏗️ Architecture

GuideAI is built on a robust, scalable architecture:

- **17 Backend Services** with full CLI/REST/MCP parity
- **PostgreSQL/TimescaleDB** for production-grade data storage
- **Redis Caching** for optimal performance
- **Real-time Streaming** via Kafka integration
- **Analytics Pipeline** with comprehensive KPI tracking

## 🔧 Commands Available

| Command | Description | Shortcut |
|---------|-------------|----------|
| `GuideAI: Sign In` | Authenticate with GuideAI platform | `Ctrl+Alt+G I` |
| `GuideAI: Refresh Execution Tracker` | Update run monitoring | `Ctrl+Alt+G R` |
| `GuideAI: Open Compliance Review` | Access compliance workflows | `Ctrl+Alt+G C` |
| `GuideAI: Show Output` | Display GuideAI logs | `Ctrl+Alt+G O` |

## 🖥️ Interface Overview

### Execution Tracker
- **Tree view** of all active runs with real-time status
- **Auto-refresh** every 5 seconds for live monitoring
- **Color-coded status** indicators (running, completed, failed, cancelled)
- **Detailed run information** with step-by-step progress

### Compliance Tracker
- **Interactive checklists** for development processes
- **Progress visualization** with coverage tracking
- **Evidence management** for audit compliance
- **Approval workflows** with team collaboration

## 📈 Performance & Reliability

- **Ultra-fast response times**: P95 <100ms for all operations
- **99.9% uptime** with enterprise-grade reliability
- **Real-time updates** with minimal latency
- **Comprehensive error handling** with graceful degradation

## 🔒 Security & Compliance

- **Enterprise authentication** via OAuth2 device flow
- **Secure token management** with automatic refresh
- **Audit logging** for all operations and changes
- **Multi-tenant isolation** for team security
- **Compliance tracking** with automated evidence collection

## 🌍 Multi-IDE Support

GuideAI is also available for:
- **Cursor IDE** - AI-powered code editor
- **Claude Desktop** - Anthropic's AI assistant
- **Any MCP-compatible IDE** - Universal AI agent integration

## 📚 Documentation & Support

- 📖 **Full Documentation**: [docs.guideai.com](https://docs.guideai.com)
- 🐛 **Issue Tracking**: [GitHub Issues](https://github.com/guideai/guideai/issues)
- 💬 **Community Support**: [GitHub Discussions](https://github.com/guideai/guideai/discussions)
- 🏢 **Enterprise Support**: [guideai.com/enterprise](https://guideai.com/enterprise)

## 🤝 Contributing

We welcome contributions! Please see our [Contributing Guide](https://github.com/guideai/guideai/blob/main/CONTRIBUTING.md) for details.

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](https://github.com/guideai/guideai/blob/main/LICENSE) file for details.

## 🙏 Acknowledgments

- Built with love by the GuideAI team
- Inspired by the Model Context Protocol (MCP) specification
- Thanks to our amazing community of contributors

---

<div align="center">

**Made with ❤️ for developers who build the future**

[Download from VSCode Marketplace](https://marketplace.visualstudio.com/items?itemName=guideai.guideai-ide-extension) | [View on GitHub](https://github.com/guideai/guideai) | [Get Started](https://docs.guideai.com)

</div>
