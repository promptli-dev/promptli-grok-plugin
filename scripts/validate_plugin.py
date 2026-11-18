"""Offline check of the plugin files for Grok Bot (Cursor plugin format) and Grok Build (.grok-plugin).

Grok Bot loads plugins from the Cursor Marketplace, so the Cursor rules apply: they mirror
`scripts/validate-template.mjs` in https://github.com/cursor/plugin-template (marketplace and plugin
names, relative paths, skill frontmatter). The Grok Build rules follow the README and CONTRIBUTING of
https://github.com/xai-org/plugin-marketplace. On top, Promptli's own rules: one remote https MCP server
with no credentials or placeholders, one version across manifests, no secrets in plugin files.

Usage: python scripts/validate_plugin.py [repo_dir]   (exit 1 with one line per problem)
"""

from __future__ import annotations

import json
import posixpath
import re
import sys
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit

PLUGIN_NAME = re.compile(r"^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$")
KEBAB = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")
PATH_FIELDS = ("logo", "rules", "skills", "agents", "commands", "hooks", "mcpServers")
SECRET = re.compile(r"(psk_(live|test)_[A-Za-z0-9]{8,}|sk-[A-Za-z0-9]{20,}|sk_live_|whsec_[A-Za-z0-9]{8,})")
PLACEHOLDER = re.compile(r"\$\{[A-Za-z_][A-Za-z0-9_]*\}")
MCP_URL = "https://api.comms.promptli.com/mcp"


def frontmatter(text: str) -> dict[str, str] | None:
    m = re.match(r"^---\r?\n(.*?)\r?\n---\r?\n", text, re.S)
    if not m:
        return None
    fields: dict[str, str] = {}
    for line in m.group(1).splitlines():
        if ":" in line and not line.startswith((" ", "\t", "#")):
            k, v = line.split(":", 1)
            fields[k.strip()] = v.strip().strip("\"'")
    return fields


def _load(p: Path, errors: list[str]) -> dict[str, Any] | None:
    try:
        doc: Any = json.loads(p.read_text())
    except FileNotFoundError:
        errors.append(f"{p.name} is missing ({p})")
        return None
    except json.JSONDecodeError as e:
        errors.append(f"{p}: invalid JSON ({e})")
        return None
    if not isinstance(doc, dict):
        errors.append(f"{p}: must be a JSON object")
        return None
    return doc  # pyright: ignore[reportUnknownVariableType]


def _safe_relative(value: str) -> bool:
    if value.startswith(("http://", "https://")):
        return True
    if not value or value.startswith("/"):
        return False
    norm = posixpath.normpath(value.replace("\\", "/"))
    return norm != ".." and not norm.startswith("../")


