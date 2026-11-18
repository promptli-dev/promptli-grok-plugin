---
name: promptli-doctor
description: Diagnose why Promptli Comms email, texts or inbound deliveries are not working for this Grok Bot. Use when Promptli tools fail or people's messages are not reaching the Bot.
---

Check each item and report one line per check, marked ok or FAIL, with the fix for each failure:

1. **Tools**: call `whoami`. An authorization error means **Authenticate** on Promptli Comms under
   **Connect apps**; "Disabled by team admin" means a team admin must allow the plugin or add
   `https://api.comms.promptli.com/mcp` to the team's MCP allowlist.
2. **Mode**: live or test. In test mode messages are simulated.
3. **Number**: does the agent have a phone number? Without one, texts and calls are unavailable.
4. **Recent activity**: call `list_conversations` with a limit of 5. If people wrote in recently but no
   `promptli.*` delivery started a run, the bridge is not delivering: check that the "Promptli Comms
   inbox" routine exists, is not paused, and still has its webhook trigger, then on the machine running
   the bridge run `promptli-grok doctor` and `promptli-grok test-delivery`.
5. **Approvals**: if replies were proposed but not sent, they are waiting on an approval card or an
   **Ask first** rule.

Never ask for or display keys, tokens or passwords. Do not send any message or place any call while
diagnosing.
