# RQ4

Multi-component research repo. Each component lives under `agent/` and is
bootstrapped by its own setup script.

## Components

| # | Name | Upstream | Setup |
|---|------|----------|-------|
| 1 | mini-swe-agent | https://github.com/SWE-agent/mini-swe-agent | [`scripts/setup.sh`](scripts/setup.sh) |

All components route their LLM calls through a shared OpenAI-compatible
gateway (`https://api.tu-zi.com`).

## Quick start

```bash
# Component 1
bash scripts/setup.sh

# Run the agent on a task
bash agent/run_mini.sh -t "<your task here>" -m openai/gpt-4o-mini
```

## Layout

```
.
├── README.md             — this file
├── .gitignore
├── scripts/
│   └── setup.sh          — bootstrap script for component 1
└── agent/
    ├── README.md         — component-level notes
    ├── run_mini.sh       — wrapper to invoke the agent
    ├── config/           — component 1 config (tracked)
    │   ├── .env.example  — template for the tu-zi gateway credentials
    │   ├── mini.yaml     — mini-swe-agent config
    │   └── smoke_test.py — single round-trip verification
    ├── .venv/            — Python venv (gitignored)
    └── mini-swe-agent/   — read-only upstream clone (gitignored)
```