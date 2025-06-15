# LTFS GUI Manager

A simple graphical user interface for managing Linear Tape File System (LTFS) operations on Linux systems.

## Features

- **Tape Drive Management**: Automatically detect and list available tape drives
- **Mount/Unmount Operations**: Easy mounting and unmounting of LTFS tapes
- **Compression Control**: Dedicated tab for configuring tape compression modes
- **Tape Formatting**: Format tapes with LTFS filesystem
- **Drive Information**: Get detailed information about tape drives and loaded tapes
- **Comprehensive Diagnostics**: Advanced diagnostic tools for tape drive health and performance
- **Status Monitoring**: Real-time status of drives and mounted tapes
- **File Manager Integration**: Open mounted tapes directly in your file manager
- **Operation Logging**: Comprehensive logging of all operations

## Requirements

- Python 3.6+
- tkinter (usually included with Python)
- LTFS tools installed (`ltfs`, `mkltfs`, `mt`)
- Linux system with tape drive support

### Optional Diagnostic Tools

For full diagnostic functionality, install these additional tools:

#### Quick Installation (All Distributions)
```bash
# Use our automated installer
./install_diagnostic_tools.sh
```

#### Manual Installation by Distribution

**Ubuntu/Debian:**
```bash
sudo apt install sg3-utils mtx lsscsi sysstat
```

**RHEL/CentOS/Rocky/AlmaLinux:**
```bash
sudo dnf install sg3_utils mt-st lsscsi sysstat
# or with yum:
sudo yum install sg3_utils mt-st lsscsi sysstat
```

**Fedora:**
```bash
sudo dnf install sg3_utils mt-st lsscsi sysstat
```

**openSUSE/SLES:**
```bash
sudo zypper install sg3_utils mt_st lsscsi sysstat
```

**Arch Linux:**
```bash
sudo pacman -S sg3_utils mt-st lsscsi sysstat
```

**Tool Functions:**
- **sg3-utils**: SCSI inquiry, log pages, VPD data
- **tapeinfo/mt-st**: Tape-specific information and control
- **lsscsi**: List and identify SCSI devices
- **sysstat**: I/O statistics and performance monitoring

Note: The GUI will work without these tools, but some diagnostic features may not be available.

## Installation

### Quick Start

For immediate setup, see: **[QUICKSTART.md](QUICKSTART.md)**

### Prerequisites

1. Ensure LTFS is installed and working:
   ```bash
   which ltfs
   which mkltfs
   ```

2. Ensure Python 3 and tkinter are installed:
   ```bash
   python3 -c "import tkinter; print('tkinter OK')"
   ```

3. (Optional) Install diagnostic tools:
   ```bash
   ./install_diagnostic_tools.sh
   ```

### Installation Options

#### Option 1: Use the Installation Script (Recommended)

```bash
./install_ltfs_gui.sh
```

This script offers several installation options:
- **Global installation** (requires sudo): Installs to `/usr/local/bin/ltfs-gui`
- **User installation**: Installs to `~/.local/bin/ltfs-gui`
- **Symlink creation**: Creates a symlink in `~/.local/bin`
- **Desktop file installation**: Adds GUI to applications menu
- **Diagnostic tools check**: Verifies availability of optional diagnostic tools

The installer will also check for and guide you through installing diagnostic tools for enhanced functionality.

#### Option 2: Manual Global Installation

```bash
# Install globally (available system-wide)
sudo cp ltfs_gui.py /usr/local/bin/ltfs-gui
sudo chmod +x /usr/local/bin/ltfs-gui

# Install desktop file
mkdir -p ~/.local/share/applications
cp ltfs-gui.desktop ~/.local/share/applications/
```

#### Option 3: Manual Local Installation

```bash
# Install to user directory
mkdir -p ~/.local/bin
cp ltfs_gui.py ~/.local/bin/ltfs-gui
chmod +x ~/.local/bin/ltfs-gui

# Add to PATH if needed
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc

# Install desktop file
mkdir -p ~/.local/share/applications
cp ltfs-gui.desktop ~/.local/share/applications/
```

#### Option 4: Run Directly (No Installation)

```bash
# Make executable
chmod +x ltfs_gui.py

# Run directly
./ltfs_gui.py
```

## Usage

### Starting the Application

After installation, you can start the LTFS GUI in several ways:

#### Command Line
```bash
# If installed globally or locally with PATH updated
ltfs-gui

# Or run directly from source
./ltfs_gui.py
```

#### Desktop Application
- Look for "LTFS Manager" in your applications menu
- Or double-click the desktop file if installed

#### Test Installation
```bash
# Test GUI functionality
ltfs-gui-test  # if test script was installed globally
# Or
python3 test_ltfs_gui.py
```

### Tabs Overview

#### 1. Tape Drives Tab
- View all available tape drives on your system
- Refresh drive list
- Get detailed information about selected drives
- Check tape status using `mt` command
- Improved filtering to show only actual tape drives

#### 2. Mount/Unmount Tab
- **Mount Section**:
  - Select tape drive device
  - Specify mount point (default: `/mnt/ltfs`)
  - Set mount options (default includes uid/gid for user access)
  - Mount LTFS tape
- **Unmount Section**:
  - View currently mounted LTFS tapes
  - Unmount selected tapes
  - Open mounted tapes in file manager

#### 3. Compression Modes Tab
- **Dedicated compression control interface**
- Select from multiple compression modes:
  - **Default Compression**: Automatic algorithm selection, good balance
  - **High Compression**: Maximum space efficiency, slower processing
  - **Fast Compression**: Speed-optimized with moderate compression
  - **No Compression**: Disabled compression for pre-compressed data
  - **Legacy Mode**: Compatibility with older tape formats
