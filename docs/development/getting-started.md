# 🚀 Getting Started

> Quick start guide for nixos-ai development.

## Prerequisites

- NixOS with flakes enabled
- NVIDIA GPU (RTX 4050 or better)
- 32GB RAM recommended

## First Time Setup

```bash
# Clone the repo
git clone git@github.com:Kuchiriel/nixos-ai.git
cd nixos-ai

# Build and switch to the configuration
./rebuild-host.sh

# Verify everything is running
jarvis doctor
```

## Daily Workflow

```bash
# Check system status
jarvis status

# Start coding with the REPL
jarvis dev

# Or use Roo Dev in VSCodium
codium .
# Click the Roo Dev icon in the sidebar
```

## Project Structure

```
nixos-ai/
├── flake.nix              # NixOS configuration entry point
├── hosts/                 # Host-specific configurations
│   └── nitro-v15/        # Acer Nitro V15 laptop
├── modules/
│   ├── ai/               # JARVIS agent, models, MCP
│   │   ├── jarvis/       # Python package
│   │   ├── package.nix   # Package definition
│   │   └── models.nix    # LLM profiles
│   ├── services/         # systemd services
│   │   ├── llama-cpp.nix # llama.cpp server
│   │   ├── qdrant.nix    # Vector database
│   │   └── jarvis-*.nix  # JARVIS services
│   └── system/           # NixOS modules
├── home-manager/         # User configuration
│   ├── modules/
│   │   ├── waybar.nix    # Status bar
│   │   ├── hyprland/     # Window manager
│   │   ├── agents-md.nix # AI context file
│   │   └── jarvismodes.nix # Custom modes
│   └── home.nix          # Home config entry
├── docs/                 # Documentation
│   ├── architecture/     # System architecture
│   ├── benchmarks/       # Performance data
│   └── development/      # Developer guides
└── scripts/              # Utility scripts
```

## Common Tasks

### Add a new MCP tool

1. Add tool definition to `modules/ai/jarvis/src/jarvis/mcp_server.py`
2. Add execution handler to `call_tool()` function
3. Add to REPL in `modules/ai/jarvis/src/jarvis/cli/dev.py` (`_get_tools()`)
4. Test: `nix develop --command python3 -m pytest modules/ai/jarvis/tests/ -x`

### Add a new JARVIS mode

1. Edit `.jarvismodes` in project root
2. Or edit `home-manager/modules/jarvismodes.nix` for system-wide
3. Restart REPL: `/modes` to verify

### Run benchmarks

```bash
# Quick benchmark
cd scripts && ./benchmark.sh

# Official benchmark with thermal monitoring
python3 scripts/benchmark-official.py --config baseline
```

### Debug issues

```bash
# Check service status
jarvis doctor

# Check logs
journalctl -u llama-cpp-server -f
journalctl -u jarvis-telegram -f

# Test MCP server
cd modules/ai/jarvis && python3 -m mcp_server
```

## Testing

```bash
# Run all tests
nix develop --command python3 -m pytest modules/ai/jarvis/tests/ -x -v

# Run specific test
nix develop --command python3 -m pytest modules/ai/jarvis/tests/test_agent.py -x

# Run E2E tests (requires live services)
nix develop --command python3 -m pytest modules/ai/jarvis/tests/test_mcp_tools_e2e.py -x -v
```
