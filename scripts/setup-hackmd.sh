#!/usr/bin/env bash
# ═══ Setup HackMD API Token ═══
# 1. Go to https://hackmd.io/settings/api
# 2. Create a new API token
# 3. Run this script and paste the token
#
# Usage: ./scripts/setup-hackmd.sh

set -euo pipefail

CONFIG_DIR="$HOME/.hackmd"
CONFIG_FILE="$CONFIG_DIR/config.json"
SECRET_FILE="/etc/jarvis-hackmd.env"

echo "🔐 HackMD API Token Setup"
echo ""
echo "Steps:"
echo "  1. Open https://hackmd.io/settings/api"
echo "  2. Click 'Create API token'"
echo "  3. Copy the token"
echo "  4. Paste it below"
echo ""

read -rsp "Paste your HackMD API token: " TOKEN
echo ""

if [[ -z "$TOKEN" ]]; then
    echo "❌ No token provided"
    exit 1
fi

# Save to user config
mkdir -p "$CONFIG_DIR"
cat > "$CONFIG_FILE" <<EOF
{
  "accessToken": "$TOKEN"
}
EOF
chmod 600 "$CONFIG_FILE"
echo "✅ Saved to $CONFIG_FILE"

# Save to NixOS secrets (for services)
sudo mkdir -p /etc/jarvis-secrets
sudo tee "$SECRET_FILE" > /dev/null <<EOF
HMD_API_ACCESS_TOKEN=$TOKEN
EOF
sudo chmod 600 "$SECRET_FILE"
echo "✅ Saved to $SECRET_FILE"

# Test the connection
echo ""
echo "Testing connection..."
RESPONSE=$(npx -y @hackmd/hackmd-cli whoami 2>&1 || true)
if echo "$RESPONSE" | grep -qi "error\|fail"; then
    echo "⚠️  Connection test failed: $RESPONSE"
    echo "   Token may be invalid. Check at https://hackmd.io/settings/api"
else
    echo "✅ Connection OK: $RESPONSE"
fi
