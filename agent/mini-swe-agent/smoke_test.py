"""Smoke test: verify mini-swe-agent can drive a tool-calling round trip
through the tu-zi gateway.

Bypasses the full agent loop (which needs a TTY for `interactive` mode)
and instead drives LitellmModel directly — that's the part that actually
talks to the gateway.
"""
import os
import sys

# Belt-and-suspenders: also set OPENAI_API_BASE so any litellm internals
# that bypass model_kwargs still find the right endpoint.
os.environ.setdefault("OPENAI_API_BASE",  os.environ["TUZI_BASE_URL"])
os.environ.setdefault("OPENAI_API_KEY",   os.environ["TUZI_API_KEY"])

from minisweagent.models.litellm_model import LitellmModel

model = LitellmModel(
    model_name=os.environ.get("DEFAULT_MODEL", "openai/gpt-4o-mini"),
    model_kwargs={
        "api_base": os.environ["TUZI_BASE_URL"],
        "api_key":  os.environ["TUZI_API_KEY"],
        "drop_params": True,
    },
)

result = model.query(
    [{"role": "user", "content": "Run `echo PONG` and report the output."}]
)

extra = result.get("extra", {})
actions = extra.get("actions", [])
response = extra.get("response", {})

if not actions:
    print("FAIL: model returned no tool call", file=sys.stderr)
    print(json.dumps(response, indent=2, default=str)[:2000], file=sys.stderr)
    sys.exit(1)

cmd = actions[0].get("command", "")
print(f"OK: model returned bash tool call -> {cmd!r}", file=sys.stderr)
print("SMOKE_OK", file=sys.stderr)
