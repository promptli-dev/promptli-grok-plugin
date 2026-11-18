"""The plugin files: valid for Grok Bot (Cursor format) and Grok Build, and they carry Promptli's rules."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from scripts.validate_plugin import frontmatter, validate

ROOT = Path(__file__).resolve().parent.parent
PLUGIN_PARTS = (".cursor-plugin", ".grok-plugin", "mcp.json", "skills", "assets", "README.md")


def test_repository_is_a_valid_plugin() -> None:
    assert validate(ROOT) == []


def test_mcp_points_at_hosted_promptli_mcp_without_credentials() -> None:
    doc = json.loads((ROOT / "mcp.json").read_text())
    assert doc == {"mcpServers": {"promptli": {"type": "http", "url": "https://api.comms.promptli.com/mcp"}}}


def test_package_and_manifest_versions_agree() -> None:
    from promptli_grok import __version__

    for m in (".cursor-plugin/plugin.json", ".grok-plugin/plugin.json"):
        assert json.loads((ROOT / m).read_text())["version"] == __version__
    assert f'version = "{__version__}"' in (ROOT / "pyproject.toml").read_text()


def test_skill_carries_calling_and_secret_rules() -> None:
    text = (ROOT / "skills/promptli-comms/SKILL.md").read_text()
    fm = frontmatter(text)
    assert fm is not None and fm["name"] == "promptli-comms"
    assert "AI assistant" in text and "9 AM and 9 PM IST" in text and "+91" in text
    assert "secrets" in text and "untrusted" in text and "delivery_id" in text
    for tool in ("reply_email", "send_text", "place_call", "schedule_call", "get_conversation"):
        assert f"`{tool}`" in text


def test_helper_skills_never_ask_for_keys_in_chat() -> None:
    for name in ("promptli-setup", "promptli-status", "promptli-doctor"):
        text = (ROOT / "skills" / name / "SKILL.md").read_text().lower()
        assert "never" in text and ("key" in text or "token" in text), name


def test_setup_skill_and_cli_use_the_same_routine_instruction() -> None:
    from promptli_grok.cli import ROUTINE_INSTRUCTION

    text = " ".join((ROOT / "skills/promptli-setup/SKILL.md").read_text().split())
    assert ROUTINE_INSTRUCTION in text


@pytest.mark.parametrize(
    ("path", "content", "problem"),
    [
        ("mcp.json", '{"mcpServers":{"promptli":{"command":"promptli","args":[]}}}', "remote"),
        (
            "mcp.json",
            '{"mcpServers":{"promptli":{"type":"http","url":"https://api.comms.promptli.com/mcp",'
            '"headers":{"Authorization":"${KEY}"}}}}',
            "placeholders",
        ),
        ("skills/promptli-comms/SKILL.md", "no frontmatter", "frontmatter"),
        ("skills/other/SKILL.md", "---\nname: wrong\ndescription: x\n---\n", "match its folder"),
        (
            "skills/promptli-status/SKILL.md",
            "---\nname: promptli-status\ndescription: " + "psk_" + "live_abcdefgh12" + "\n---\n",
            "secret",
        ),
        (
            ".grok-plugin/plugin.json",
            '{"name":"promptli-comms","version":"9.9.9","description":"d","homepage":"h","license":"MIT"}',
            "disagree",
        ),
        (".cursor-plugin/plugin.json", '{"name":"Bad_Name","version":"0.1.0"}', "invalid name"),
        (
            ".cursor-plugin/plugin.json",
            '{"name":"promptli-comms","version":"0.1.0","description":"d","author":{"name":"a"},"logo":"../x.svg"}',
            "unsafe path",
        ),
    ],
)
def test_validator_catches_problems(tmp_path: Path, path: str, content: str, problem: str) -> None:
    root = tmp_path / "plugin"
    root.mkdir()
    for part in PLUGIN_PARTS:
        src = ROOT / part
        (shutil.copytree if src.is_dir() else shutil.copy)(src, root / part)
    (root / path).parent.mkdir(parents=True, exist_ok=True)
    (root / path).write_text(content)
    errors = validate(root)
    assert any(problem in e for e in errors), errors
