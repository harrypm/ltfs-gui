#!/bin/bash

# LTFS Quick Installation Script for Ubuntu/Debian/Linux Mint
# This script installs all dependencies and builds LTFS from source

set -e

echo "LTFS Installation Script for Ubuntu/Debian/Linux Mint"
echo "===================================================="
echo

# Check if running as root
if [[ $EUID -eq 0 ]]; then
   echo "❌ Error: Do not run this script as root"
   echo "The script will use sudo when needed"
   exit 1
fi

# Detect system
if ! command -v apt >/dev/null 2>&1; then
    echo "❌ Error: This script is for Ubuntu/Debian/Linux Mint systems only"
    echo "Use the manual installation instructions for other distributions"
    exit 1
fi

echo "📦 Installing dependencies..."

# Update package list
sudo apt update

# Install build tools
echo "Installing build tools..."
sudo apt install -y build-essential autotools-dev automake libtool pkg-config

# Install core dependencies
echo "Installing core dependencies..."
sudo apt install -y libfuse-dev libxml2-dev uuid-dev libicu-dev

# Install ICU development tools
echo "Installing ICU development tools..."
sudo apt install -y icu-devtools libicu-dev

# Install additional libraries
echo "Installing additional libraries..."
sudo apt install -y libpthread-stubs0-dev libsnmp-dev

# Install Python dependencies for GUI
echo "Installing Python dependencies..."
sudo apt install -y python3 python3-tk

echo "✅ All dependencies installed successfully"

# Handle ICU config issue for newer Ubuntu/Debian
if ! command -v icu-config &> /dev/null; then
    echo "🔧 Fixing missing icu-config..."
    cat << 'EOF' | sudo tee /usr/local/bin/icu-config
#!/bin/bash
pkg-config "$@" icu-i18n icu-uc icu-io
EOF
    sudo chmod +x /usr/local/bin/icu-config
    echo "✅ Created icu-config wrapper"
fi

# Set up tape group and permissions
echo "🔧 Setting up tape device permissions..."
if ! getent group tape > /dev/null; then
    sudo groupadd tape
fi
sudo usermod -a -G tape $USER

# Set up udev rules for tape devices
echo 'SUBSYSTEM=="scsi_generic", GROUP="tape", MODE="0664"' | sudo tee /etc/udev/rules.d/60-tape.rules
echo 'SUBSYSTEM=="scsi_tape", GROUP="tape", MODE="0664"' | sudo tee -a /etc/udev/rules.d/60-tape.rules
sudo udevadm control --reload-rules
sudo udevadm trigger

echo "✅ Tape permissions configured"

# Build LTFS
echo "🔨 Building LTFS..."

# Generate configure script
echo "Generating configure script..."
./autogen.sh

# Configure build
echo "Configuring build..."
./configure --prefix=/usr/local

# Build
echo "Building LTFS (this may take a few minutes)..."
make -j$(nproc)

# Install
echo "Installing LTFS..."
sudo make install

# Update library cache
sudo ldconfig -v

echo "✅ LTFS build and installation completed"

# Verify installation
echo "🧪 Verifying installation..."
if command -v ltfs >/dev/null 2>&1; then
    echo "✅ LTFS installed successfully: $(which ltfs)"
    ltfs --version
else
    echo "⚠️  LTFS not found in PATH, adding /usr/local/bin to PATH"
    echo 'export PATH="/usr/local/bin:$PATH"' >> ~/.bashrc
    export PATH="/usr/local/bin:$PATH"
    
    if command -v ltfs >/dev/null 2>&1; then
        echo "✅ LTFS now available: $(which ltfs)"
    else
        echo "❌ LTFS installation verification failed"
        exit 1
    fi
fi

# Install GUI if present
if [ -f "ltfs_gui.py" ]; then
    echo "🖥️  Installing LTFS GUI..."
    chmod +x ltfs_gui.py
    
    # Test GUI dependencies
    if python3 -c "import tkinter" >/dev/null 2>&1; then
        echo "✅ GUI dependencies OK"
        
        # Install GUI globally
        echo "Installing GUI globally to /usr/local/bin..."
        sudo cp ltfs_gui.py /usr/local/bin/ltfs-gui
        sudo chmod +x /usr/local/bin/ltfs-gui
        
        # Install test script too
        if [ -f "test_ltfs_gui.py" ]; then
            sudo cp test_ltfs_gui.py /usr/local/bin/ltfs-gui-test
            sudo chmod +x /usr/local/bin/ltfs-gui-test
        fi
        
        echo "✅ GUI installed globally as 'ltfs-gui'"
        
        # Install desktop file
        if [ -f "ltfs-gui.desktop" ]; then
            mkdir -p ~/.local/share/applications
            cp ltfs-gui.desktop ~/.local/share/applications/
            chmod +x ~/.local/share/applications/ltfs-gui.desktop
            echo "✅ Desktop file installed"
        fi
        
        # Test GUI installation
        if command -v ltfs-gui >/dev/null 2>&1; then
            echo "✅ GUI command 'ltfs-gui' is available globally"
        else
            echo "⚠️  GUI installed but 'ltfs-gui' command not found in PATH"
            echo "   You may need to restart your terminal"
        fi
    else
        echo "❌ GUI dependencies missing, skipping GUI installation"
    fi
fi

echo
echo "🎉 LTFS installation completed successfully!"
echo
echo "📋 Next steps:"
echo "1. Log out and back in for group membership changes to take effect"
echo "2. Connect your tape drive"
echo "3. Test with: ltfs -o device_list"
if [ -f "$HOME/.local/bin/ltfs-gui" ]; then
    echo "4. Launch GUI with: ltfs-gui (or from applications menu)"
fi
echo
echo "📖 Documentation:"
echo "   - Main README: README.md"
echo "   - GUI README: README_LTFS_GUI.md"
echo "   - Test GUI: python3 test_ltfs_gui.py"
echo
echo "⚠️  Important: You MUST log out and back in for tape device access!"

