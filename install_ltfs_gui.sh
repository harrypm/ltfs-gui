#!/bin/bash

# LTFS GUI Installation Script
# Installs the LTFS GUI wrapper for easy access

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GUI_SCRIPT="$SCRIPT_DIR/ltfs_gui.py"
DESKTOP_FILE="$SCRIPT_DIR/ltfs-gui.desktop"

echo "LTFS GUI Installation Script"
echo "============================"

# Check if LTFS is installed
if ! command -v ltfs >/dev/null 2>&1; then
    echo "❌ Error: LTFS is not installed or not in PATH"
    echo "Please install LTFS first before running this script."
    exit 1
fi

echo "✅ LTFS found: $(which ltfs)"

# Check if Python 3 and tkinter are available
if ! /usr/bin/python3 -c "import tkinter" >/dev/null 2>&1; then
    echo "❌ Error: Python 3 tkinter is not available"
    echo "Please install python3-tk:"
    echo "  sudo apt install python3-tk"
    exit 1
fi

echo "✅ Python 3 and tkinter are available"

# Check for optional diagnostic tools
echo
echo "Checking optional diagnostic tools..."
DIAGNOSTIC_TOOLS=(
    "sg_inq:sg3-utils:SCSI inquiry utility for hardware information"
    "sg_logs:sg3-utils:SCSI log page utility for error statistics"
    "sg_vpd:sg3-utils:SCSI VPD utility for device details"
    "tapeinfo:tapeinfo:Tape information utility"
    "lsscsi:lsscsi:List SCSI devices utility"
    "iostat:sysstat:I/O statistics utility"
)

MISSING_TOOLS=()
AVAILABLE_TOOLS=()

for tool_info in "${DIAGNOSTIC_TOOLS[@]}"; do
    IFS=':' read -r cmd package desc <<< "$tool_info"
    if command -v "$cmd" >/dev/null 2>&1; then
        echo "✅ $desc ($cmd)"
        AVAILABLE_TOOLS+=("$cmd")
    else
        echo "⚠️  $desc ($cmd) - install with: sudo apt install $package"
        MISSING_TOOLS+=("$package")
    fi
done

if [ ${#MISSING_TOOLS[@]} -gt 0 ]; then
    echo
    echo "📋 To install all missing diagnostic tools:"
    echo "   sudo apt install ${MISSING_TOOLS[*]}"
    echo "   (or equivalent for your distribution)"
    echo
    echo "Note: The GUI will work without these tools, but some diagnostic features may be limited."
else
    echo "✅ All diagnostic tools are available - full functionality enabled!"
fi

# Make scripts executable
chmod +x "$GUI_SCRIPT"
echo "✅ Made ltfs_gui.py executable"

# Installation options
echo
echo "Installation options:"
echo "1) Install globally to /usr/local/bin (recommended - requires sudo)"
echo "2) Install to user ~/.local/bin (user-only access)"
echo "3) Create symlink in ~/.local/bin"
echo "4) Install desktop file only"
echo "5) Just verify installation"
echo
read -p "Choose option (1-5): " choice

case $choice in
    1)
        # Global installation
        echo "Installing globally..."
        sudo cp "$GUI_SCRIPT" /usr/local/bin/ltfs-gui
        sudo chmod +x /usr/local/bin/ltfs-gui
        
        # Also install test script globally
        if [ -f "$SCRIPT_DIR/test_ltfs_gui.py" ]; then
            sudo cp "$SCRIPT_DIR/test_ltfs_gui.py" /usr/local/bin/ltfs-gui-test
            sudo chmod +x /usr/local/bin/ltfs-gui-test
        fi
        
        echo "✅ Installed globally: /usr/local/bin/ltfs-gui"
        echo "   Command: ltfs-gui (available system-wide)"
        
        # Update desktop file to use global path
        DESKTOP_EXEC_PATH="/usr/local/bin/ltfs-gui"
        ;;
    2)
        # User local installation
        USER_BIN="$HOME/.local/bin"
        if [ ! -d "$USER_BIN" ]; then
            mkdir -p "$USER_BIN"
        fi
        
        cp "$GUI_SCRIPT" "$USER_BIN/ltfs-gui"
        chmod +x "$USER_BIN/ltfs-gui"
        
        # Also install test script
        if [ -f "$SCRIPT_DIR/test_ltfs_gui.py" ]; then
            cp "$SCRIPT_DIR/test_ltfs_gui.py" "$USER_BIN/ltfs-gui-test"
            chmod +x "$USER_BIN/ltfs-gui-test"
        fi
        
        echo "✅ Copied script to: $USER_BIN/ltfs-gui"
        DESKTOP_EXEC_PATH="$USER_BIN/ltfs-gui"
        ;;
    3)
        # Symlink installation
        USER_BIN="$HOME/.local/bin"
        if [ ! -d "$USER_BIN" ]; then
            mkdir -p "$USER_BIN"
        fi
        
        ln -sf "$GUI_SCRIPT" "$USER_BIN/ltfs-gui"
        echo "✅ Created symlink: $USER_BIN/ltfs-gui -> $GUI_SCRIPT"
        DESKTOP_EXEC_PATH="$USER_BIN/ltfs-gui"
        ;;
    4)
        echo "ℹ️  Skipping binary installation"
        DESKTOP_EXEC_PATH="$GUI_SCRIPT"
        ;;
    5)
        echo "ℹ️  Verification mode only"
        ;;
    *)
        echo "❌ Invalid option"
        exit 1
        ;;
