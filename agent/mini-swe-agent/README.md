# Mini-SWE-Agent — RQ4 component 1

Upstream: <https://github.com/SWE-agent/mini-swe-agent>
API gateway: <https://api.tu-zi.com> (OpenAI-compatible)

## Boundary: mini-swe-agent is an EXTERNAL MODULE

We treat mini-swe-agent as a read-only external dependency:

| Layer | Owner | Tracked in RQ4 git? |
| --- | --- | --- |
| `upstream/` (cloned from `SWE-agent/mini-swe-agent`) | upstream | **No** (gitignored) |
| `.venv/` (Python venv built from `upstream/`) | local | **No** (gitignored) |
| `mini.yaml`, `setup.sh`, `smoke_test.py`, `secrets.env` | **this repo (RQ4)** | Yes |

We only ever edit files in *this* directory. `setup.sh` will refuse to
proceed if `upstream/` already exists with a remote other than the official
one, so accidental edits inside `upstream/` are surfaced loudly.

## Files

- `setup.sh` — one-shot bootstrap (idempotent).
- `secrets.env` — created by `setup.sh` on first run (gitignored).
- `secrets.env.example` — template.
- `mini.yaml` — generated. Loaded with `mini -c mini.yaml`. Routes litellm
  at the tu-zi gateway.
- `smoke_test.py` — generated. Drives one tool-calling round-trip through
  LitellmModel to verify the gateway is reachable.
- `upstream/`, `.venv/` — populated by `setup.sh` (gitignored).

## Bootstrap

```bash
./setup.sh
```

## Running the agent

```bash
source .venv/bin/activate

# Single prompt, yolo (no confirmation):
mini -c mini.yaml -m openai/gpt-4o-mini -y -t "Write a hello-world python script under /tmp/hi.py"

# Use a bigger model for harder tasks:
mini -c mini.yaml -m openai/claude-sonnet-4-5 -y -t "..."

# List models available on the gateway:
curl -s "$TUZI_BASE_URL/models" -H "Authorization: Bearer $TUZI_API_KEY" \
  | python3 -c "import json,sys; print('\n'.join(m['id'] for m in json.load(sys.stdin)['data']))"
```

## How the routing works

Mini-SWE-Agent uses [`litellm`](https://github.com/BerriAI/litellm) under the
hood. litellm supports the `openai/<model-id>` prefix and looks at
`OPENAI_API_BASE` / `OPENAI_API_KEY` env vars (or equivalent `api_base` /
`api_key` kwargs) to route calls.

Our `mini.yaml` sets both via `model_kwargs`, and the smoke test additionally
exports `OPENAI_API_BASE` / `OPENAI_API_KEY` as belt-and-suspenders.

## Files NOT to commit

`secrets.env`, `upstream/`, `.venv/`, `.mswea*/` — all covered by `.gitignore`.