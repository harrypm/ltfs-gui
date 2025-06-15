#!/bin/bash

# LTFS GUI Debug Monitor
# Run this script to monitor LTFS GUI activity and system status

echo "=== LTFS GUI Debug Monitor ==="
echo "GUI Process Status:"
ps aux | grep ltfs_gui | grep -v grep
echo

echo "Tape Drives Available:"
lsscsi -g | grep tape
echo

echo "Current Tape Status:"
if [ -e /dev/st0 ]; then
    echo "Checking /dev/st0..."
    sudo mt -f /dev/st0 status 2>/dev/null || echo "No tape loaded or drive busy"
else
    echo "No /dev/st0 device found"
fi
echo

echo "LTFS Mounts:"
mount | grep ltfs || echo "No LTFS mounts found"
echo

echo "Recent LTFS Activity (last 20 lines):"
sudo journalctl -n 20 | grep -i ltfs || echo "No recent LTFS activity in journal"
echo

echo "=== Quantum LTO-5 Compatibility Check ==="
if [ -e /dev/sg0 ]; then
    echo "Drive Information:"
    sudo sg_inq /dev/sg0 2>/dev/null | grep -E "Vendor|Product|Unit serial" || echo "Could not get drive info"
else
    echo "No /dev/sg0 device found"
fi
echo

echo "=== Available Test Commands ==="
echo "1. Test drive detection:    ltfs -o device_list"
echo "2. Check tape status:       sudo mt -f /dev/st0 status"
echo "3. Test format (CAREFUL):   sudo mkltfs -d /dev/st0 -n 'TEST' -b 65536 -f"
echo "4. Test mount:              sudo ltfs -o devname=/dev/st0 /tmp/ltfs_test"
echo "5. Monitor GUI process:     watch 'ps aux | grep ltfs_gui | grep -v grep'"
echo
echo "Press Ctrl+C to stop monitoring, or run individual commands as needed."
echo "GUI is running - you can now test all functionality!"