esac

# Install desktop file
if [ "$choice" != "4" ]; then
    echo
    read -p "Install desktop file for GUI launcher? (y/n): " install_desktop
    if [[ $install_desktop =~ ^[Yy] ]]; then
        DESKTOP_DIR="$HOME/.local/share/applications"
        mkdir -p "$DESKTOP_DIR"
        
        # Update desktop file with correct path
        sed "s|/home/harry/src/ltfs/ltfs_gui.py|$GUI_SCRIPT|g" "$DESKTOP_FILE" > "$DESKTOP_DIR/ltfs-gui.desktop"
        chmod +x "$DESKTOP_DIR/ltfs-gui.desktop"
        
        echo "✅ Installed desktop file: $DESKTOP_DIR/ltfs-gui.desktop"
        echo "   The LTFS Manager should now appear in your applications menu"
    fi
fi

# Check tape group membership
echo
echo "Checking tape device permissions..."
if groups | grep -q tape; then
    echo "✅ You are already in the 'tape' group"
else
    echo "⚠️  You are not in the 'tape' group"
    echo "   To access tape devices, add yourself to the tape group:"
    echo "   sudo usermod -a -G tape $USER"
    echo "   Then log out and back in for the change to take effect"
fi

# Test the installation
echo
echo "Testing LTFS GUI..."
if [ -f "$SCRIPT_DIR/test_ltfs_gui.py" ]; then
    if /usr/bin/python3 "$SCRIPT_DIR/test_ltfs_gui.py" >/dev/null 2>&1; then
        echo "✅ LTFS GUI test passed"
    else
        echo "⚠️  LTFS GUI test had warnings (check permissions above)"
    fi
else
    echo "ℹ️  Test script not found, performing basic import test..."
    if /usr/bin/python3 -c "import sys; sys.path.insert(0, '$SCRIPT_DIR'); import ltfs_gui" >/dev/null 2>&1; then
        echo "✅ LTFS GUI imports successfully"
    else
        echo "❌ LTFS GUI import failed - check dependencies"
    fi
fi

echo
echo "Installation Summary:"
echo "==================="
echo "📍 LTFS GUI script: $GUI_SCRIPT"
if [ -f "$SCRIPT_DIR/test_ltfs_gui.py" ]; then
    echo "📍 Test script: $SCRIPT_DIR/test_ltfs_gui.py"
fi
echo "📍 README: $SCRIPT_DIR/README_LTFS_GUI.md"
echo "📍 Available diagnostic tools: ${#AVAILABLE_TOOLS[@]}/${#DIAGNOSTIC_TOOLS[@]}"
if [ ${#MISSING_TOOLS[@]} -gt 0 ]; then
    echo "📍 Missing diagnostic tools: ${MISSING_TOOLS[*]}"
fi

if [ "$choice" = "1" ] || [ "$choice" = "2" ]; then
    echo "📍 Command: ltfs-gui (if ~/.local/bin is in your PATH)"
    
    # Check if ~/.local/bin is in PATH
    if echo "$PATH" | grep -q "$USER_BIN"; then
        echo "✅ ~/.local/bin is in your PATH"
    else
        echo "⚠️  ~/.local/bin is not in your PATH"
        echo "   Add this to your ~/.bashrc or ~/.profile:"
        echo "   export PATH=\"\$HOME/.local/bin:\$PATH\""
    fi
fi

echo
echo "Usage:"
echo "------"
echo "Direct execution:    $GUI_SCRIPT"
if [ "$choice" = "1" ] || [ "$choice" = "2" ]; then
    echo "Command:             ltfs-gui"
fi
echo "Test functionality:  $SCRIPT_DIR/test_ltfs_gui.py"
echo
echo "📖 For detailed usage instructions, see: $SCRIPT_DIR/README_LTFS_GUI.md"
echo
echo "🎉 LTFS GUI installation completed!"

