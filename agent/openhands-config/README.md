# Component 2 — OpenHands Agent Canvas

Upstream: <https://github.com/OpenHands/OpenHands>
Installed via: `npm install -g @openhands/agent-canvas`
API gateway: <https://api.tu-zi.com> (OpenAI-compatible, configured via the web UI)

## Boundary

| Layer | Owner | Tracked? |
| --- | --- | --- |
| `@openhands/agent-canvas` (global npm install) | npm registry | **No** (system-level) |
| `config/` (our tracked config) | **RQ4** | Yes |

## First-time LLM setup

OpenHands stores LLM settings in an encrypted server-side store. They
cannot be set via environment variables. After `bash agent/run_openhands.sh`:

1. Open <http://localhost:8000> in a browser.
2. Go to **Settings → LLM**.
3. Toggle **Advanced**.
4. Fill in:
   - **Custom Model**: `openai/gpt-4o-mini`
   - **Base URL**: `https://api.tu-zi.com/v1`
   - **API Key**: `sk-52RaA81V3pImnAGLRby5kMbDWVVDcXkZkmBPXlj4D7pUxLvv`
5. Click **Save Changes**.

Subsequent conversations use the saved profile until you delete it.

## Files

- `run_openhands.sh` (parent dir) — wrapper that sources this `.env`,
  then `exec`s `agent-canvas`.
- `.env` — auto-generated API key (`LOCAL_BACKEND_API_KEY`) and secret
  key (`OH_SECRET_KEY`). Gitignored, `chmod 600`.
- `.env.example` — template.
- `smoke_test.sh` — boots the stack, hits `/alive`, tears it down.
