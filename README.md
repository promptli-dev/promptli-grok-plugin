# Promptli Comms for Grok Bot

Give your [Grok Bot](https://x.ai/news/introducing-grok-bot) its own email address and phone number. The
Bot can email, text and place AI-disclosed calls, and people who email, text or leave a voicemail for
it start a run of the Bot.

The repository has two parts:

- **The plugin.** These are the files Grok Bot loads: `.cursor-plugin/plugin.json`, `mcp.json`, `skills/`
  and `assets/`. Grok Bot takes plugins from the Cursor Marketplace, so they use the
  [Cursor plugin format](https://cursor.com/docs/plugins). The plugin adds the hosted Promptli Comms MCP
  server (OAuth, so no key pasting), a `promptli-comms` skill, and the `promptli-setup`,
  `promptli-status` and `promptli-doctor` skills. The plugin runs no code. The same payload also has a
  `.grok-plugin/plugin.json` for [Grok Build](https://github.com/xai-org/plugin-marketplace), xAI's
  coding CLI.
- **`promptli-grok`.** This optional bridge service handles inbound mail, texts and voicemail. It holds
  an outbound Agent Link WebSocket to Promptli Comms. For each message a person sends, it starts a run of
  a Grok Bot **routine** through the routine's webhook trigger. That trigger is the documented way for
  an outside service to start Bot work.

```
person ──email/SMS/voicemail──▶ Promptli Comms ──Agent Link──▶ promptli-grok ──routine webhook──▶ Grok Bot run
Grok Bot ──MCP (OAuth)──▶ api.comms.promptli.com/mcp ──▶ reply_email / send_text / place_call
```

## 1. Add the plugin to Grok Bot

1. In Grok Bot, open **Connect apps** (or **Plugins**), search for **Promptli Comms** and choose **Add**.
2. Choose **Authenticate**. In the browser, pick an existing Promptli agent or create one, and add a
   phone number if you want SMS and calls. Grok Bot finds the OAuth server on its own: the server
   supports RFC 9728 and 8414 discovery, dynamic client registration and PKCE.
3. Ask the Bot: `use promptli-status`.

**Before the Marketplace listing is live**, add the server by hand. In the desktop app, open **Connect
apps**, then **Add a custom connector**:
- **Type:** Remote HTTPS
- **URL:** `https://api.comms.promptli.com/mcp`
- **Headers** and **OAuth Client ID:** leave empty

Then choose **Add plugin** and **Authenticate**. The skills only come with the Marketplace plugin.

Team admins: Grok Bot follows your team's Cursor connector policy. Allow the plugin under **Plugins &
MCPs**, or add `https://api.comms.promptli.com/mcp` to the MCP allowlist (Enterprise).

## 2. Answer inbound messages (optional)

Grok Bot has no headless session or SDK API. Outside services can start Bot work only through a
routine's webhook trigger:
- Send `POST <routine URL>` with `Authorization: Bearer <key>` and a JSON body.
- `200` means a run started. Any other answer means no run started.

1. Ask the Bot to `use promptli-setup`. It offers to create a routine named **Promptli Comms inbox**
   with a webhook trigger. Open that routine in the desktop app. Its **Webhook** section shows the
   **POST to** URL and the key.
2. On a Mac or Linux machine that stays on, run:

   ```bash
   curl -fsSL https://comms.promptli.com/install/grok.sh | sh
   promptli-grok setup          # browser login to Promptli, then paste the webhook URL and key
   promptli-grok test-delivery  # starts one test run; check the Bot's chat
   ```

   `setup` first shows the security warning, then logs you in with your browser, so no Promptli key is
   pasted. It asks for the webhook URL, then the key with hidden input. The key can be bare, `Bearer …`,
   or the full header. Both are stored in `~/.promptli/promptli-grok/grok.json` (mode 600). Last,
   `setup` starts the background service: launchd on macOS, `systemd --user` on Linux.

Each run gets one JSON delivery:

| Field | Meaning |
| --- | --- |
| `event` | `promptli.email`, `promptli.sms` or `promptli.voicemail` |
| `delivery_id` | Stays the same when a delivery is retried. The skill tells the Bot to skip one it already handled |
| `contact`, `channel` | Who wrote, and on which channel |
| `content` | The fenced, untrusted message |
| `reply` | The tool to answer with (`reply.tool`), plus `message_id` or `to` |

The Bot replies with the Promptli Comms tools. The bridge never sends anything itself.

**Calls.** Live calls are answered by Promptli's hosted voice assistant for the agent, configured in the
Promptli console. It says it is an AI. A routine run can't answer in real time, so the bridge doesn't
advertise voice. Voicemails come to the Bot as deliveries for follow-up.

**Approvals.** Grok Bot's Auto Review checks each action, and a matching **Ask first** rule shows an
approval card that expires after 30 minutes. If you set an Ask first rule for `reply_email` or
`send_text`, each reply waits for you.

> **Security:** anyone who learns the agent's address or number can start runs of your Bot. Each
> delivery is marked as untrusted data, and the routine's instruction limits replies to the sender. Even
> so, use a Bot made for outside contacts. Give it only the apps it needs, and keep sensitive work in
> another Bot. Grok Bot's docs say Bots that share a computer are not a security boundary.

## Commands (`promptli-grok`)

| Command | What it does |
| --- | --- |
| `setup [--number] [--test] [--no-browser]` | Browser login, routine webhook, start the service. `--test` uses Promptli test mode, where nothing reaches real people |
| `status [--json]` | Agent, address, number, webhook (the key is never shown) and service state |
| `doctor [--json]` | Login, channels, Agent Link, clock, service, webhook config. It never POSTs, because a POST starts a run |
| `test-delivery` | Start one routine run with a `promptli.test` delivery |
| `start` / `stop` / `restart` / `logs -f` / `run -v` | Manage the background service, or run it in the foreground |
| `logout` / `uninstall [--purge]` | Revoke the login and forget the key, or remove the service and local state |

`PROMPTLI_GROK_WEBHOOK_URL` and `PROMPTLI_GROK_WEBHOOK_KEY` override the stored webhook, for containers.
`PROMPTLI_API_KEY` and `PROMPTLI_BASE_URL` work as in the other Promptli plugins.

## How it maps to Grok Bot

| Need | Grok Bot extension point | Here |
| --- | --- | --- |
| Tools | Plugin MCP (remote HTTPS + OAuth), or a custom connector | `mcp.json` → `https://api.comms.promptli.com/mcp` |
| Know-how | Plugin `skills/<name>/SKILL.md` (packaged skills) | `promptli-comms`, `promptli-setup`, `promptli-status`, `promptli-doctor` |
| Inbound | Routine with a webhook trigger (`POST` + `Bearer` key) | `promptli-grok` (Agent Link → webhook) |
| Listing | Cursor Marketplace (Grok Bot loads plugins from it) | See *Publishing* |

Built on `promptli-gateway`, which handles Agent Link, dedupe and acks, per-person queues, framing,
browser login, doctor and autostart. This repo adds only the routine adapter
(`promptli_grok/adapter.py`), the payload (`promptli_grok/payload.py`), the CLI and the plugin files.

Known limits, all from xAI's docs or untested:
- Routines can run at most 200 times an hour each, and 300 times an hour across all routines. Texts
  that arrive in a burst are batched into one run. When Grok Bot answers `429`, the bridge retries.
- Every person's deliveries land in the same Bot chat. The skill tells the Bot to keep people apart by
  `contact`, and to read history with `get_conversation`.
- xAI documents neither the routine webhook's body size limit nor its URL shape. Content is truncated
  at 24,000 characters, and the URL is only checked for https.

## Development

```bash
uv sync
uv run pytest                       # offline: mock HTTP transport, real gateway core, no real messages
uv run ruff check . && uv run ruff format --check . && uv run pyright
python scripts/validate_plugin.py . # Cursor / Grok Bot and Grok Build plugin rules, offline
```

Install from a local checkout: `PROMPTLI_GROK_SOURCE=$PWD sh install.sh`.

## Publishing (maintainers)

1. Test the plugin in Cursor from `~/.cursor/plugins/local/promptli-comms`. Then submit the repo at
   <https://cursor.com/marketplace/publish>. Submissions are reviewed by hand and must be open source.
   Grok Bot loads plugins only from the Cursor Marketplace or dashboard, not from local folders.
2. Once the plugin is listed, add, authenticate and use it in Grok Bot, in Promptli test mode.
3. Publish `promptli-grok` to PyPI (tag `grok-v0.1.0`). Serve `install.sh` at
   `https://comms.promptli.com/install/grok.sh`.
4. Optional, for Grok Build: open a PR to <https://github.com/xai-org/plugin-marketplace> that adds a
   remote entry pinned to a full commit SHA.
5. Optional: a Grok Bot Marketplace listing (<https://x.ai/bot/marketplace>) of an example "Promptli
   inbox" bot template. xAI has no public submission process for it.

## Sources

- <https://x.ai/news/introducing-grok-bot>, <https://x.ai/bot>, <https://x.ai/bot/marketplace>
- <https://docs.x.ai/grok-bot/overview>, [computer-and-apps](https://docs.x.ai/grok-bot/computer-and-apps)
  (custom connectors), [skills-routines-and-automations](https://docs.x.ai/grok-bot/skills-routines-and-automations)
  (webhook triggers), [chat-and-collaboration](https://docs.x.ai/grok-bot/chat-and-collaboration),
  [teams-and-enterprises](https://docs.x.ai/grok-bot/teams-and-enterprises),
  [approvals-security-and-privacy](https://docs.x.ai/grok-bot/approvals-security-and-privacy)
- <https://cursor.com/docs/plugins>, <https://github.com/cursor/plugin-template>
- <https://github.com/xai-org/plugin-marketplace>
- A third-party plugin that ships for Grok Bot: <https://docs.railway.com/ai/grok-bot-plugin>,
  <https://github.com/railwayapp/railway-skills>

## License

MIT
