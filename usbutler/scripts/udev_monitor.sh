#!/bin/bash

# Monitor USB devices and restart pcscd when card readers are added/removed
# This script watches for USB device changes and restarts pcscd to detect new readers

echo "Starting USB device monitor for smart card readers..."

# Function to restart pcscd and application
restart_services() {
    echo "$(date): USB device change detected, restarting services..."
    
    # Kill existing pcscd processes
    pkill -f pcscd || true
    sleep 1
    
    # Restart pcscd through supervisor
    supervisorctl restart pcscd
    
    # Give pcscd time to start
    sleep 3
    
    # Restart usbutler to reinitialize the connection
    supervisorctl restart usbutler
    
    echo "$(date): Services restarted"
}

# Monitor USB subsystem for add/remove events
udevadm monitor --subsystem-match=usb --property | while read line; do
    # Check if this is an add or remove event
    if echo "$line" | grep -q "ACTION=add\|ACTION=remove"; then
        # Wait a moment for device to settle
        sleep 2
        
        # Check if any smart card readers are present or if device was removed
        if echo "$line" | grep -q "ACTION=remove"; then
            echo "$(date): USB device removed, checking for card readers..."
            restart_services
        elif lsusb | grep -i -E "(smart|card|reader|ccid|omnikey|gemalto|identiv|cherry|acr)" > /dev/null; then
            echo "$(date): Smart card reader detected in USB devices"
            restart_services
        fi
    fi
done
