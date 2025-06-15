# LTFS GUI Manager - Quick Start Guide

## 🚀 Quick Installation

```bash
# Clone or download LTFS with GUI
git clone <repository_url>
cd ltfs-release

# Run the installation script
./install_ltfs_gui.sh
```

## 📋 Prerequisites Checklist

### Required Components
- [ ] **LTFS installed** - `which ltfs` should return a path
- [ ] **Python 3** - `python3 --version` 
- [ ] **tkinter** - `python3 -c "import tkinter"`
- [ ] **Tape drive connected** - Check `/dev/st*` devices exist
- [ ] **User permissions** - Add to tape group: `sudo usermod -a -G tape $USER`

### Optional Diagnostic Tools (for full functionality)
```bash
# Install all diagnostic tools at once:
sudo apt install sg3-utils mtx lsscsi sysstat
```

## 🎯 First Time Setup

1. **Install the GUI**:
   ```bash
   ./install_ltfs_gui.sh
   # Choose option 1 for global installation (recommended)
   ```

2. **Add yourself to tape group** (if not already done):
   ```bash
   sudo usermod -a -G tape $USER
   # Log out and back in for this to take effect
   ```

3. **Launch the GUI**:
   ```bash
   ltfs-gui
   # Or from applications menu: "LTFS Manager"
   ```

## 🎮 Quick Operations

### Mount a Tape (Most Common)
1. Launch LTFS GUI: `ltfs-gui`
2. Go to **"Mount/Unmount"** tab
3. Select your tape drive from dropdown
4. Leave mount point as `/mnt/ltfs` (or choose custom)
5. Click **"Mount Tape"**
6. Wait for success message
7. Access files at `/mnt/ltfs`

### Format a New Tape
1. Insert blank/reusable tape
2. Go to **"Format Tape"** tab
3. Select drive, optionally add label
4. ⚠️ Check "Force format" if overwriting data
5. Click **"Format Tape"** and confirm

### Set Compression Mode
1. Go to **"Compression Modes"** tab
2. Select your drive
3. Choose compression mode:
   - **Default**: Good balance (recommended)
   - **High**: Maximum compression, slower
   - **Fast**: Speed optimized
   - **None**: No compression
   - **Legacy**: Compatibility mode
4. Click **"Apply Compression Settings"**

### Run Diagnostics
1. Go to **"Diagnostics"** tab
2. Select your drive
3. Start with **"Drive Status"** (basic check)
4. Try **"Tape Status"** for health info
5. Use **"Full Diagnostic"** for comprehensive testing

## 🔧 Common Issues & Solutions

### "Permission denied" errors
```bash
# Add yourself to tape group and restart session
sudo usermod -a -G tape $USER
# Then log out and back in
```

### "No tape drives found"
```bash
# Check if drives are detected
ls -la /dev/st* /dev/nst*
# Check system logs
dmesg | grep -i tape
```

### "Mount failed"
- Ensure tape is LTFS-formatted (use Format tab if needed)
- Check if another process is using the drive
- Try ejecting and reinserting the tape

### GUI won't start
```bash
# Test dependencies
python3 -c "import tkinter; print('GUI support OK')"
# Check if LTFS is in PATH
which ltfs
```

## 📁 All Features Overview

### Tab 1: Tape Drives
- 📋 List all available tape drives
- 🔍 Get detailed drive information
- 🔄 Refresh drive list

### Tab 2: Mount/Unmount  
- 💾 Mount LTFS tapes to filesystem
- 🔓 Safely unmount tapes
- 📂 Open mounted tapes in file manager

### Tab 3: Compression Modes
- ⚙️ Configure tape compression settings
- 📊 View compression mode descriptions
- 🎛️ Apply settings to drives

### Tab 4: Format Tape
- 🆕 Format blank tapes with LTFS
- 🏷️ Add optional tape labels
- ⚠️ Force format existing tapes

### Tab 5: Status
- 📈 System and LTFS status overview
- 🔄 Auto-refresh every 30 seconds
- 📊 Mounted tapes summary

### Tab 6: Diagnostics
- 🔍 **Basic**: Drive status, tape health, position
- 🧪 **Advanced**: Read/write tests, load/unload tests
- 🛠️ **Maintenance**: Rewind, eject, tension release
- 📊 **Utilities**: Reset, logs, error stats, firmware

### Tab 7: Log
- 📝 View all operation history
- 💾 Save logs to file
- 🗑️ Clear log display

## 🎓 Pro Tips

### Speed Up Operations
- Use **Fast Compression** mode for regular backups
- Use **Non-rewinding** devices (nst*) for multiple operations
- Keep mount points persistent across sessions

### Maintenance Best Practices
- Run **Drive Status** check before important operations
- Use **Tape Status** to monitor tape health
- Run **Full Diagnostic** monthly for production drives
- Always **Safely Unmount** before removing tapes

### Troubleshooting Workflow
1. **Basic Checks**: Drive Status → Tape Status
2. **Connection Test**: Load/Unload Test
3. **Performance Test**: Seek Test
4. **Data Integrity**: Read/Write Test
5. **Full Analysis**: Full Diagnostic Suite

## 📞 Getting Help

### Built-in Help
- Check the **Log tab** for detailed error messages
- Use **Drive Status** in Diagnostics for hardware issues
- Review compression mode descriptions before changing settings

### Documentation
- Full documentation: `README_LTFS_GUI.md`
- LTFS official docs for underlying functionality
- System logs: `dmesg | grep -i tape`

### Quick Diagnostics
```bash
# Test GUI functionality
python3 test_ltfs_gui.py

# Check tape devices
ls -la /dev/st* /dev/nst*

# Check permissions
groups | grep tape

# Test LTFS
mt -f /dev/st0 status
```

---

**🎉 You're ready to go!** Start with mounting a tape and explore the other features as needed.