def _paths(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [p for v in value for p in _paths(v)]  # pyright: ignore[reportUnknownVariableType]
    if isinstance(value, dict):
        d = cast("dict[str, Any]", value)
        return [str(d[k]) for k in ("path", "file") if isinstance(d.get(k), str)]
    return []


def check_manifest(root: Path, manifest: Path, errors: list[str]) -> dict[str, Any] | None:
    doc = _load(manifest, errors)
    if doc is None:
        return None
    label = manifest.relative_to(root).as_posix()
    if not isinstance(doc.get("name"), str) or not PLUGIN_NAME.match(doc["name"]):
        errors.append(f"{label}: invalid name (lowercase letters, digits, '-' and '.')")
    for field in PATH_FIELDS:
        for value in _paths(doc.get(field)):
            if not _safe_relative(value):
                errors.append(f'{label}: field "{field}" has unsafe path "{value}"')
            elif not value.startswith("http") and not (root / value).exists():
                errors.append(f'{label}: field "{field}" references missing path "{value}"')
    return doc


def check_cursor(root: Path, errors: list[str]) -> dict[str, Any] | None:
    market = _load(root / ".cursor-plugin" / "marketplace.json", errors)
    if market is None:
        return None
    if not isinstance(market.get("name"), str) or not KEBAB.match(market["name"]):
        errors.append("marketplace.json: name must be lowercase kebab-case")
    if not (market.get("owner") or {}).get("name"):
        errors.append('marketplace.json: "owner.name" is required')
    plugins: list[dict[str, Any]] = market.get("plugins") or []
    if len(plugins) != 1:
        errors.append("marketplace.json: expected exactly one plugin entry")
        return None
    entry = plugins[0]
    if entry.get("source") not in ("./", "."):
        errors.append("marketplace.json: the plugin source must be the repo root ('./')")
    doc = check_manifest(root, root / ".cursor-plugin" / "plugin.json", errors)
    if doc and doc.get("name") != entry.get("name"):
        errors.append("marketplace.json: entry name does not match .cursor-plugin/plugin.json")
    for f in ("description", "version", "author"):
        if doc is not None and not doc.get(f):
            errors.append(f".cursor-plugin/plugin.json: {f} is required for the Marketplace listing")
    return doc


def check_grok(root: Path, errors: list[str]) -> dict[str, Any] | None:
    doc = check_manifest(root, root / ".grok-plugin" / "plugin.json", errors)
    if doc is None:
        return None
    for f in ("description", "homepage", "license"):
        if not doc.get(f):
            errors.append(f".grok-plugin/plugin.json: {f} is required by the xAI marketplace checklist")
    if not (root / "README.md").exists():
        errors.append("README.md is required by the xAI marketplace checklist")
    return doc


def check_mcp(root: Path, errors: list[str]) -> None:
    doc = _load(root / "mcp.json", errors)
    if doc is None:
        return
    servers: dict[str, Any] = doc.get("mcpServers") or {}
    if list(servers) != ["promptli"]:
        errors.append("mcp.json: expected exactly one server named 'promptli'")
        return
    s = servers["promptli"]
    if s.get("type") != "http" or "command" in s:
        errors.append("mcp.json: the promptli server must be a remote 'http' server (no local command)")
    url = str(s.get("url", ""))
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.username or parts.query:
        errors.append("mcp.json: url must be https with no credentials or query")
    if url != MCP_URL:
        errors.append(f"mcp.json: url must be {MCP_URL}")
    if "headers" in s or "env" in s:
        errors.append("mcp.json: no headers or env (OAuth is discovered from the server)")
    if PLACEHOLDER.search(json.dumps(doc)):
        errors.append("mcp.json: placeholders like ${VAR} are not allowed")


def check_skills(root: Path, errors: list[str]) -> None:
    skills = sorted((root / "skills").glob("*/SKILL.md"))
    if not skills:
        errors.append("skills/: no SKILL.md found")
    for p in skills:
        fm = frontmatter(p.read_text())
        label = p.relative_to(root).as_posix()
        if fm is None:
            errors.append(f"{label}: missing YAML frontmatter")
            continue
        for key in ("name", "description"):
            if not fm.get(key):
                errors.append(f'{label}: missing "{key}" in frontmatter')
        if fm.get("name") and fm["name"] != p.parent.name:
            errors.append(f"{label}: name must match its folder ({p.parent.name})")


def check_secrets(root: Path, errors: list[str]) -> None:
    files = [root / "mcp.json", *root.glob(".*-plugin/*.json"), *root.glob("skills/**/*")]
    for p in files:
        if p.is_file() and SECRET.search(p.read_text(errors="replace")):
            errors.append(f"{p.relative_to(root).as_posix()}: looks like it contains a secret")


def validate(root: Path) -> list[str]:
    errors: list[str] = []
    cursor = check_cursor(root, errors)
    grok = check_grok(root, errors)
    check_mcp(root, errors)
    check_skills(root, errors)
    check_secrets(root, errors)
    versions = {d.get("version") for d in (cursor, grok) if d is not None}
    if len(versions) > 1:
        errors.append(f"manifests disagree on version: {sorted(map(str, versions))}")
    return errors


def main() -> None:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    errors = validate(root)
    for e in errors:
        print(e)
    if errors:
        sys.exit(1)
    print("plugin files ok (Cursor / Grok Bot and Grok Build)")


if __name__ == "__main__":
    main()
