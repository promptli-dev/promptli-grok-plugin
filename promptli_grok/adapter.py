"""GrokRoutineAdapter: hands each Promptli Comms turn to a Grok Bot routine through its webhook trigger.

Grok Bot has no public SDK or headless session API. The documented way for an outside service to start
Bot work is a routine with a **Webhook** trigger: `POST <routine URL>` with `Authorization: Bearer <key>`
and an optional JSON body, which "the Bot receives with the routine instruction". Per xAI's docs, a `200`
means Grok Bot accepted the call and started a run, and any other response means no run started (paused
routine or stale key). See https://docs.x.ai/grok-bot/skills-routines-and-automations.

The webhook is one-way: there is no streamed answer to send back. A turn is "done" once Grok Bot
accepted it, and nothing is auto-replied; the Bot answers people with the Promptli Comms MCP tools from
the plugin. Live calls are not routed here: Promptli's hosted voice assistant answers them (it says it is
an AI), and voicemails arrive as deliveries for follow-up.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Any, cast
from urllib.parse import urlsplit

import httpx
from promptli_gateway.adapter import (
    AdapterCapabilities,
    GatewayContext,
    TurnChunk,
    TurnDone,
    TurnError,
    TurnKind,
)
from promptli_gateway.tools import ToolSpec

from promptli_grok import __version__
from promptli_grok.payload import build_payload, delivery_id

log = logging.getLogger("promptli.grok")

RUNTIME = "promptli-grok"
NO_REPLY = "NO_REPLY"
LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")


class RunNotStarted(Exception):
    """Grok Bot answered, but not with 200: no run started."""

    def __init__(self, status: int) -> None:
        super().__init__(f"HTTP {status}")
        self.status = status


def webhook_url_problem(url: str) -> str | None:
    """None when `url` looks like a routine webhook URL we may send the key to, else the reason.

    xAI does not document the shape of routine webhook URLs, so only transport rules are enforced."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return "not a URL"
    if not parts.scheme or not parts.hostname:
        return "not a URL (copy the full 'POST to' URL from the routine's Webhook section)"
    if parts.username or parts.password:
        return "the URL must not contain credentials"
    local = parts.hostname in LOCAL_HOSTS
    if parts.scheme != "https" and not (parts.scheme == "http" and local):
        return "use https (http is only allowed for localhost)"
    if parts.fragment:
        return "the URL must not have a fragment"
    return None


def explain_status(status: int) -> tuple[str, bool]:
    """(message, retryable) for a non-200 answer. Non-200 means no run started, so retrying is safe."""
    if status in (401, 403):
        return f"Grok Bot refused the webhook key (HTTP {status}); copy the current key and run setup", False
    if status == 404:
        return "Grok Bot does not know this routine URL (HTTP 404); was the routine deleted?", False
    if status == 429:
        return "Grok Bot rate-limited the routine (HTTP 429; routines run at most 200 times an hour)", True
    if status == 408 or status >= 500:
        return f"Grok Bot returned HTTP {status}", True
    return f"Grok Bot did not start a run (HTTP {status}); check that the routine is not paused", False


class GrokRoutineAdapter:
    name = "grok-bot"
    capabilities = AdapterCapabilities(
        streams_text=False, native_tools=False, resumable_sessions=False, interruptible=False, voice=False
    )

    def __init__(
        self,
        url: str,
        secret: str,
        *,
        timeout: float = 30.0,
        retry_delays: tuple[float, ...] = (2.0, 10.0, 30.0, 120.0),
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        problem = webhook_url_problem(url)
        if problem:
            raise ValueError(f"Grok Bot webhook URL: {problem}")
        if not secret:
            raise ValueError("Grok Bot webhook key is missing")
        self.url = url
        self._headers = {
            "Authorization": f"Bearer {secret}",
            "Content-Type": "application/json",
            "User-Agent": f"promptli-grok/{__version__}",
        }
        # Never follow redirects: the bearer key must only ever go to the URL the user pasted.
        self._client = httpx.AsyncClient(timeout=timeout, transport=transport, follow_redirects=False)
        self.retry_delays = retry_delays
        self.ctx: GatewayContext | None = None
        self.delivered = 0

    async def start(self, ctx: GatewayContext, tools: list[ToolSpec]) -> None:
        # The Bot gets the Promptli tools from the plugin's hosted MCP server, not from this process.
        self.ctx = ctx

    async def deliver(self, payload: dict[str, Any], key: str) -> dict[str, Any]:
        """POST one body. Returns the (possibly empty) JSON answer; raises RunNotStarted on non-200."""
        res = await self._client.post(
            self.url, json=payload, headers={**self._headers, "Idempotency-Key": key}
        )
        if res.status_code != 200:
            raise RunNotStarted(res.status_code)
        try:
            body: Any = res.json() if res.content else {}
        except ValueError:
            body = {}
        return cast("dict[str, Any]", body) if isinstance(body, dict) else {}

    async def run_turn(
        self, session_key: str, prompt: str, *, kind: TurnKind, resume_id: str | None
    ) -> AsyncIterator[TurnChunk]:
        if kind is not TurnKind.CHANNEL:
            yield TurnDone(text=NO_REPLY)  # calls are answered by the hosted assistant, not the Bot
            return
        identity = self.ctx.identity_handle if self.ctx else None
        payload = build_payload(session_key, prompt, identity=identity)
        key = delivery_id(session_key, prompt)
        error: TurnError | None = None
        # The gateway acks a turn once it ends, so retry here: a Grok Bot hiccup must not drop a message.
        # A non-200 answer means no run started, so those retries cannot double-run the Bot.
        for delay in (*self.retry_delays, None):
            error = await self._attempt(payload, key)
            if error is None or not error.retryable or delay is None:
                break
            log.warning("%s; retrying in %.0fs", error.message, delay)
            await asyncio.sleep(delay)
        if error is not None:
            yield error
            return
        self.delivered += 1
        log.info("started a Grok Bot run for a %s from %s", payload["channel"], payload["contact_key"])
        yield TurnDone(text=NO_REPLY)

    async def _attempt(self, payload: dict[str, Any], key: str) -> TurnError | None:
        try:
            await self.deliver(payload, key)
        except RunNotStarted as e:
            message, retryable = explain_status(e.status)
            return TurnError(message, retryable=retryable)
        except httpx.HTTPError as e:
            # A timeout after sending is ambiguous; the Bot skips a delivery_id it already handled.
            return TurnError(f"Grok Bot unreachable: {type(e).__name__}", retryable=True)
        return None

    async def interrupt(self, session_key: str) -> None:
        return None

    async def reset_session(self, session_key: str) -> None:
        return None

    async def close(self) -> None:
        await self._client.aclose()
