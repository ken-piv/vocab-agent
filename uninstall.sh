#!/usr/bin/env bash
set -euo pipefail

echo ""
echo "  Uninstalling Vocab Agent..."
echo ""

PLIST_LABEL="com.vocab-agent.morning"
PLIST_PATH="$HOME/Library/LaunchAgents/$PLIST_LABEL.plist"

# Unload LaunchAgent
launchctl unload "$PLIST_PATH" 2>/dev/null || true
rm -f "$PLIST_PATH"
echo "  ✓ Removed LaunchAgent"

# Remove gatekeeper and symlink
rm -f "$HOME/.local/bin/vocab-check"
rm -f "$HOME/.local/bin/vocab"
echo "  ✓ Removed scripts from ~/.local/bin"

# Remove wakeup hook
rm -f "$HOME/.wakeup"
echo "  ✓ Removed ~/.wakeup"

# Remove .zshrc additions
if grep -q "# --- vocab-agent ---" "$HOME/.zshrc" 2>/dev/null; then
    sed -i '' '/# --- vocab-agent ---/,+2d' "$HOME/.zshrc"
    echo "  ✓ Removed lines from ~/.zshrc"
fi

echo ""
echo "  Done. ~/vocab-agent/ was left in place (your progress is in vocab.db)."
echo "  To remove everything: rm -rf ~/vocab-agent"
echo ""
