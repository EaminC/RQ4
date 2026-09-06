# Agent components

Each subdirectory is a self-contained RQ4 component. See the table in the
top-level [README](../README.md) for the current list.

## Component 1 — `mini-swe-agent`

Wraps [`SWE-agent/mini-swe-agent`](https://github.com/SWE-agent/mini-swe-agent)
and routes it through the shared tu-zi OpenAI-compatible gateway.

### Boundary

| Layer | Owner | Tracked? |
| --- | --- | --- |
| `mini-swe-agent/` (cloned from upstream) | upstream | **No** |
| `.venv/` (Python venv) | local | **No** |
| `config/`, `run_mini.sh` | **RQ4** | Yes |

We only ever edit files tracked in git. `scripts/setup.sh` will refuse to
overwrite an existing upstream clone whose `origin` is not the official
`SWE-agent/mini-swe-agent` — this catches accidental in-place edits.

### Files

- `run_mini.sh` — single entry point. Sources `config/.env`, activates the
  venv, then `exec`s the `mini` CLI with `config/mini.yaml`.
- `config/mini.yaml` — agent config (cost cap, mode).
- `config/.env` — real API key + base URL (gitignored, `chmod 600`).
- `config/.env.example` — template for the above.
- `config/smoke_test.py` — single round-trip tool-call verification.

### Usage

```bash
# one-time bootstrap
bash scripts/setup.sh

# run a task
bash agent/run_mini.sh -t "fix the failing test in src/foo.py" -m openai/gpt-4o-mini

# run the smoke test by hand
source agent/config/.env
source agent/.venv/bin/activate
python agent/config/smoke_test.py
```