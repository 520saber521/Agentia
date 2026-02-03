# AgentHub - Multi-Agent Collaboration Framework

<div align="center">

<img src="images/8beddced-3fd2-4756-b0db-b090c8648092.png" alt="AgentHub Workflow" width="800">

> **Orchestrate multiple AI Agents to work together like a human team**
> Complete complex software development tasks through reliable messaging protocols

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![GitHub stars](https://img.shields.io/github/stars/Dmatut7/AgentHub?style=social)](https://github.com/Dmatut7/AgentHub/stargazers)
[![GitHub forks](https://img.shields.io/github/forks/Dmatut7/AgentHub?style=social)](https://github.com/Dmatut7/AgentHub/network)
[![GitHub issues](https://img.shields.io/github/issues/Dmatut7/AgentHub)](https://github.com/Dmatut7/AgentHub/issues)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](https://github.com/Dmatut7/AgentHub/pulls)

[Features](#features) | [Quick Start](#quick-start) | [Architecture](#architecture) | [Examples](#use-cases) | [Contributing](#contributing)

</div>

---

## What is AgentHub?

**AgentHub** is an open-source **Multi-Agent Orchestration Framework** that enables reliable communication and coordinated work between multiple AI Agents through a message routing architecture.

With a **single command**, launch a complete AI development team with:
- **1 Coordinator Agent (MAIN)** - task planning, coordination, and review
- **4 Executor Agents (A/B/C/D)** - parallel task execution

Manage AI collaborative development just like managing a human team.

---

## Why AgentHub?

| Traditional AI Development | AgentHub |
|:---------------------------:|:--------:|
| Single AI working alone | **Multi-Agent Parallel Collaboration** |
| No division of labor | **Automatic Task Breakdown & Assignment** |
| High communication overhead | **Standardized Messaging Protocol** |
| State easily lost | **Persistence + Crash Recovery** |
| Hard to track progress | **Complete Task State Management** |

---

## Features

### 🚀 One-Command Team Launch

```bash
./scripts/start_team.sh
```

- Auto-start Router (message hub)
- Open 5 independent terminal windows
- Generate standard documentation templates
- Inject AI role prompts

### 🧠 Intelligent Task Scheduling (NEW)

```bash
# Analyze project before adding features
team analyze --path . --feature "user login"

# Generate design document
team design --requirement "user login with OAuth"

# Smart execution with contract-first design
team run --task "implement login" --design-approved
```

- **Complexity Judgment** - Auto-detect simple/complex tasks
- **Task Decomposition** - Break down into subtasks by domain
- **Contract-First Design** - Generate interface contracts before coding
- **Specialized Agents** - Frontend(A), Backend(B), Database(C), Support(D)

### 🤝 Real-time Collaboration (NEW)

```bash
# View progress board
team board

# Report progress
team progress --task TASK-001 --percent 50 --step "implementing API"

# Lock files to prevent conflicts
team lock --files "src/api.py" --task TASK-001

# Notify interface changes
team notify --task TASK-001 --interface "POST /api/login" --change-type modify
```

- **Progress Board** - Real-time visibility of all agents
- **File Locking** - Prevent code conflicts
- **Change Broadcasting** - Auto-notify when interfaces change
- **Dependency Tracking** - Track and alert on blocked tasks

### 🔄 Reliable Message Delivery

- **ACK Confirmation** - Dual acknowledgment at delivery and application layer
- **Auto Retry** - Exponential backoff retry strategy
- **Timeout Handling** - Automatic timeout detection and handling
- **Idempotency** - Message deduplication to avoid duplicate execution

### 📋 Complete Collaboration Protocol

```
analyze -> design -> confirm -> schedule -> execute -> aggregate
```

Standardized AI-to-AI communication protocol supporting:
- Project analysis & impact assessment
- Design document generation
- Contract-first task decomposition
- Parallel execution with coordination
- Result aggregation

### 💾 State Persistence & Recovery

- Message logs (JSONL format)
- Inbox state persistence
- Auto-recovery after crash
- Session/epoch management support

### 🔧 Flexible Configuration

- Customizable agent count
- Support for different AI CLI tools (Codex, Claude Code, etc.)
- Environment variable configuration

---

## Demo

> Watch how AgentHub orchestrates 5 AI agents working together

[![Demo Video](https://img.shields.io/badge/Watch-Demo-red?style=for-the-badge&logo=youtube)](https://github.com/Dmatut7/AgentHub#demo)

*Coming soon: Video demonstration of multi-agent collaboration*

---

## Architecture

![Architecture](images/architecture.png)

```
                    Router Server
        (Message Routing / State Management / Delivery)

                    │
    ┌───────┬───────┼───────┬───────┐
    │       │       │       │       │
┌───▼───┐ ┌─▼───┐ ┌─▼───┐ ┌─▼───┐ ┌─▼───┐
│ MAIN  │ │  A  │ │  B  │ │  C  │ │  D  │
│Coord. │ │Exec │ │Exec │ │Exec │ │Exec │
│Agent  │ │Agent│ │Agent│ │Agent│ │Agent│
└───────┘ └─────┘ └─────┘ └─────┘ └─────┘
```

**Role Responsibilities:**
| Agent | Role | Specialty | Responsibilities |
|:-----:|:-----:|:---------:|:------------------|
| **MAIN** | Coordinator | - | Task planning, design review, problem solving |
| **A** | Frontend Expert | UI/UX | React, Vue, CSS, components, pages |
| **B** | Backend Expert | API | FastAPI, business logic, services |
| **C** | Database Expert | Data | Models, migrations, queries |
| **D** | Support Expert | DevOps | Testing, docs, deployment |

---

## Message Protocol

AgentHub defines a complete AI-to-AI communication protocol:

| Message Type | Direction | Purpose |
|:------------:|:--------:|:---------|
| `review` | MAIN->Members | Review documents/code |
| `report` | Members->MAIN | Feedback review results |
| `assign` | MAIN->Members | Assign tasks |
| `clarify` | Members->MAIN | Ask questions |
| `answer` | MAIN->Members | Answer questions |
| `verify` | MAIN->Members | Verify changes |
| `done` | Members->MAIN | Task complete |
| `fail` | Members->MAIN | Task failed |

See [docs/main-members-workflow.md](docs/main-members-workflow.md) for complete protocol specification.

---

## Quick Start

### Prerequisites

- **macOS** (Linux support planned)
- **Python 3.8+**
- **Terminal.app or iTerm2**
- **AI CLI tool** (Codex, Claude Code, or compatible)

### Installation

```bash
# Clone repository
git clone https://github.com/Dmatut7/AgentHub.git
cd AgentHub
```

### Launch AI Team

```bash
# Start in your project directory
./scripts/start_team.sh
```

The system will automatically:
1. Start Router (default port 8765)
2. Generate standard documentation templates
3. Open 5 terminal windows for each agent

---

## Use Cases

### 1. Code Review Pipeline
```bash
# MAIN writes code -> A/B/C/D review in parallel -> MAIN consolidates feedback
```

### 2. Parallel Feature Development
```bash
# MAIN breaks down feature -> A/B/C/D implement components -> MAIN integrates
```

### 3. Documentation Generation
```bash
# MAIN outlines -> A/B/C/D write sections -> MAIN finalizes
```

### 4. Bug Hunt & Fix
```bash
# MAIN describes bug -> A/B/C/D investigate & propose fixes -> MAIN verifies
```

See [EXAMPLES.md](EXAMPLES.md) for detailed use cases.

---

## Directory Structure

```
AgentHub/
├── scripts/               # Launch scripts
│   ├── start_team.sh     # One-command launch
│   ├── stop_team.sh      # Stop system
│   └── status_team.sh    # Check status
├── src/
│   ├── api/              # HTTP server
│   ├── cli/              # CLI tools
│   ├── router/           # Message routing core
│   ├── protocol/         # Protocol definitions
│   ├── state/            # State management
│   ├── storage/          # Persistent storage
│   └── launcher/         # Terminal launcher
├── prompts/              # AI prompt templates
├── doc/                  # Documentation templates
├── docs/                 # Design documents
│   ├── design.md         # System architecture
│   └── main-members-workflow.md  # Protocol spec
└── README.md
```

---

## Common Commands

```bash
# === System Management ===
./scripts/start_team.sh          # Start system
./scripts/status_team.sh         # Check status
./scripts/stop_team.sh           # Stop system

# === Smart Task Flow (NEW) ===
team analyze --path . --feature "new feature"    # Analyze impact
team design --requirement "feature description"   # Generate design
team run --task "feature" --design-approved       # Execute with contracts
team schedule --task "feature description"        # Preview schedule only

# === Collaboration (NEW) ===
team board                                        # View progress board
team progress --task T1 --percent 50 --step "..."# Report progress
team lock --files "src/api.py" --task T1         # Lock files
team notify --task T1 --interface "API" -c modify # Notify changes

# === Messaging ===
team say --from MAIN --to A --text "Start task"  # Send message
team review --to A,B,C,D --task T1 --file doc.md # Request review
team assign --to B --task T1 --files "src/*"     # Assign task

# === Monitoring ===
team status --tasks                              # View task status
team trace --task T1                             # Trace task messages
curl http://127.0.0.1:8765/status | jq           # Raw API status
```

---

## Configuration

| Environment Variable | Description | Default |
|:--------------------|:------------|:--------|
| `TERMINAL_ADAPTER` | Terminal type (`terminal`/`iterm`) | `terminal` |
| `CODEX_PATH` | AI CLI executable path | `codex` |

---

## Contributing

We welcome contributions! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for details.

Quick steps:
1. Fork the repository
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

---

## Documentation

- [Design Doc](docs/design.md) - System architecture
- [Protocol Spec](docs/main-members-workflow.md) - Message protocol details
- [Examples](EXAMPLES.md) - Use cases and examples
- [Contributing](CONTRIBUTING.md) - Contribution guide
- [Support](SUPPORT.md) - Help & troubleshooting
- [Changelog](CHANGELOG.md) - Version history

---

## Roadmap

- [ ] Linux support
- [ ] Windows support
- [ ] Web dashboard for monitoring
- [ ] More AI model integrations (GPT-4, Claude, Gemini)
- [ ] Plugin system for custom protocols
- [ ] Distributed agent support (across machines)

---

## License

[MIT License](LICENSE) © 2026 [Dmatut7](https://github.com/Dmatut7)

---

<div align="center">

**AgentHub** - Making AI team collaboration simpler.

[GitHub](https://github.com/Dmatut7/AgentHub) | [Issues](https://github.com/Dmatut7/AgentHub/issues) | [Discussions](https://github.com/Dmatut7/AgentHub/discussions)

⭐ **If you find this project helpful, please give it a Star!**

</div>
