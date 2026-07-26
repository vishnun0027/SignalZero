#!/bin/bash
# Uniform Deployment Script for SignalZero
set -e

PROJECT_NAME="SignalZero"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "========================================="
echo "🚀 Deploying $PROJECT_NAME in $PROJECT_DIR"
echo "========================================="

# 1. Update PATH to include user local binaries
export PATH="$HOME/.local/bin:$PATH"

# 2. Pull latest code
if [ -d "$PROJECT_DIR/.git" ]; then
    echo "--- Pulling latest code ---"
    cd "$PROJECT_DIR"
    git reset --hard HEAD
    git pull origin main
fi

# 3. Write .env if provided via CI secret env variable
if [ -n "$DOTENV_CONTENT" ]; then
    echo "--- Writing .env from environment variable ---"
    printf '%s\n' "$DOTENV_CONTENT" > "$PROJECT_DIR/.env"
fi

# 4. Sync dependencies
echo "--- Syncing dependencies with uv ---"
cd "$PROJECT_DIR"
uv sync --frozen

# 5. Prepare systemd directory
echo "--- Installing systemd user services ---"
mkdir -p "$HOME/.config/systemd/user/"

# 6. Template and copy systemd files
# Both services and timers
for f in "$PROJECT_DIR"/config/systemd/signalzero*; do
    if [ -f "$f" ]; then
        basename_f=$(basename "$f")
        echo "Templating $basename_f..."
        # Replace hardcoded paths dynamically and remove explicit User/Group for user mode
        sed -e "s|/home/vishnu/worklab/SignalZero|$PROJECT_DIR|g" \
            -e "/^User=/d" \
            -e "/^Group=/d" \
            "$f" > "$HOME/.config/systemd/user/$basename_f"
    fi
done

# 7. Enable lingering and export runtime dir for systemctl --user commands
loginctl enable-linger "$(whoami)" || true
export XDG_RUNTIME_DIR="/run/user/$(id -u)"

# 8. Reload systemd daemon
echo "--- Reloading systemd user daemon ---"
systemctl --user daemon-reload

# 9. Enable services and timers
echo "--- Enabling services and timers ---"
systemctl --user enable signalzero_api.service signalzero.timer signalzero_digest.timer

# 10. Restart services and timers
echo "--- Restarting services ---"
systemctl --user restart signalzero_api.service signalzero.timer signalzero_digest.timer

# 11. Verify deployment (health check)
echo "--- Verifying deployment (health check) ---"
HEALTH_PASSED=false
for i in {1..8}; do
    echo "Health check attempt $i/8..."
    if curl --fail --silent --show-error http://localhost:8007/api/health; then
        echo "✅ API health check passed"
        HEALTH_PASSED=true
        break
    fi
    sleep 5
done

if [ "$HEALTH_PASSED" = false ]; then
    echo "❌ API health check FAILED"
    echo "=== Journalctl API logs ==="
    journalctl --user -u signalzero_api.service -n 100 --no-pager || true
    echo "=== Service Status ==="
    systemctl --user status signalzero_api.service || true
    exit 1
fi

echo "🎉 $PROJECT_NAME deployment completed successfully!"
