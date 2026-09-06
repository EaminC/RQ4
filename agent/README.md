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
  venv, then `exec`s the `mini` CLI with both the built-in `mini.yaml`
  and our `config/mini.yaml` so defaults aren't clobbered.
- `config/mini.yaml` — user-customizable extension point (intentionally
  empty by default; CLI flags cover `cost-limit` and `mode`).
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

## Component 2 — `openhands` (Agent Canvas)

Wraps [`OpenHands/OpenHands`](https://github.com/OpenHands/OpenHands) via
the [`@openhands/agent-canvas`](https://www.npmjs.com/package/@openhands/agent-canvas)
npm package. Unlike component 1, this is a long-running web UI rather
than a one-shot CLI.

### Boundary

| Layer | Owner | Tracked? |
| --- | --- | --- |
| `@openhands/agent-canvas` (global npm install) | npm registry | **No** (system-level) |
| `openhands-config/`, `run_openhands.sh` | **RQ4** | Yes |

### LLM configuration

OpenHands stores LLM settings in an encrypted server-side store. They
cannot be pre-configured from the CLI. On first launch:

1. Open <http://localhost:8000> in a browser.
2. Go to **Settings → LLM** → toggle **Advanced**.
3. Fill in:
   - **Custom Model**: `openai/gpt-4o-mini`
   - **Base URL**: `https://api.tu-zi.com/v1`
   - **API Key**: the tu-zi key from `openhands-config/.env`
4. **Save Changes**.

See `openhands-config/README.md` for the canonical version.

### Files

- `run_openhands.sh` — sources `openhands-config/.env` (which exports
  `LOCAL_BACKEND_API_KEY` and `OH_SECRET_KEY`), then `exec agent-canvas`.
- `openhands-config/.env` — auto-generated API key + secret key
  (gitignored, `chmod 600`).
- `openhands-config/.env.example` — template.
- `openhands-config/README.md` — LLM setup steps.
- `openhands-config/smoke_test.sh` — boots the stack, hits `/alive`,
  tears it down. Does NOT exercise the LLM (that needs the UI config
  step above).

### Usage

```bash
# one-time bootstrap (installs npm package, generates keys, smoke tests)
bash scripts/setup-openhands.sh

# start the canvas (foreground)
bash agent/run_openhands.sh

# or pick a port / mode
bash agent/run_openhands.sh -p 9000
bash agent/run_openhands.sh --backend-only
```