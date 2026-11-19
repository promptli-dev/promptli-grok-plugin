#!/bin/sh
# Promptli Comms for Grok Bot: installer for the inbound bridge `promptli-grok`.
#
#   curl -fsSL https://comms.promptli.com/install/grok.sh | sh
#
# Installs `promptli-grok` into its own virtualenv (~/.local/share/promptli-grok/venv) and links it to
# ~/.local/bin. It never asks for or stores a key: run `promptli-grok setup` afterwards.
# The Grok Bot plugin itself (MCP tools + skills) is added inside Grok Bot: Connect apps → Promptli Comms.
#
# Environment overrides:
#   PROMPTLI_GROK_SOURCE   pip requirement or local path for this package (default: GitHub main)
#   PROMPTLI_COMMS_REF     install the SDK/gateway from this git ref instead of PyPI (development)
#   PROMPTLI_COMMS_SOURCE  git URL used with PROMPTLI_COMMS_REF          (default: GitHub)
set -eu

COMMS_SOURCE="${PROMPTLI_COMMS_SOURCE:-https://github.com/promptli-dev/promptli-comms}"
COMMS_REF="${PROMPTLI_COMMS_REF:-}"
PKG_SOURCE="${PROMPTLI_GROK_SOURCE:-git+https://github.com/promptli-dev/promptli-grok-plugin@main}"
DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/promptli-grok"
VENV="$DATA_DIR/venv"
BIN_DIR="$HOME/.local/bin"

say() { printf '\033[1;38;5;202m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33mwarning:\033[0m %s\n' "$*" >&2; }
die() { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }

case "$(uname -s)" in
  Darwin) ;;
  Linux) ;;
  *) die "unsupported OS: $(uname -s)" ;;
esac

if ! command -v uv >/dev/null 2>&1; then
  if [ -x "$HOME/.local/bin/uv" ]; then
    PATH="$HOME/.local/bin:$PATH"
  else
    say "Installing uv (Python package manager from astral.sh)"
    curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null
    PATH="$HOME/.local/bin:$PATH"
  fi
fi
command -v uv >/dev/null 2>&1 || die "uv is required: https://docs.astral.sh/uv/"

say "Creating $VENV"
mkdir -p "$DATA_DIR" "$BIN_DIR"
uv venv --quiet --allow-existing --python ">=3.11" "$VENV"

say "Installing promptli-grok"
if [ -n "$COMMS_REF" ]; then  # development: SDK + gateway from a git ref
  set -- "promptli[cli] @ git+$COMMS_SOURCE@$COMMS_REF#subdirectory=sdk/python" \
    "promptli-gateway @ git+$COMMS_SOURCE@$COMMS_REF#subdirectory=gateway"
else  # released packages from PyPI
  set -- "promptli[cli]>=0.2.2,<0.3" "promptli-gateway>=0.2.2,<0.3"
fi
uv pip install --quiet --no-sources --python "$VENV/bin/python" "$@" "$PKG_SOURCE"

ln -sf "$VENV/bin/promptli-grok" "$BIN_DIR/promptli-grok"
"$BIN_DIR/promptli-grok" version >/dev/null || die "install failed: promptli-grok does not run"

case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) warn "$BIN_DIR is not on your PATH. Add it: echo 'export PATH=\"$BIN_DIR:\$PATH\"' >> ~/.zshrc" ;;
esac

say "Installed $("$BIN_DIR/promptli-grok" version)"
cat <<'MSG'

Next:
  1. In Grok Bot: Connect apps → Promptli Comms → Add → Authenticate (tools + skills).
  2. Ask the Bot to "use promptli-setup"; it creates the "Promptli Comms inbox" webhook routine.
  3. promptli-grok setup          log in with your browser, paste the routine's webhook URL and key
  4. promptli-grok test-delivery  start one test run, then check the Bot's chat

Anyone who learns your agent's address or number can start runs of that Bot. Use a Bot made for
outside contacts, with only the apps it needs.
MSG
