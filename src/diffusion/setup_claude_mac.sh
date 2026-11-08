#!/usr/bin/env bash
# Optional: Claude Code CLI and persistent PATH. Authentication remains manual.
set -euo pipefail
BIN_DIR="$HOME/.local/bin"
CLAUDE="$BIN_DIR/claude"
if [[ ! -x "$CLAUDE" ]]; then
    echo "Installing Claude Code CLI via official installer..."
    curl -fsSL https://claude.ai/install.sh | bash
fi
if [[ ! -x "$CLAUDE" ]]; then
    echo "Claude executable not found: $CLAUDE" >&2
    exit 1
fi
path_line='export PATH="$HOME/.local/bin:$PATH"'
if [[ "$SHELL" == *"/zsh" ]]; then
    profile="$HOME/.zprofile"
else
    profile="$HOME/.bash_profile"
fi
touch "$profile"
if ! grep -Fqx "$path_line" "$profile"; then
    printf '\n%s\n' "$path_line" >> "$profile"
    echo "PATH registered in $profile"
fi
export PATH="$BIN_DIR:$PATH"
"$CLAUDE" --version
echo "Claude CLI PATH ready. Open a new terminal then: claude auth login"
echo "To verify login: claude auth status"
