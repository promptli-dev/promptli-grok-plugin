from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from promptli_gateway.config import GatewayConfig
from promptli_gateway.setup.bootstrap import BootstrapResult
from typer.testing import CliRunner

from promptli_grok import cli
from promptli_grok.settings import GrokSettings, settings_path

runner = CliRunner()
URL = "https://grok-bot.example.com/routines/rtn_123/webhook"
KEY = "gbk_test_not_a_real_key"


@pytest.fixture(autouse=True)
def _home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROMPTLI_HOME", str(tmp_path))
    for var in ("PROMPTLI_API_KEY", "PROMPTLI_GROK_WEBHOOK_URL", "PROMPTLI_GROK_WEBHOOK_KEY"):
        monkeypatch.delenv(var, raising=False)
    # never touch the real launchd / systemd
    monkeypatch.setattr(cli, "install_autostart", lambda *a, **k: "fake-unit")
    monkeypatch.setattr(cli, "uninstall_autostart", lambda _r: False)
    monkeypatch.setattr(cli, "autostart_status", lambda _r: (False, "not installed"))


def test_version() -> None:
    r = runner.invoke(cli.app, ["version"])
    assert r.exit_code == 0 and "promptli-grok 0.1.1" in r.output


def test_unconfigured_status_doctor_and_run() -> None:
    r = runner.invoke(cli.app, ["status", "--json"])
    assert r.exit_code == 0 and json.loads(r.output)["configured"] is False
    assert runner.invoke(cli.app, ["doctor"]).exit_code == 1
    assert runner.invoke(cli.app, ["run"]).exit_code == 2


def test_setup_requires_accepting_the_warning() -> None:
    r = runner.invoke(cli.app, ["setup"], input="n\n")
    assert r.exit_code == 1 and "Anyone who knows" in r.output


@pytest.mark.parametrize("pasted", [KEY, f"Bearer {KEY}", f"Authorization: Bearer {KEY}"])
def test_setup_with_browser_login_stores_webhook_privately_and_never_echoes_the_key(
    pasted: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_bootstrap(**kw: Any) -> BootstrapResult:
        GatewayConfig(runtime="promptli-grok", identity="glow").save(api_key="psk_test_x")
        return BootstrapResult(status="ok", identity="glow", env="test", email_address="glow@agents.x")

    monkeypatch.setattr(cli, "_browser_login", lambda *a, **k: object())
    monkeypatch.setattr(cli, "bootstrap", fake_bootstrap)
    r = runner.invoke(
        cli.app, ["setup", "--yes", "--test"], input=f"http://example.com/nope\n{URL}\n{pasted}\n"
    )
    assert r.exit_code == 0, r.output
    assert KEY not in r.output and "use https" in r.output and "Promptli Comms inbox" in r.output
    assert settings_path().stat().st_mode & 0o777 == 0o600
    assert GrokSettings.load() == GrokSettings(URL, KEY)
    cfg = GatewayConfig.load("promptli-grok")
    assert cfg is not None and cfg.auto_reply is False and cfg.extra["supervise"] is False
    assert "Background service started" in r.output


def test_status_redacts_the_key() -> None:
    GatewayConfig(runtime="promptli-grok", identity="glow", base_url="http://127.0.0.1:9").save(
        api_key="psk_test_x"
    )
    GrokSettings(URL, KEY).save()
    r = runner.invoke(cli.app, ["status", "--json"])
    data = json.loads(r.output)
    assert data["grok"] == {"webhook_url": URL, "webhook_key": "set"} and KEY not in r.output


def test_env_overrides_stored_webhook(monkeypatch: pytest.MonkeyPatch) -> None:
    GrokSettings(URL, KEY).save()
    monkeypatch.setenv("PROMPTLI_GROK_WEBHOOK_KEY", "gbk_test_from_env")
    s = GrokSettings.load()
    assert s is not None and s.webhook_key == "gbk_test_from_env"


async def test_grok_check_reports_missing_bad_and_good_urls(monkeypatch: pytest.MonkeyPatch) -> None:
    ok, detail = await cli.grok_check()
    assert not ok and "run setup" in detail
    monkeypatch.setenv("PROMPTLI_GROK_WEBHOOK_URL", "http://grok-bot.example.com/webhook")
    monkeypatch.setenv("PROMPTLI_GROK_WEBHOOK_KEY", KEY)
    ok, detail = await cli.grok_check()
    assert not ok and "https" in detail
    monkeypatch.setenv("PROMPTLI_GROK_WEBHOOK_URL", "https://localhost/webhook")
    ok, detail = await cli.grok_check()
    assert ok and "localhost" in detail


def test_test_delivery_posts_one_promptli_test_event(monkeypatch: pytest.MonkeyPatch) -> None:
    GrokSettings(URL, KEY).save()
    seen: list[dict[str, Any]] = []

    def fake(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200)

    real = cli.GrokRoutineAdapter
    monkeypatch.setattr(
        cli, "GrokRoutineAdapter", lambda *a, **k: real(*a, **k, transport=httpx.MockTransport(fake))
    )
    r = runner.invoke(cli.app, ["test-delivery", "--yes"])
    assert r.exit_code == 0, r.output
    assert len(seen) == 1 and seen[0]["event"] == "promptli.test" and KEY not in r.output


def test_clean_key_accepts_the_header_forms() -> None:
    assert cli.clean_key(f"  Authorization: Bearer {KEY} ") == KEY
    assert cli.clean_key(f"bearer {KEY}") == KEY


def test_logout_forgets_the_key_and_purge_removes_state(tmp_path: Path) -> None:
    GatewayConfig(runtime="promptli-grok", identity="glow").save(api_key="psk_test_x")
    GrokSettings(URL, KEY).save()
    assert runner.invoke(cli.app, ["logout", "--yes"]).exit_code == 0
    assert not settings_path().exists()
    assert runner.invoke(cli.app, ["uninstall", "--purge", "--yes"]).exit_code == 0
    assert not (tmp_path / "promptli-grok").exists()
