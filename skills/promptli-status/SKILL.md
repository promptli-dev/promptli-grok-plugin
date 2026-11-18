---
name: promptli-status
description: Show this Bot's Promptli Comms identity, email address, phone number, mode and usage. Use when the user asks for the Promptli status, address or number.
---

Call the Promptli Comms `whoami` and `get_usage` tools and report, in at most five short lines: the agent
handle, email address, phone number (or none), live or test mode, and usage against the plan. If a tool
fails with an authorization error, say that Promptli Comms needs **Authenticate** under **Connect apps**.
Never show tokens or keys.
