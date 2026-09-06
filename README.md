# RQ4

Multi-component research repo. Each component lives under `agent/` and is
bootstrapped by its own setup script.

## Components

| # | Name | Install | Setup |
|---|------|---------|-------|
| 1 | mini-swe-agent | `git clone` + `pip install -e` | [`scripts/setup.sh`](scripts/setup.sh) |
| 2 | openhands (Agent Canvas) | `npm install -g @openhands/agent-canvas` | [`scripts/setup-openhands.sh`](scripts/setup-openhands.sh) |

All components route their LLM calls through a shared OpenAI-compatible
gateway (`https://api.tu-zi.com`).

## Quick start

```bash
# Component 1 — CLI agent
bash scripts/setup.sh
bash agent/run_mini.sh -t "<your task>" -m openai/gpt-4o-mini

# Component 2 — Web UI on http://localhost:8000
bash scripts/setup-openhands.sh
bash agent/run_openhands.sh
# then open http://localhost:8000 and configure LLM via Settings
```

## Layout

```
.
├── README.md                — this file
├── .gitignore
├── scripts/
│   ├── setup.sh             — bootstrap for component 1
│   └── setup-openhands.sh   — bootstrap for component 2
└── agent/
    ├── README.md            — component-level notes
    ├── run_mini.sh          — wrapper for component 1
    ├── run_openhands.sh     — wrapper for component 2
    ├── config/              — component 1 config (tracked)
    │   ├── .env.example
    │   ├── mini.yaml
    │   └── smoke_test.py
    ├── openhands-config/    — component 2 config (tracked)
    │   ├── .env.example
    │   ├── README.md        — how to wire LLM via the web UI
    │   └── smoke_test.sh
    ├── .venv/               — Python venv (gitignored)
    └── mini-swe-agent/      — read-only upstream clone (gitignored)
```