from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from promptli_gateway.adapter import GatewayContext, TurnDone, TurnError, TurnKind
from promptli_gateway.config import GatewayConfig
from promptli_gateway.framing import frame_email

from promptli_grok.adapter import GrokRoutineAdapter, webhook_url_problem
from promptli_grok.gateway import GrokGateway
from tests.conftest import email_event, text_event, voicemail_event

URL = "https://grok-bot.example.com/routines/rtn_123/webhook"  # fictional; xAI does not document the shape
KEY = "gbk_test_not_a_real_key"
CTX = GatewayContext("glow", "glow@agents.promptli.com", "+15550100000", None)


class FakeGrokBot:
    """Stands in for a routine's webhook trigger: 200 starts a run, anything else means no run."""

    def __init__(self, statuses: list[int] | None = None) -> None:
        self.statuses = statuses or []
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        status = self.statuses.pop(0) if self.statuses else 200
        return httpx.Response(status, text="" if status == 200 else "error")

    def payloads(self) -> list[dict[str, Any]]:
        return [json.loads(r.content) for r in self.requests]


def adapter(fake: Any, **kw: Any) -> GrokRoutineAdapter:
    return GrokRoutineAdapter(URL, KEY, transport=httpx.MockTransport(fake), retry_delays=(0, 0), **kw)


async def turn(a: GrokRoutineAdapter, prompt: str, kind: TurnKind = TurnKind.CHANNEL) -> list[Any]:
    await a.start(CTX, [])
    return [c async for c in a.run_turn("ctc_jane", prompt, kind=kind, resume_id=None)]


@pytest.mark.parametrize(
    ("url", "ok"),
    [
        (URL, True),
        ("https://grok-bot.example.com/hooks/abc?routine=1", True),
        ("http://localhost:8787/webhook", True),
        ("http://grok-bot.example.com/webhook", False),
        ("https://user:pw@grok-bot.example.com/webhook", False),
        ("https://grok-bot.example.com/webhook#x", False),
        ("grok-bot.example.com/webhook", False),
    ],
)
def test_webhook_url_rules(url: str, ok: bool) -> None:
    assert (webhook_url_problem(url) is None) is ok


async def test_delivery_posts_json_with_bearer_key_and_never_auto_replies() -> None:
    fake = FakeGrokBot()
    a = adapter(fake)
    chunks = await turn(a, frame_email(email_event(1, "Hello"), CTX.identity_email))
    assert chunks == [TurnDone(text="NO_REPLY")]
    req = fake.requests[0]
    assert req.method == "POST" and str(req.url) == URL
    assert req.headers["authorization"] == f"Bearer {KEY}"
    assert req.headers["content-type"] == "application/json"
    p = fake.payloads()[0]
    assert p["event"] == "promptli.email" and p["agent"] == "glow" and p["reply"]["message_id"] == "msg_1"
    assert p["delivery_id"] == req.headers["idempotency-key"] and p["untrusted"] is True
    assert KEY not in req.content.decode()
    await a.close()


@pytest.mark.parametrize("status", [500, 502, 503, 429, 408])
async def test_non_200_means_no_run_so_transient_errors_are_retried(status: int) -> None:
    fake = FakeGrokBot(statuses=[status, status])
    chunks = await turn(adapter(fake), frame_email(email_event(1, "Hello"), None))
    assert chunks == [TurnDone(text="NO_REPLY")] and len(fake.requests) == 3
    assert len({json.loads(r.content)["delivery_id"] for r in fake.requests}) == 1


async def test_other_2xx_is_not_treated_as_a_started_run() -> None:
    # xAI: "A 200 response means Grok Bot accepted the call and started a run"; anything else did not.
    fake = FakeGrokBot(statuses=[202])
    chunks = await turn(adapter(fake), frame_email(email_event(1, "Hello"), None))
    assert isinstance(chunks[0], TurnError) and "paused" in chunks[0].message


@pytest.mark.parametrize(("status", "words"), [(401, "key"), (403, "key"), (404, "deleted"), (409, "paused")])
async def test_client_errors_are_not_retried(status: int, words: str) -> None:
    fake = FakeGrokBot(statuses=[status])
    chunks = await turn(adapter(fake), frame_email(email_event(1, "Hello"), None))
    assert isinstance(chunks[0], TurnError) and not chunks[0].retryable and len(fake.requests) == 1
    assert words in chunks[0].message and KEY not in chunks[0].message


async def test_gives_up_after_retries() -> None:
    fake = FakeGrokBot(statuses=[500, 500, 500])
    chunks = await turn(adapter(fake), frame_email(email_event(1, "Hello"), None))
    assert isinstance(chunks[0], TurnError) and chunks[0].retryable and len(fake.requests) == 3


