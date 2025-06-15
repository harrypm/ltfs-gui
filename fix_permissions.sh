#!/bin/bash

# LTFS GUI Permissions Fix Script
# Fixes common tape device permission issues

set -e

echo "LTFS GUI Permissions Fix"
echo "========================"
echo

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    local color=$1
    local message=$2
    echo -e "${color}${message}${NC}"
}

# Check if running as root
if [[ $EUID -eq 0 ]]; then
    print_status $RED "❌ Do not run this script as root!"
    echo "Run it as your regular user instead."
    exit 1
fi

echo "Checking tape device permissions..."
echo

# Check if tape devices exist
TAPE_DEVICES=()
for device in /dev/st* /dev/nst*; do
    if [[ -e "$device" && ! "$device" =~ (stdin|stdout|stderr) ]]; then
        TAPE_DEVICES+=("$device")
    fi
done

if [ ${#TAPE_DEVICES[@]} -eq 0 ]; then
    print_status $RED "❌ No tape devices found!"
    echo "   Check if your tape drive is connected and detected by the system."
    echo "   Run: dmesg | grep -i tape"
    exit 1
fi

echo "Found tape devices:"
for device in "${TAPE_DEVICES[@]}"; do
    ls -l "$device"
done
echo

# Check current groups
echo "Current groups for user $USER:"
echo "   $(groups)"
echo

# Check if user is in tape group (in /etc/group)
if getent group tape | grep -q "\b$USER\b"; then
    print_status $GREEN "✅ User $USER is in the tape group (according to /etc/group)"
    IN_TAPE_GROUP=true
else
    print_status $RED "❌ User $USER is NOT in the tape group"
    IN_TAPE_GROUP=false
fi

# Check if current session reflects tape group membership
if groups | grep -q "\btape\b"; then
    print_status $GREEN "✅ Current session has tape group access"
    SESSION_HAS_TAPE=true
else
    print_status $YELLOW "⚠️  Current session does NOT have tape group access"
    SESSION_HAS_TAPE=false
fi

# Test actual access to a tape device
TEST_DEVICE="${TAPE_DEVICES[0]}"
echo
echo "Testing access to $TEST_DEVICE..."
if timeout 5 dd if="$TEST_DEVICE" of=/dev/null bs=1 count=1 2>/dev/null; then
    print_status $GREEN "✅ Can read from tape device"
    CAN_ACCESS=true
elif [[ $? -eq 124 ]]; then
    # Timeout - device is accessible but no tape/takes too long
    print_status $GREEN "✅ Can access tape device (timeout indicates device is accessible)"
    CAN_ACCESS=true
else
    print_status $RED "❌ Cannot access tape device"
    CAN_ACCESS=false
fi

echo
echo "=== DIAGNOSIS ==="

# Determine what needs to be fixed
NEEDS_GROUP_ADD=false
NEEDS_SESSION_REFRESH=false
NEEDS_UDEV_RULES=false

if [ "$IN_TAPE_GROUP" = false ]; then
    NEEDS_GROUP_ADD=true
    print_status $RED "❌ Need to add user to tape group"
elif [ "$SESSION_HAS_TAPE" = false ]; then
    NEEDS_SESSION_REFRESH=true
    print_status $YELLOW "⚠️  Need to refresh session (logout/login or use newgrp)"
fi

if [ "$CAN_ACCESS" = false ]; then
    # Check if it's a udev rules issue
    if ls -l "$TEST_DEVICE" | grep -q "crw.rw.....*tape"; then
        if [ "$SESSION_HAS_TAPE" = true ]; then
            print_status $YELLOW "⚠️  Device permissions look correct but access failed - may need udev rules"
            NEEDS_UDEV_RULES=true
        fi
    else
        print_status $RED "❌ Device permissions are incorrect"
    fi
fi

echo
echo "=== SOLUTIONS ==="

if [ "$NEEDS_GROUP_ADD" = true ]; then
    echo
    print_status $BLUE "🔧 SOLUTION 1: Add user to tape group"
    echo "   Run this command:"
    echo "   sudo usermod -a -G tape $USER"
    echo
    echo "   Then logout and login again, or run:"
    echo "   newgrp tape"
    echo
    
    read -p "Would you like me to add you to the tape group now? (y/N): " add_to_group
    if [[ $add_to_group =~ ^[Yy] ]]; then
        echo "Adding user $USER to tape group..."
        if sudo usermod -a -G tape "$USER"; then
            print_status $GREEN "✅ Successfully added to tape group"
            NEEDS_SESSION_REFRESH=true
        else
            print_status $RED "❌ Failed to add to tape group"
        fi
    fi
fi

if [ "$NEEDS_SESSION_REFRESH" = true ]; then
    echo
    print_status $BLUE "🔧 SOLUTION 2: Refresh session to activate group membership"
    echo
    echo "Choose one of these options:"
    echo
    echo "   Option A - Use newgrp (temporary for this terminal):"
    echo "   newgrp tape"
    echo
    echo "   Option B - Logout and login again (permanent)"
    echo "   This is the recommended solution for permanent access."
    echo
    echo "   Option C - Start LTFS GUI with correct groups:"
    echo "   sudo -u $USER -g tape ltfs-gui"
    echo
    
    read -p "Would you like to try Option A (newgrp) now? (y/N): " use_newgrp
    if [[ $use_newgrp =~ ^[Yy] ]]; then
        echo
        print_status $YELLOW "⚠️  Starting new shell with tape group..."
        echo "Run 'exit' to return to this shell when done."
        echo "Try running: ltfs-gui"
        exec newgrp tape
    fi
fi

if [ "$NEEDS_UDEV_RULES" = true ]; then
    echo
    print_status $BLUE "🔧 SOLUTION 3: Create udev rules for tape devices"
    echo
    echo "This creates a udev rule to ensure proper permissions:"
    
    UDEV_RULE='/etc/udev/rules.d/99-tape-permissions.rule'
    echo 'KERNEL=="st*", GROUP="tape", MODE="0660"'
    echo 'KERNEL=="nst*", GROUP="tape", MODE="0660"'
    echo
    echo "These rules will be written to: $UDEV_RULE"
    echo
    
    read -p "Would you like me to create these udev rules? (y/N): " create_udev
    if [[ $create_udev =~ ^[Yy] ]]; then
        echo "Creating udev rules..."
        if sudo tee "$UDEV_RULE" > /dev/null << 'EOF'
# LTFS tape device permissions
KERNEL=="st*", GROUP="tape", MODE="0660"
KERNEL=="nst*", GROUP="tape", MODE="0660"
EOF
        then
            print_status $GREEN "✅ Udev rules created successfully"
            echo "Reloading udev rules..."
            sudo udevadm control --reload-rules
            sudo udevadm trigger --subsystem-match=block
            print_status $GREEN "✅ Udev rules reloaded"
        else
            print_status $RED "❌ Failed to create udev rules"
        fi
    fi
fi

# Alternative workarounds
echo
print_status $BLUE "🚀 IMMEDIATE WORKAROUNDS"
echo
echo "If you need to use LTFS GUI right now before logging out:"
echo
echo "1. Run with sudo (temporarily):"
echo "   sudo -u $USER -g tape /usr/local/bin/ltfs-gui"
echo "   # or wherever ltfs-gui is installed"
echo
echo "2. Use newgrp in current terminal:"
echo "   newgrp tape"
echo "   ltfs-gui"
echo
echo "3. Test tape access manually:"
echo "   sudo -u $USER -g tape mt -f $TEST_DEVICE status"
echo

# Final verification
echo
print_status $BLUE "🔍 VERIFICATION COMMANDS"
echo
echo "After applying fixes, verify with these commands:"
echo
echo "1. Check group membership:"
echo "   groups | grep tape"
echo
echo "2. Test tape device access:"
echo "   mt -f $TEST_DEVICE status"
echo
echo "3. Test LTFS GUI:"
echo "   ltfs-gui"
echo

# Create a test script
cat > /tmp/test_tape_access.sh << 'EOF'
#!/bin/bash
echo "Testing tape access..."
echo "Groups: $(groups)"
for device in /dev/st* /dev/nst*; do
    if [[ -e "$device" && ! "$device" =~ (stdin|stdout|stderr) ]]; then
        echo "Testing $device:"
        if timeout 2 dd if="$device" of=/dev/null bs=1 count=1 2>/dev/null; then
            echo "  ✅ Accessible"
        elif [[ $? -eq 124 ]]; then
            echo "  ✅ Accessible (timeout)"
        else
            echo "  ❌ Not accessible"
        fi
    fi
done
EOF
chmod +x /tmp/test_tape_access.sh

echo "Created test script: /tmp/test_tape_access.sh"
echo "Run this after applying fixes to verify access."
echo

print_status $GREEN "🎉 Permissions fix script completed!"
echo
echo "Remember: The most reliable fix is to logout and login again after"
echo "being added to the tape group."

