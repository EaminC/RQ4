# Mini-SWE-Agent — RQ4 component 1

Upstream: <https://github.com/SWE-agent/mini-swe-agent>
API gateway: <https://api.tu-zi.com> (OpenAI-compatible)

This directory contains:

- `setup.sh` — one-shot bootstrap. Clones the upstream repo into `./upstream/`,
  installs it into an isolated `uv` venv, writes the `tu-zi` API configuration,
  and runs a smoke test against `gpt-4o-mini`.
- `secrets.env` — created by `setup.sh` on first run (gitignored).
- `secrets.env.example` — template.
- `mini.yaml` — generated. Loaded with `mini -c mini.yaml`. Routes litellm
  at the tu-zi gateway.
- `upstream/` — populated by `setup.sh` (gitignored).
- `.venv/` — populated by `setup.sh` (gitignored).

## Bootstrap

```bash
./setup.sh
```

Re-running is safe and idempotent.

## Running the agent

```bash
source .venv/bin/activate

# Single prompt, yolo (no confirmation), save trajectory:
mini -c mini.yaml -m openai/gpt-4o-mini -y -t "Write a hello-world python script under /tmp/hi.py"

# Use a bigger model for harder tasks:
mini -c mini.yaml -m openai/claude-sonnet-4-5 -y -t "..."

# Verify which models are available on the gateway:
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