async def test_network_errors_are_retried_with_the_same_delivery_id() -> None:
    calls: list[str] = []

    def flaky(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content)["delivery_id"])
        if len(calls) == 1:
            raise httpx.ReadTimeout("slow", request=request)
        return httpx.Response(200)

    chunks = await turn(adapter(flaky), frame_email(email_event(1, "Hello"), None))
    assert chunks == [TurnDone(text="NO_REPLY")] and len(calls) == 2 and calls[0] == calls[1]


async def test_redirects_are_not_followed_so_the_key_never_leaves_the_host() -> None:
    seen: list[str] = []

    def redirect(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(307, headers={"location": "https://evil.example.net/steal"})

    a = GrokRoutineAdapter(URL, KEY, transport=httpx.MockTransport(redirect), retry_delays=())
    chunks = await turn(a, frame_email(email_event(1, "Hello"), None))
    assert isinstance(chunks[0], TurnError) and seen == [URL]


async def test_voice_and_supervisor_turns_never_reach_the_webhook() -> None:
    fake = FakeGrokBot()
    a = adapter(fake)
    assert a.capabilities.voice is False
    for kind in (TurnKind.VOICE, TurnKind.SUPERVISOR, TurnKind.POST_CALL):
        assert await turn(a, "hello", kind) == [TurnDone(text="NO_REPLY")]
    assert fake.requests == []


def test_refuses_bad_config() -> None:
    with pytest.raises(ValueError, match="https"):
        GrokRoutineAdapter("http://grok-bot.example.com/webhook", KEY)
    with pytest.raises(ValueError, match="key"):
        GrokRoutineAdapter(URL, "")


# ---- the real gateway loop, with a fake Promptli client and a fake Grok Bot ----------------------


class FakeIdentity:
    def __init__(self, log: list[tuple[str, Any]]) -> None:
        self.log = log

    async def reply(self, message_id: str, **kw: Any) -> None:
        self.log.append(("reply", message_id))

    async def send_text(self, to: Any, text: str = "", **_: Any) -> None:
        self.log.append(("text", to))


class FakePromptli:
    def __init__(self) -> None:
        self.log: list[tuple[str, Any]] = []

    def identity(self, _ref: str) -> FakeIdentity:
        return FakeIdentity(self.log)

    async def close(self) -> None:
        return None


class FakeLink:
    def __init__(self) -> None:
        self.acks: list[int] = []

    async def ack(self, seq: int) -> None:
        self.acks.append(seq)


@pytest.fixture(autouse=True)
def _home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROMPTLI_HOME", str(tmp_path))


async def run_gateway(events: list[dict[str, Any]], fake: FakeGrokBot) -> tuple[FakePromptli, FakeLink]:
    cfg = GatewayConfig(runtime="promptli-grok", identity="glow", batch_window_s=0.05, auto_reply=False)
    a = adapter(fake)
    client = FakePromptli()
    gw = GrokGateway(cfg, a, client=client)  # type: ignore[arg-type]
    gw.identity_address, gw.identity_number = CTX.identity_email, CTX.identity_number
    link = FakeLink()
    gw.link = link  # type: ignore[assignment]
    await a.start(CTX, [])
    for e in events:
        await gw.handle_event(e)
    for _ in range(200):
        await asyncio.sleep(0.01)
        if not gw._pending:  # pyright: ignore[reportPrivateUsage]
            break
    await a.close()
    gw.state.close()
    return client, link


async def test_gateway_starts_one_run_per_turn_and_never_sends_itself() -> None:
    fake = FakeGrokBot()
    events = [
        email_event(1, "Can we move to 4pm?"),
        text_event(2, "running late"),
        text_event(3, "10 min"),  # same person within the batch window: one run
        voicemail_event(4, "please call me back"),
    ]
    client, link = await run_gateway(events, fake)
    kinds = sorted(p["event"] for p in fake.payloads())
    assert kinds == ["promptli.email", "promptli.sms", "promptli.voicemail"]
    sms = next(p for p in fake.payloads() if p["event"] == "promptli.sms")
    assert "running late\n10 min" in sms["content"]
    assert client.log == []  # replies come from the Bot's MCP tools, never from the bridge
    assert link.acks and link.acks[-1] == 4
    assert {p["contact_key"] for p in fake.payloads()} == {"ctc_jane", "ctc_bob"}


async def test_same_person_on_two_channels_at_once_gets_both_delivered() -> None:
    fake = FakeGrokBot()
    mail = email_event(1, "see attached")
    mail["data"]["contact_key"] = "ctc_bob"
    await run_gateway([mail, text_event(2, "did you get my email?")], fake)
    assert sorted(p["event"] for p in fake.payloads()) == ["promptli.email", "promptli.sms"]


async def test_gateway_skips_stop_keywords_and_our_own_mail() -> None:
    fake = FakeGrokBot()
    stop = text_event(1, "STOP")
    stop["data"]["keyword"] = "stop"
    own = email_event(2, "loop", sender="glow@agents.promptli.com")
    await run_gateway([stop, own], fake)
    assert fake.requests == []
