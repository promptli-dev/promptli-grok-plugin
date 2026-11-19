# AGENTS.md: promptli-grok-plugin

Promptli Comms for xAI's Grok Bot. Keep this repo thin: transport, dedupe, per-person queues, framing,
setup and doctor belong in `promptli-gateway` (promptli-comms repo), not here.

- Plugin files (what Grok Bot loads, via the Cursor Marketplace): `.cursor-plugin/plugin.json`,
  `.cursor-plugin/marketplace.json`, `mcp.json` (hosted MCP, OAuth), `skills/`, `assets/logo.svg`.
  `.grok-plugin/plugin.json` describes the same payload for Grok Build (xAI plugin marketplace).
- `promptli_grok/adapter.py`: GrokRoutineAdapter (Agent Link turn → POST to a routine's webhook trigger).
- `promptli_grok/payload.py`: the JSON body (`promptli.email|sms|voicemail`, `delivery_id`, reply hint).
- `promptli_grok/cli.py`: `promptli-grok` Typer CLI (runtime id / config dir: `promptli-grok`).
- `install.sh`: curl installer (own venv under ~/.local/share/promptli-grok, shim in ~/.local/bin).

Rules:
- Never print, log or commit API keys or the webhook key. Keys come from hidden input or env, never argv.
- The bridge never sends messages itself (`auto_reply` is off); the Bot replies with MCP tools.
- Never follow redirects with the webhook key. Doctor must not POST to the webhook (that starts a run).
- Keep the version equal in `pyproject.toml`, `promptli_grok/__init__.py` and both plugin manifests.
- Checks: `uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest`
  and `python scripts/validate_plugin.py .`.
