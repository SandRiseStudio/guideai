# GuideAI Homebrew Formula
#
# Usage:
#   1. Create a tap repository: github.com/<org>/homebrew-guideai
#   2. Copy this formula to Formula/guideai.rb in the tap
#   3. Install with: brew install <org>/guideai/guideai
#
# Or install directly from PyPI:
#   brew install python@3.11
#   pip install guideai

class Guideai < Formula
  include Language::Python::Virtualenv

  desc "AI-powered developer tooling and task orchestration"
  homepage "https://amprealize.ai"
  url "https://files.pythonhosted.org/packages/source/g/guideai/guideai-0.1.0.tar.gz"
  sha256 "REPLACE_WITH_ACTUAL_SHA256_AFTER_PYPI_PUBLISH"
  license "Apache-2.0"
  head "https://github.com/Nas4146/guideai.git", branch: "main"

  depends_on "python@3.11"
  depends_on "podman" => :optional

  # Core dependencies (pinned for reproducibility)
  resource "fastapi" do
    url "https://files.pythonhosted.org/packages/source/f/fastapi/fastapi-0.115.0.tar.gz"
    sha256 "REPLACE_WITH_ACTUAL_SHA256"
  end

  resource "pydantic" do
    url "https://files.pythonhosted.org/packages/source/p/pydantic/pydantic-2.9.0.tar.gz"
    sha256 "REPLACE_WITH_ACTUAL_SHA256"
  end

  resource "httpx" do
    url "https://files.pythonhosted.org/packages/source/h/httpx/httpx-0.27.0.tar.gz"
    sha256 "REPLACE_WITH_ACTUAL_SHA256"
  end

  resource "click" do
    url "https://files.pythonhosted.org/packages/source/c/click/click-8.1.7.tar.gz"
    sha256 "ca9853ad459e787e2192211578cc907e7594e294c7ccc834310722b41b9ca6de"
  end

  resource "pyyaml" do
    url "https://files.pythonhosted.org/packages/source/p/pyyaml/pyyaml-6.0.2.tar.gz"
    sha256 "d584d9ec91ad65861cc08d42e834324ef890a082e591037abe114850ff7bbc3e"
  end

  def install
    virtualenv_install_with_resources

    # Generate shell completions
    generate_completions_from_executable(bin/"guideai", shells: [:bash, :zsh, :fish], shell_parameter_format: :click)
  end

  def post_install
    # Create data directories
    (var/"guideai").mkpath
    (var/"guideai/data").mkpath
    (var/"guideai/telemetry").mkpath
  end

  def caveats
    <<~EOS
      GuideAI has been installed!

      To get started:
        guideai init              # Initialize a new project
        guideai doctor            # Check installation health
        guideai mcp-server        # Start the MCP server

      Configuration is stored in:
        ~/.guideai/config.yaml    (user config)
        .guideai/config.yaml      (project config)

      Data is stored in:
        #{var}/guideai/           (Homebrew managed)

      For MCP integration with VS Code:
        Add to your VS Code settings.json:
        {
          "github.copilot.chat.mcpServers": {
            "guideai": {
              "command": "guideai",
              "args": ["mcp-server"]
            }
          }
        }

      Optional: Install Podman for infrastructure management:
        brew install podman
    EOS
  end

  test do
    # Test CLI is accessible
    assert_match "GuideAI", shell_output("#{bin}/guideai --version")

    # Test doctor command (JSON output for parsing)
    output = shell_output("#{bin}/guideai doctor --json")
    assert_match '"passed":', output

    # Test init in temp directory
    system bin/"guideai", "init", "--non-interactive", "--template", "minimal"
    assert_predicate testpath/".guideai/config.yaml", :exist?

    # Test Python import
    system "python3", "-c", "import guideai; print(guideai.__version__)"
  end
end
