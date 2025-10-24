#!/bin/bash

# Manual reconnection script for USB card reader issues
# Usage: /app/scripts/reconnect_reader.sh

echo "🔄 Manually reconnecting USB card reader..."

# Check if pcscd is running
if ! pgrep -f pcscd > /dev/null; then
    echo "❌ pcscd is not running. Starting it..."
    supervisorctl start pcscd
    sleep 3
fi

# Show current USB devices
echo "📋 Current USB devices:"
lsusb | grep -i -E "(smart|card|reader|ccid|omnikey|gemalto|identiv|cherry|acr)" || echo "No card readers found"

# Restart pcscd to detect device changes
echo "🔄 Restarting pcscd..."
supervisorctl restart pcscd
sleep 3

# Check pcscd status
echo "✅ pcscd status:"
supervisorctl status pcscd

# Show detected readers
echo "📋 Detected card readers:"
pcsc_scan -n 2>/dev/null | head -10 || echo "Could not scan for readers"

echo "✅ Reader reconnection complete!"
echo "💡 Tip: Place a card on the reader to test if it's working"