- Apply compression settings to drives
- View current compression status
- Detailed descriptions of each mode's effects

#### 4. Format Tape Tab
- Select tape drive
- Optionally set tape label
- Format tape with LTFS filesystem
- **WARNING**: Formatting erases all data on the tape!

#### 5. Status Tab
- View LTFS version information
- Monitor available drives
- Check mounted tapes status
- System information
- Auto-refresh option (every 30 seconds)

#### 6. Diagnostics Tab
- **Comprehensive tape drive diagnostic suite**
- **Basic Diagnostics**:
  - Drive status checks
  - Tape health monitoring
  - Position information
  - Hardware details
- **Advanced Diagnostics**:
  - Read/write integrity tests
  - Load/unload cycle testing
  - Seek performance tests
  - Full diagnostic suite (10-30 minutes)
- **Tape Maintenance**:
  - Tape rewinding
  - Safe tape ejection
  - Tension release
  - Drive cleaning (with cleaning cartridge)
- **Drive Utilities**:
  - Drive reset
  - Log page retrieval
  - Error statistics
  - Firmware information
- **Results Management**:
  - Diagnostic results display
  - Save results to file
  - Export comprehensive HTML/text reports

#### 7. Log Tab
- View operation history with timestamps
- Clear log
- Save log to file

## Common Operations

### Mounting a Tape
1. Go to "Mount/Unmount" tab
2. Select your tape drive from the "Device" dropdown
3. Choose or create a mount point (e.g., `/mnt/ltfs`)
4. Click "Mount Tape"
5. Wait for the operation to complete
6. Access your tape files at the mount point

### Unmounting a Tape
1. Go to "Mount/Unmount" tab
2. Select the mounted tape from the list
3. Click "Unmount Selected"
4. Wait for safe unmount completion

### Formatting a New Tape
1. Insert a blank or reusable tape
2. Go to "Format Tape" tab
3. Select the tape drive

## Quantum LTO-5 Compatibility

**Important Note for Quantum LTO-5 Users**: The LTFS GUI includes automatic compatibility handling for Quantum LTO-5 tape drives.

### Automatic Detection
The GUI automatically detects Quantum LTO drives and applies optimal block size settings:
- **Quantum LTO-5**: Uses 64KB block size (instead of default 512KB)
- **Other drives**: Uses standard 512KB block size

### Manual Verification
If you encounter mounting issues with Quantum drives:

1. **Check drive detection**: Look for "Detected Quantum LTO drive" message in logs
2. **Verify block size**: Format logs should show "LTFS volume blocksize: 65536"
3. **Troubleshoot**: See [Quantum LTO-5 Compatibility Notes](QUANTUM_LTO5_COMPATIBILITY.md)

### Command Line Alternative
For manual formatting of Quantum LTO-5 drives:
```bash
sudo mkltfs -d /dev/st0 -n 'TAPE_LABEL' -b 65536 -f
```

**Why This Matters**: Default LTFS block size (512KB) causes mounting failures on Quantum LTO-5 drives due to driver compatibility issues. The 64KB block size ensures reliable operation.

For detailed technical information, see: **[QUANTUM_LTO5_COMPATIBILITY.md](QUANTUM_LTO5_COMPATIBILITY.md)**
4. Optionally enter a tape label
5. Check "Force format" if overwriting existing data
6. Click "Format Tape"
7. Confirm the operation (THIS WILL ERASE ALL DATA!)

## Default Mount Options

The GUI uses these default mount options:
- `-o uid=1000,gid=1000`: Allows your user to access files
- `-o devname=<device>`: Specifies the tape device

You can modify these options in the Mount tab before mounting.

## Troubleshooting

### Permission Issues
- Ensure your user has access to tape devices (usually `/dev/st*`)
- You may need to add your user to the `tape` group:
  ```bash
  sudo usermod -a -G tape $USER
  ```
- Log out and back in for group changes to take effect

### Tape Drive Not Detected
- Check if the tape drive is properly connected
- Verify SCSI tape devices exist: `ls -la /dev/st*`
- Check system logs: `dmesg | grep -i tape`

### Mount Failures
- Ensure the tape is LTFS-formatted
- Check if another process is using the tape drive
- Verify the tape is not write-protected when formatting

### GUI Won't Start
- Ensure Python 3 and tkinter are installed:
  ```bash
  python3 -c "import tkinter"
  ```
- Check the log tab for detailed error messages

## File Locations

- Main script: `ltfs_gui.py`
- Installation script: `install_ltfs_gui.sh`
- Diagnostic tools installer: `install_diagnostic_tools.sh`
- Desktop launcher: `ltfs-gui.desktop`
- Full documentation: `README_LTFS_GUI.md`
- Quick start guide: `QUICKSTART.md`
- Test script: `test_ltfs_gui.py` (if available)

## Supported Tape Drives

This GUI works with any tape drive supported by LTFS, including:
- IBM LTO drives (LTO-5 and newer)
- HP LTO drives (LTO-5 and newer)
- Other LTFS-compatible drives

## Security Notes

- The application requires permissions to access tape devices
- Mount operations may require elevated privileges
- Always safely unmount tapes before removing them
- Be cautious with the format operation as it permanently erases data

## License

This LTFS GUI wrapper is provided as-is for educational and practical use. Modify and distribute as needed.

## Support

For LTFS-specific issues, refer to the official LTFS documentation.
For GUI-specific issues, check the operation log for detailed error messages.

