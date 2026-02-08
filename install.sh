#!/usr/bin/env bash
set -euo pipefail

VOCAB_DIR="$HOME/vocab-agent"
BIN_DIR="$HOME/.local/bin"
LAUNCH_AGENTS="$HOME/Library/LaunchAgents"
PLIST_LABEL="com.vocab-agent.morning"
PLIST_PATH="$LAUNCH_AGENTS/$PLIST_LABEL.plist"

echo ""
echo "  ╔══════════════════════════════════════╗"
echo "  ║       Vocab Agent — Installer        ║"
echo "  ╚══════════════════════════════════════╝"
echo ""

# --- Check Python 3 ---
if ! command -v python3 &>/dev/null; then
    echo "  ERROR: python3 is required but not found."
    echo "  Install it with: brew install python3"
    exit 1
fi

# --- Check that we're running from the repo ---
if [[ ! -f "$VOCAB_DIR/vocab_agent.py" ]]; then
    echo "  ERROR: vocab_agent.py not found in $VOCAB_DIR"
    echo "  Clone the repo to ~/vocab-agent first:"
    echo "    git clone https://github.com/ken-piv/vocab-agent.git ~/vocab-agent"
    exit 1
fi

echo "  [1/6] Making script executable..."
chmod +x "$VOCAB_DIR/vocab_agent.py"

echo "  [2/6] Setting up ~/.local/bin..."
mkdir -p "$BIN_DIR"

# --- Create vocab-check gatekeeper ---
cat > "$BIN_DIR/vocab-check" << 'GATEKEEPER'
#!/usr/bin/env bash
set -euo pipefail

VOCAB_DIR="$HOME/vocab-agent"
TODAY=$(date +%Y-%m-%d)
STAMP_FILE="$VOCAB_DIR/.done-$TODAY"
LOCK_DIR="$VOCAB_DIR/.lock"
HOUR=$(date +%-H)

[[ -f "$STAMP_FILE" ]] && exit 0
(( HOUR < 5 || HOUR >= 12 )) && exit 0
pgrep -f "vocab_agent.py" > /dev/null 2>&1 && exit 0

if [[ -d "$LOCK_DIR" ]]; then
    lock_age=$(( $(date +%s) - $(stat -f %m "$LOCK_DIR") ))
    (( lock_age > 1800 )) && rmdir "$LOCK_DIR" 2>/dev/null || true
fi
mkdir "$LOCK_DIR" 2>/dev/null || exit 0
trap 'rmdir "$LOCK_DIR" 2>/dev/null || true' EXIT

find "$VOCAB_DIR" -name ".done-*" -mtime +7 -delete 2>/dev/null || true

osascript -e '
tell application "Terminal"
    activate
    do script "python3 ~/vocab-agent/vocab_agent.py"
end tell
' > /dev/null 2>&1

exit 0
GATEKEEPER
chmod +x "$BIN_DIR/vocab-check"

# --- Create symlink ---
ln -sf "$VOCAB_DIR/vocab_agent.py" "$BIN_DIR/vocab"

echo "  [3/6] Installing SleepWatcher..."
if command -v brew &>/dev/null; then
    if ! brew list sleepwatcher &>/dev/null 2>&1; then
        brew install sleepwatcher
    fi
    if ! brew services list | grep sleepwatcher | grep -q started; then
        brew services start sleepwatcher
    fi
    echo "         SleepWatcher ready."
else
    echo "         Homebrew not found. Skipping SleepWatcher."
    echo "         (Wake detection will rely on LaunchAgent and shell hook instead.)"
fi

echo "  [4/6] Creating ~/.wakeup hook..."
cat > "$HOME/.wakeup" << 'WAKEUP'
#!/usr/bin/env bash
~/.local/bin/vocab-check &
WAKEUP
chmod 700 "$HOME/.wakeup"

echo "  [5/6] Installing LaunchAgent..."
mkdir -p "$LAUNCH_AGENTS"
cat > "$PLIST_PATH" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$PLIST_LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>$BIN_DIR/vocab-check</string>
    </array>
    <key>StartCalendarInterval</key>
    <array>
        <dict>
            <key>Hour</key>
            <integer>7</integer>
            <key>Minute</key>
            <integer>0</integer>
        </dict>
        <dict>
            <key>Hour</key>
            <integer>8</integer>
            <key>Minute</key>
            <integer>0</integer>
        </dict>
        <dict>
            <key>Hour</key>
            <integer>9</integer>
            <key>Minute</key>
            <integer>0</integer>
        </dict>
    </array>
    <key>LimitLoadToSessionType</key>
    <string>Aqua</string>
    <key>StandardErrorPath</key>
    <string>/tmp/vocab-morning.err</string>
    <key>StandardOutPath</key>
    <string>/tmp/vocab-morning.out</string>
</dict>
</plist>
PLIST
launchctl unload "$PLIST_PATH" 2>/dev/null || true
launchctl load "$PLIST_PATH"

echo "  [6/6] Adding shell hook..."
MARKER="# --- vocab-agent ---"
if ! grep -q "$MARKER" "$HOME/.zshrc" 2>/dev/null; then
    cat >> "$HOME/.zshrc" << 'ZSHRC'

# --- vocab-agent ---
~/.local/bin/vocab-check 2>/dev/null &!
alias vocab="python3 ~/vocab-agent/vocab_agent.py"
ZSHRC
    echo "         Added to ~/.zshrc"
else
    echo "         Already in ~/.zshrc, skipping."
fi

# --- Ensure ~/.local/bin is in PATH ---
if ! grep -q 'export PATH="$HOME/.local/bin:$PATH"' "$HOME/.zshrc" 2>/dev/null; then
    sed -i '' '1i\
export PATH="$HOME/.local/bin:$PATH"\
' "$HOME/.zshrc" 2>/dev/null || echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$HOME/.zshrc"
    echo "         Added ~/.local/bin to PATH in .zshrc"
fi

echo ""
echo "  ✓ Vocab Agent installed!"
echo ""
echo "  Usage:"
echo "    vocab              Launch manually from any terminal"
echo "    (automatic)        Opens each morning when you open your laptop"
echo ""
echo "  To uninstall, run:   bash ~/vocab-agent/uninstall.sh"
echo ""
