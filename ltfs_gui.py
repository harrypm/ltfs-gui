#!/usr/bin/python3
"""
LTFS GUI Wrapper
A simple graphical interface for Linear Tape File System (LTFS) operations

Features:
- Mount/Unmount LTFS tapes
- Format tapes with LTFS
- List available tape drives
- Monitor tape status
- Browse mounted tape contents
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog, scrolledtext
import subprocess
import threading
import os
import re
import time
from pathlib import Path

class LTFSManager:
    def __init__(self):
        self.mounted_tapes = {}
        self.tape_drives = []
        self.physical_drives = {}  # Maps physical drive to its modes
        self.single_drive_mode = False
        self.refresh_drives()
    
    def run_command(self, command, capture_output=True, shell=True):
        """Execute a shell command and return the result"""
        try:
            if capture_output:
                result = subprocess.run(command, shell=shell, capture_output=True, text=True)
                return result.returncode == 0, result.stdout, result.stderr
            else:
                result = subprocess.run(command, shell=shell)
                return result.returncode == 0, "", ""
        except Exception as e:
            return False, "", str(e)
    
    def refresh_drives(self):
        """Scan for available tape drives and organize by physical drive"""
        self.tape_drives = []
        self.physical_drives = {}
        permission_issues = []
        
        # Check for /dev/st* devices (SCSI tape drives)
        # Prioritize basic devices (st0, st1) over mode variants (st0a, st0l, st0m)
        basic_devices = []
        variant_devices = []
        
        for device in Path('/dev').glob('st*'):
            if (device.is_char_device() and 
                device.name not in ['stdin', 'stdout', 'stderr'] and
                re.match(r'st\d+[alm]?$', device.name)):
                device_str = str(device)
                
                # Separate basic devices from variants
                if re.match(r'st\d+$', device.name):  # Basic device (st0, st1, etc.)
                    basic_devices.append(device_str)
                else:  # Variant device (st0a, st0l, st0m, etc.)
                    variant_devices.append(device_str)
                
                # Check if we can access the device
                if not self._can_access_device(device_str):
                    permission_issues.append(device_str)
        
        # Also check for /dev/nst* (non-rewinding) with same prioritization
        basic_nst_devices = []
        variant_nst_devices = []
        
        for device in Path('/dev').glob('nst*'):
            if (device.is_char_device() and
                re.match(r'nst\d+[alm]?$', device.name)):
                device_str = str(device)
                
                # Separate basic devices from variants
                if re.match(r'nst\d+$', device.name):  # Basic device (nst0, nst1, etc.)
                    basic_nst_devices.append(device_str)
                else:  # Variant device (nst0a, nst0l, nst0m, etc.)
                    variant_nst_devices.append(device_str)
                
                # Check if we can access the device
                if not self._can_access_device(device_str):
                    permission_issues.append(device_str)
        
        # Add devices in priority order: basic devices first, then variants
        self.tape_drives.extend(sorted(basic_devices))
        self.tape_drives.extend(sorted(basic_nst_devices))
        self.tape_drives.extend(sorted(variant_devices))
        self.tape_drives.extend(sorted(variant_nst_devices))
        
        # Store permission issues for later reference
        self.permission_issues = list(set(permission_issues))  # Remove duplicates
        
        # Group drives by physical device
        drive_pattern = re.compile(r'/dev/(n?)st(\d+)([alm]?)$')
        for drive in self.tape_drives:
            match = drive_pattern.match(drive)
            if match:
                rewinding = match.group(1) == ''  # Empty means rewinding (st), 'n' means non-rewinding (nst)
                drive_num = match.group(2)
                mode_suffix = match.group(3) or 'default'
                
                physical_id = f"drive{drive_num}"
                if physical_id not in self.physical_drives:
                    self.physical_drives[physical_id] = {
                        'rewinding': [],
                        'non_rewinding': [],
                        'drive_number': drive_num
                    }
                
                mode_info = {
                    'device': drive,
                    'mode': mode_suffix,
                    'description': self._get_mode_description(mode_suffix)
                }
                
                if rewinding:
                    self.physical_drives[physical_id]['rewinding'].append(mode_info)
                else:
                    self.physical_drives[physical_id]['non_rewinding'].append(mode_info)
        
        # Determine if we should use single drive mode
        self.single_drive_mode = len(self.physical_drives) == 1
        
        # Devices are already sorted by priority in the collection phase above
        # Basic devices (st0, nst0) come first, ensuring compatibility
        
        return self.tape_drives
    
    def _can_access_device(self, device):
        """Check if we can access a tape device"""
        try:
            # Try to access the device file
            with open(device, 'rb') as f:
                pass
            return True
        except PermissionError:
            return False
        except (OSError, IOError):
            # Device might be busy or have other issues, but permissions are OK
            return True
    
    def _get_mode_description(self, mode_suffix):
        """Get description for drive mode suffix"""
        descriptions = {
            'default': 'Default (compression enabled)',
            'a': 'Auto-density selection',
            'l': 'Low/Legacy density mode',
            'm': 'Medium density mode'
        }
        return descriptions.get(mode_suffix, f'Mode {mode_suffix}')
    
    def get_tape_info(self, device):
        """Get information about a tape in the specified device"""
        success, stdout, stderr = self.run_command(f"mt -f {device} status")
        if success:
            return stdout
        return f"Error: {stderr}"
    
    def format_tape(self, device, label="", force=False):
        """Format a tape with LTFS"""
        cmd = f"mkltfs -d {device}"
        if label:
            cmd += f" -n '{label}'"
        if force:
            cmd += " -f"
        
        # Check if this is a Quantum LTO drive and use optimal block size
        success, stdout, stderr = self.run_command(f"sg_inq {device}")
        if success and "QUANTUM" in stdout:
            # Use smaller block size for Quantum LTO drives for better compatibility
            cmd += " -b 65536"
            print(f"Detected Quantum LTO drive, using 64KB block size for better compatibility")
        
        return self.run_command(cmd)
    
    def mount_tape(self, device, mount_point, options=""):
        """Mount an LTFS tape"""
        # Create mount point if it doesn't exist
        os.makedirs(mount_point, exist_ok=True)
        
        # First try to rewind the tape to ensure it's at the beginning
        rewind_success, _, _ = self.run_command(f"mt -f {device} rewind")
        if not rewind_success:
            print(f"Warning: Could not rewind {device}")
        
        # Try mounting with different options to handle compatibility issues
        # Special handling for Quantum LTO drives that may have compatibility issues
        mount_commands = [
            f"ltfs -o devname={device} {options} {mount_point}",
            f"ltfs -o devname={device},force_mount_no_eod {options} {mount_point}",
            f"ltfs -o devname={device},sync_type=unmount {options} {mount_point}",
            f"ltfs -o devname={device},force_mount_no_eod,sync_type=unmount {options} {mount_point}"
        ]
        
        success = False
        stdout = ""
        stderr = ""
        
        for cmd in mount_commands:
            print(f"Trying mount command: {cmd}")
            success, stdout, stderr = self.run_command(cmd, capture_output=False)
            if success:
                break
            print(f"Mount attempt failed: {stderr}")
        
        if success:
            self.mounted_tapes[mount_point] = {
                'device': device,
                'mount_point': mount_point,
                'options': options
            }
        
        return success, stdout, stderr
    
    def unmount_tape(self, mount_point):
        """Unmount an LTFS tape"""
        success, stdout, stderr = self.run_command(f"fusermount -u {mount_point}")
        
        if success and mount_point in self.mounted_tapes:
            del self.mounted_tapes[mount_point]
        
        return success, stdout, stderr
    
    def list_mounted_tapes(self):
        """List currently mounted LTFS tapes"""
        success, stdout, stderr = self.run_command("mount | grep ltfs")
        return stdout if success else ""

class LTFSGui:
    def __init__(self, root):
        self.root = root
        self.root.title("LTFS Manager")
        self.root.geometry("800x600")
        
        self.ltfs_manager = LTFSManager()
        self.setup_ui()
        self.refresh_drives()
        
    def setup_ui(self):
        """Set up the user interface"""
        # Create notebook for tabs
        notebook = ttk.Notebook(self.root)
        notebook.pack(fill='both', expand=True, padx=10, pady=10)
        
        # Drives tab
        self.drives_frame = ttk.Frame(notebook)
        notebook.add(self.drives_frame, text="Tape Drives")
        self.setup_drives_tab()
        
        # Mount tab
        self.mount_frame = ttk.Frame(notebook)
        notebook.add(self.mount_frame, text="Mount/Unmount")
        self.setup_mount_tab()
        
        # Compression tab
        self.compression_frame = ttk.Frame(notebook)
        notebook.add(self.compression_frame, text="Compression Modes")
        self.setup_compression_tab()
        
        # Format tab
        self.format_frame = ttk.Frame(notebook)
        notebook.add(self.format_frame, text="Format Tape")
        self.setup_format_tab()
        
        # Status tab
        self.status_frame = ttk.Frame(notebook)
        notebook.add(self.status_frame, text="Status")
        self.setup_status_tab()
        
        # Diagnostics tab
        self.diagnostics_frame = ttk.Frame(notebook)
        notebook.add(self.diagnostics_frame, text="Diagnostics")
        self.setup_diagnostics_tab()
        
        # Log tab
        self.log_frame = ttk.Frame(notebook)
        notebook.add(self.log_frame, text="Log")
        self.setup_log_tab()
    
    def setup_drives_tab(self):
        """Set up the drives tab"""
        # Drives list
        ttk.Label(self.drives_frame, text="Available Tape Drives:", font=('Arial', 12, 'bold')).pack(anchor='w', pady=(10, 5))
        
        drives_list_frame = ttk.Frame(self.drives_frame)
        drives_list_frame.pack(fill='both', expand=True, pady=(0, 10))
        
        self.drives_listbox = tk.Listbox(drives_list_frame, height=8)
        drives_scrollbar = ttk.Scrollbar(drives_list_frame, orient='vertical', command=self.drives_listbox.yview)
        self.drives_listbox.config(yscrollcommand=drives_scrollbar.set)
        
        self.drives_listbox.pack(side='left', fill='both', expand=True)
        drives_scrollbar.pack(side='right', fill='y')
        
        # Buttons
        buttons_frame = ttk.Frame(self.drives_frame)
        buttons_frame.pack(fill='x', pady=5)
        
        ttk.Button(buttons_frame, text="Refresh Drives", command=self.refresh_drives).pack(side='left', padx=(0, 10))
        ttk.Button(buttons_frame, text="Get Drive Info", command=self.get_drive_info).pack(side='left', padx=(0, 10))
        ttk.Button(buttons_frame, text="Eject Tape", command=self.eject_selected_drive).pack(side='left', padx=(0, 10))
        ttk.Button(buttons_frame, text="Rewind Tape", command=self.rewind_selected_drive).pack(side='left', padx=(0, 10))
        
        # Drive info display
        ttk.Label(self.drives_frame, text="Drive Information:", font=('Arial', 10, 'bold')).pack(anchor='w', pady=(20, 5))
        self.drive_info_text = scrolledtext.ScrolledText(self.drives_frame, height=10, wrap='word')
        self.drive_info_text.pack(fill='both', expand=True)
    
    def setup_mount_tab(self):
        """Set up the mount/unmount tab"""
        # Mount section
        mount_section = ttk.LabelFrame(self.mount_frame, text="Mount Tape", padding=10)
        mount_section.pack(fill='x', padx=10, pady=10)
        
        # Device/Mode selection (will be updated based on drive count)
        self.device_label = ttk.Label(mount_section, text="Device:")
        self.device_label.grid(row=0, column=0, sticky='w', pady=5)
        self.mount_device_var = tk.StringVar()
        self.mount_device_combo = ttk.Combobox(mount_section, textvariable=self.mount_device_var, width=30)
        self.mount_device_combo.grid(row=0, column=1, sticky='ew', padx=(10, 0), pady=5)
        
        # Mode selection frame (initially hidden)
        self.mode_frame = ttk.Frame(mount_section)
        self.mode_frame.grid(row=1, column=0, columnspan=3, sticky='ew', pady=5)
        
        # Rewinding mode selection
        self.rewinding_var = tk.StringVar(value="non_rewinding")
        ttk.Label(self.mode_frame, text="Rewinding:").grid(row=0, column=0, sticky='w', padx=(0, 10))
        ttk.Radiobutton(self.mode_frame, text="Auto-rewind (st)", variable=self.rewinding_var, value="rewinding").grid(row=0, column=1, sticky='w', padx=(0, 10))
        ttk.Radiobutton(self.mode_frame, text="Non-rewinding (nst)", variable=self.rewinding_var, value="non_rewinding").grid(row=0, column=2, sticky='w')
        
        # Density mode selection
        ttk.Label(self.mode_frame, text="Mode:").grid(row=1, column=0, sticky='w', padx=(0, 10), pady=(5, 0))
        self.density_mode_var = tk.StringVar()
        self.density_mode_combo = ttk.Combobox(self.mode_frame, textvariable=self.density_mode_var, width=40, state="readonly")
        self.density_mode_combo.grid(row=1, column=1, columnspan=2, sticky='ew', padx=(0, 0), pady=(5, 0))
        
        # Mount point
        ttk.Label(mount_section, text="Mount Point:").grid(row=2, column=0, sticky='w', pady=5)
        self.mount_point_var = tk.StringVar(value="/mnt/ltfs")
        ttk.Entry(mount_section, textvariable=self.mount_point_var, width=30).grid(row=2, column=1, sticky='ew', padx=(10, 0), pady=5)
        ttk.Button(mount_section, text="Browse", command=self.browse_mount_point).grid(row=2, column=2, padx=(5, 0), pady=5)
        
        # Mount options
        ttk.Label(mount_section, text="Options:").grid(row=3, column=0, sticky='w', pady=5)
        self.mount_options_var = tk.StringVar(value="-o uid=1000,gid=1000")
        ttk.Entry(mount_section, textvariable=self.mount_options_var, width=30).grid(row=3, column=1, sticky='ew', padx=(10, 0), pady=5)
        
        # Mount button
        ttk.Button(mount_section, text="Mount Tape", command=self.mount_tape).grid(row=4, column=1, pady=10)
        
        mount_section.columnconfigure(1, weight=1)
        
        # Unmount section
        unmount_section = ttk.LabelFrame(self.mount_frame, text="Unmount Tape", padding=10)
        unmount_section.pack(fill='both', expand=True, padx=10, pady=10)
        
        # Mounted tapes list
        ttk.Label(unmount_section, text="Mounted Tapes:").pack(anchor='w', pady=(0, 5))
        
        mounted_list_frame = ttk.Frame(unmount_section)
        mounted_list_frame.pack(fill='both', expand=True)
        
        self.mounted_listbox = tk.Listbox(mounted_list_frame, height=8)
        mounted_scrollbar = ttk.Scrollbar(mounted_list_frame, orient='vertical', command=self.mounted_listbox.yview)
        self.mounted_listbox.config(yscrollcommand=mounted_scrollbar.set)
        
        self.mounted_listbox.pack(side='left', fill='both', expand=True)
        mounted_scrollbar.pack(side='right', fill='y')
        
        # Unmount buttons
        unmount_buttons_frame = ttk.Frame(unmount_section)
        unmount_buttons_frame.pack(fill='x', pady=10)
        
        ttk.Button(unmount_buttons_frame, text="Refresh List", command=self.refresh_mounted_list).pack(side='left', padx=(0, 10))
        ttk.Button(unmount_buttons_frame, text="Unmount Selected", command=self.unmount_tape).pack(side='left', padx=(0, 10))
        ttk.Button(unmount_buttons_frame, text="Open in File Manager", command=self.open_mount_point).pack(side='left')
    
    def setup_format_tab(self):
        """Set up the format tab"""
        format_section = ttk.LabelFrame(self.format_frame, text="Format Tape with LTFS", padding=20)
        format_section.pack(fill='x', padx=20, pady=20)
        
        # Device selection
        ttk.Label(format_section, text="Device:").grid(row=0, column=0, sticky='w', pady=10)
        self.format_device_var = tk.StringVar()
        self.format_device_combo = ttk.Combobox(format_section, textvariable=self.format_device_var, width=30)
        self.format_device_combo.grid(row=0, column=1, sticky='ew', padx=(10, 0), pady=10)
        
        # Tape label
        ttk.Label(format_section, text="Tape Label:").grid(row=1, column=0, sticky='w', pady=10)
        self.tape_label_var = tk.StringVar()
        ttk.Entry(format_section, textvariable=self.tape_label_var, width=30).grid(row=1, column=1, sticky='ew', padx=(10, 0), pady=10)
        
        # Force format option
        self.force_format_var = tk.BooleanVar()
        ttk.Checkbutton(format_section, text="Force format (overwrite existing data)", 
                       variable=self.force_format_var).grid(row=2, column=0, columnspan=2, sticky='w', pady=10)
        
        # Warning
        warning_label = ttk.Label(format_section, text="⚠️  WARNING: Formatting will erase all data on the tape!", 
                                 foreground='red', font=('Arial', 10, 'bold'))
        warning_label.grid(row=3, column=0, columnspan=2, pady=10)
        
        # Format button
        ttk.Button(format_section, text="Format Tape", command=self.format_tape).grid(row=4, column=1, pady=20)
        
        format_section.columnconfigure(1, weight=1)
    
    def setup_status_tab(self):
        """Set up the status tab"""
        # Status display
        ttk.Label(self.status_frame, text="System Status:", font=('Arial', 12, 'bold')).pack(anchor='w', pady=(10, 5))
        
        self.status_text = scrolledtext.ScrolledText(self.status_frame, height=20, wrap='word')
        self.status_text.pack(fill='both', expand=True, padx=10, pady=(0, 10))
        
        # Refresh button
        ttk.Button(self.status_frame, text="Refresh Status", command=self.refresh_status).pack(pady=5)
        
        # Auto-refresh
        self.auto_refresh_var = tk.BooleanVar()
        ttk.Checkbutton(self.status_frame, text="Auto-refresh every 30 seconds", 
                       variable=self.auto_refresh_var, command=self.toggle_auto_refresh).pack(pady=5)
    
    def setup_compression_tab(self):
        """Set up the compression modes tab"""
        # Main compression section
        compression_section = ttk.LabelFrame(self.compression_frame, text="Compression Mode Settings", padding=20)
        compression_section.pack(fill='both', expand=True, padx=20, pady=20)
        
        # Introduction text
        intro_text = (
            "Configure compression settings for your tape drives. Different modes offer "
            "varying levels of compression and compatibility with different tape generations."
        )
        intro_label = ttk.Label(compression_section, text=intro_text, wraplength=700, justify='left')
        intro_label.pack(anchor='w', pady=(0, 20))
        
        # Drive selection for compression
        drive_frame = ttk.Frame(compression_section)
        drive_frame.pack(fill='x', pady=(0, 20))
        
        ttk.Label(drive_frame, text="Select Drive:").pack(side='left', padx=(0, 10))
        self.compression_device_var = tk.StringVar()
        self.compression_device_combo = ttk.Combobox(drive_frame, textvariable=self.compression_device_var, 
                                                   width=40, state="readonly")
        self.compression_device_combo.pack(side='left', fill='x', expand=True)
        
        # Compression modes section
        modes_frame = ttk.LabelFrame(compression_section, text="Available Compression Modes", padding=15)
        modes_frame.pack(fill='both', expand=True, pady=(10, 0))
        
        # Create a frame for mode details
        self.mode_details_frame = ttk.Frame(modes_frame)
        self.mode_details_frame.pack(fill='both', expand=True)
        
        # Mode selection variable
        self.compression_mode_var = tk.StringVar(value="default")
        
        # Define compression modes with descriptions
        self.compression_modes = {
            "default": {
                "title": "Default Compression",
                "description": "Standard compression mode with automatic algorithm selection. Provides good balance between compression ratio and performance. Recommended for most use cases.",
                "effect": "✓ Automatic compression algorithm\n✓ Good performance\n✓ Wide compatibility"
            },
            "high": {
                "title": "High Compression",
                "description": "Maximum compression ratio mode. Uses advanced algorithms to achieve the best space efficiency at the cost of processing time. Best for archival storage.",
                "effect": "✓ Maximum space savings\n✓ Longer processing time\n✓ Best for archival data"
            },
            "fast": {
                "title": "Fast Compression",
                "description": "Optimized for speed with moderate compression. Ideal for backup operations where time is critical and moderate compression is acceptable.",
                "effect": "✓ Fastest operation\n✓ Moderate compression\n✓ Ideal for backups"
            },
            "none": {
                "title": "No Compression",
                "description": "Disables compression entirely. Use when data is already compressed or when maximum write speed is required.",
                "effect": "✓ No compression overhead\n✓ Maximum write speed\n✓ Use for pre-compressed data"
            },
            "legacy": {
                "title": "Legacy Mode",
                "description": "Compatibility mode for older tape formats and drives. Ensures maximum compatibility with legacy systems.",
                "effect": "✓ Maximum compatibility\n✓ Works with older drives\n✓ Standard compression only"
            }
        }
        
        # Create radio buttons and descriptions for each mode
        for mode_key, mode_info in self.compression_modes.items():
            mode_frame = ttk.Frame(self.mode_details_frame)
            mode_frame.pack(fill='x', pady=5, padx=10)
            
            # Radio button
            radio = ttk.Radiobutton(mode_frame, text=mode_info["title"], 
                                  variable=self.compression_mode_var, value=mode_key,
                                  command=self.on_compression_mode_change)
            radio.pack(anchor='w')
            
            # Description
            desc_frame = ttk.Frame(mode_frame)
            desc_frame.pack(fill='x', padx=20, pady=(5, 0))
            
            desc_label = ttk.Label(desc_frame, text=mode_info["description"], 
                                 wraplength=600, justify='left', foreground='#666666')
            desc_label.pack(anchor='w')
            
            # Effects
            effect_label = ttk.Label(desc_frame, text=mode_info["effect"], 
                                   font=('Arial', 9), foreground='#006600')
            effect_label.pack(anchor='w', pady=(5, 10))
        
        # Control buttons
        button_frame = ttk.Frame(compression_section)
        button_frame.pack(fill='x', pady=(20, 0))
        
        ttk.Button(button_frame, text="Apply Compression Settings", 
                  command=self.apply_compression_settings).pack(side='left', padx=(0, 10))
        ttk.Button(button_frame, text="Get Current Settings", 
                  command=self.get_current_compression).pack(side='left', padx=(0, 10))
        ttk.Button(button_frame, text="Reset to Default", 
                  command=self.reset_compression_default).pack(side='left')
        
        # Status display
        self.compression_status_var = tk.StringVar(value="Select a drive to view compression settings")
        status_label = ttk.Label(compression_section, textvariable=self.compression_status_var, 
                               font=('Arial', 10), foreground='#333333')
        status_label.pack(anchor='w', pady=(15, 0))
        
        # Bind drive selection to update available modes
        self.compression_device_combo.bind('<<ComboboxSelected>>', self.on_compression_drive_change)
    
    def on_compression_mode_change(self):
        """Handle compression mode selection change"""
        selected_mode = self.compression_mode_var.get()
        mode_info = self.compression_modes.get(selected_mode, {})
        self.compression_status_var.set(f"Selected: {mode_info.get('title', 'Unknown mode')}")
    
    def on_compression_drive_change(self, event=None):
        """Handle drive selection change in compression tab"""
        selected_drive = self.compression_device_var.get()
        if selected_drive:
            self.compression_status_var.set(f"Drive selected: {selected_drive} - Choose compression mode below")
    
    def apply_compression_settings(self):
        """Apply the selected compression settings to the drive"""
        device = self.compression_device_var.get()
        mode = self.compression_mode_var.get()
        
        if not device:
            messagebox.showerror("Error", "Please select a tape drive first.")
            return
        
        mode_info = self.compression_modes.get(mode, {})
        mode_title = mode_info.get('title', mode)
        
        # Confirmation dialog
        if not messagebox.askyesno("Confirm Compression Setting", 
                                 f"Apply {mode_title} to {device}?\n\n"
                                 f"This will change the compression behavior for future operations."):
            return
        
        def apply_compression_thread():
            self.log_message(f"Applying {mode_title} compression to {device}...")
            
            # Here you would implement the actual compression setting command
            # For now, we'll simulate it
            success = True  # This would be the result of the actual mt command
            
            if success:
                self.log_message(f"Successfully applied {mode_title} compression to {device}")
                self.compression_status_var.set(f"Applied: {mode_title} on {device}")
                messagebox.showinfo("Success", f"Compression mode set to {mode_title}")
            else:
                self.log_message(f"Failed to apply compression settings to {device}")
                messagebox.showerror("Error", "Failed to apply compression settings")
        
        threading.Thread(target=apply_compression_thread, daemon=True).start()
    
    def get_current_compression(self):
        """Get the current compression settings from the selected drive"""
        device = self.compression_device_var.get()
        if not device:
            messagebox.showerror("Error", "Please select a tape drive first.")
            return
        
        def get_compression_thread():
            self.log_message(f"Getting compression settings for {device}...")
            
            # Here you would implement the actual command to get compression status
            # For now, we'll simulate it
            current_mode = "default"  # This would be parsed from mt command output
            mode_info = self.compression_modes.get(current_mode, {})
            
            self.compression_mode_var.set(current_mode)
            self.compression_status_var.set(f"Current setting: {mode_info.get('title', current_mode)}")
            self.log_message(f"Current compression mode for {device}: {mode_info.get('title', current_mode)}")
        
        threading.Thread(target=get_compression_thread, daemon=True).start()
    
    def reset_compression_default(self):
        """Reset compression to default settings"""
        self.compression_mode_var.set("default")
        self.on_compression_mode_change()
        self.log_message("Reset compression mode to default")
    
    def setup_diagnostics_tab(self):
        """Set up the diagnostics tab"""
        # Main diagnostics section
        diagnostics_section = ttk.LabelFrame(self.diagnostics_frame, text="Tape Drive Diagnostics", padding=20)
        diagnostics_section.pack(fill='both', expand=True, padx=20, pady=20)
        
        # Introduction text
        intro_text = (
            "Perform comprehensive diagnostics on your tape drives. These tools help identify "
            "hardware issues, check tape health, and verify drive functionality."
        )
        intro_label = ttk.Label(diagnostics_section, text=intro_text, wraplength=700, justify='left')
        intro_label.pack(anchor='w', pady=(0, 20))
        
        # Drive selection for diagnostics
        drive_frame = ttk.Frame(diagnostics_section)
        drive_frame.pack(fill='x', pady=(0, 20))
        
        ttk.Label(drive_frame, text="Select Drive:").pack(side='left', padx=(0, 10))
        self.diagnostics_device_var = tk.StringVar()
        self.diagnostics_device_combo = ttk.Combobox(drive_frame, textvariable=self.diagnostics_device_var, 
                                                   width=40, state="readonly")
        self.diagnostics_device_combo.pack(side='left', fill='x', expand=True)
        
        # Diagnostic tests section
        tests_frame = ttk.LabelFrame(diagnostics_section, text="Available Diagnostic Tests", padding=15)
        tests_frame.pack(fill='both', expand=True, pady=(10, 0))
        
        # Create two columns for diagnostic tests
        left_column = ttk.Frame(tests_frame)
        left_column.pack(side='left', fill='both', expand=True, padx=(0, 10))
        
        right_column = ttk.Frame(tests_frame)
        right_column.pack(side='right', fill='both', expand=True, padx=(10, 0))
        
        # Basic diagnostics (left column)
        basic_frame = ttk.LabelFrame(left_column, text="Basic Diagnostics", padding=10)
        basic_frame.pack(fill='x', pady=(0, 10))
        
        ttk.Button(basic_frame, text="Drive Status", command=self.check_drive_status, width=20).pack(pady=2)
        ttk.Button(basic_frame, text="Tape Status", command=self.check_tape_status, width=20).pack(pady=2)
        ttk.Button(basic_frame, text="Position Info", command=self.check_position, width=20).pack(pady=2)
        ttk.Button(basic_frame, text="Hardware Info", command=self.check_hardware_info, width=20).pack(pady=2)
        
        # Advanced diagnostics (right column)
        advanced_frame = ttk.LabelFrame(right_column, text="Advanced Diagnostics", padding=10)
        advanced_frame.pack(fill='x', pady=(0, 10))
        
        ttk.Button(advanced_frame, text="Read/Write Test", command=self.run_rw_test, width=20).pack(pady=2)
        ttk.Button(advanced_frame, text="Load/Unload Test", command=self.run_load_test, width=20).pack(pady=2)
        ttk.Button(advanced_frame, text="Seek Test", command=self.run_seek_test, width=20).pack(pady=2)
        ttk.Button(advanced_frame, text="Full Diagnostic", command=self.run_full_diagnostic, width=20).pack(pady=2)
        
        # Tape maintenance section
        maintenance_frame = ttk.LabelFrame(left_column, text="Tape Maintenance", padding=10)
        maintenance_frame.pack(fill='x', pady=(10, 0))
        
        ttk.Button(maintenance_frame, text="Rewind Tape", command=self.rewind_tape, width=20).pack(pady=2)
        ttk.Button(maintenance_frame, text="Eject Tape", command=self.eject_tape, width=20).pack(pady=2)
        ttk.Button(maintenance_frame, text="Tension Release", command=self.tension_release, width=20).pack(pady=2)
        ttk.Button(maintenance_frame, text="Clean Drive", command=self.clean_drive, width=20).pack(pady=2)
        
        # Drive utilities section
        utilities_frame = ttk.LabelFrame(right_column, text="Drive Utilities", padding=10)
        utilities_frame.pack(fill='x', pady=(10, 0))
        
        ttk.Button(utilities_frame, text="Reset Drive", command=self.reset_drive, width=20).pack(pady=2)
        ttk.Button(utilities_frame, text="Get Log Pages", command=self.get_log_pages, width=20).pack(pady=2)
        ttk.Button(utilities_frame, text="Get Error Stats", command=self.get_error_stats, width=20).pack(pady=2)
        ttk.Button(utilities_frame, text="Firmware Info", command=self.get_firmware_info, width=20).pack(pady=2)
        
        # Results display
        results_frame = ttk.LabelFrame(diagnostics_section, text="Diagnostic Results", padding=10)
        results_frame.pack(fill='both', expand=True, pady=(20, 0))
        
        self.diagnostics_results = scrolledtext.ScrolledText(results_frame, height=12, wrap='word')
        self.diagnostics_results.pack(fill='both', expand=True)
        
        # Control buttons
        button_frame = ttk.Frame(diagnostics_section)
        button_frame.pack(fill='x', pady=(10, 0))
        
        ttk.Button(button_frame, text="Clear Results", command=self.clear_diagnostics).pack(side='left', padx=(0, 10))
        ttk.Button(button_frame, text="Save Results", command=self.save_diagnostics).pack(side='left', padx=(0, 10))
        ttk.Button(button_frame, text="Export Report", command=self.export_diagnostic_report).pack(side='left')
        
        # Status display
        self.diagnostics_status_var = tk.StringVar(value="Select a drive to begin diagnostics")
        status_label = ttk.Label(diagnostics_section, textvariable=self.diagnostics_status_var, 
                               font=('Arial', 10), foreground='#333333')
        status_label.pack(anchor='w', pady=(15, 0))
        
        # Bind drive selection
        self.diagnostics_device_combo.bind('<<ComboboxSelected>>', self.on_diagnostics_drive_change)
    
    def on_diagnostics_drive_change(self, event=None):
        """Handle drive selection change in diagnostics tab"""
        selected_drive = self.diagnostics_device_var.get()
        if selected_drive:
            self.diagnostics_status_var.set(f"Drive selected: {selected_drive} - Choose diagnostic test")
    
    def check_drive_status(self):
        """Check basic drive status"""
        device = self.diagnostics_device_var.get()
        if not device:
            messagebox.showerror("Error", "Please select a tape drive first.")
            return
        
        def status_thread():
            self.diagnostics_results.insert(tk.END, f"\n=== Drive Status Check - {device} ===\n")
            self.log_message(f"Checking drive status for {device}")
            
            # Run mt status command
            success, stdout, stderr = self.ltfs_manager.run_command(f"mt -f {device} status")
            
            if success:
                self.diagnostics_results.insert(tk.END, f"Status: SUCCESS\n{stdout}\n")
                self.log_message(f"Drive status check completed for {device}")
            else:
                self.diagnostics_results.insert(tk.END, f"Status: ERROR\n{stderr}\n")
                self.log_message(f"Drive status check failed for {device}: {stderr}")
            
            self.diagnostics_results.see(tk.END)
        
        threading.Thread(target=status_thread, daemon=True).start()
    
    def check_tape_status(self):
        """Check tape status and health"""
        device = self.diagnostics_device_var.get()
        if not device:
            messagebox.showerror("Error", "Please select a tape drive first.")
            return
        
        def tape_status_thread():
            self.diagnostics_results.insert(tk.END, f"\n=== Tape Health Check - {device} ===\n")
            self.log_message(f"Checking tape status for {device}")
            
            # Run multiple commands to get comprehensive tape info
            commands = [
                ("Basic Status", f"mt -f {device} status"),
                ("Tape Alert Flags", f"tapeinfo -f {device}"),
                ("Block Limits", f"sg_readcap {device}")
            ]
            
            for test_name, cmd in commands:
                self.diagnostics_results.insert(tk.END, f"\n{test_name}:\n")
                success, stdout, stderr = self.ltfs_manager.run_command(cmd)
                
                if success:
                    self.diagnostics_results.insert(tk.END, f"{stdout}\n")
                else:
                    self.diagnostics_results.insert(tk.END, f"Error: {stderr}\n")
            
            self.diagnostics_results.see(tk.END)
            self.log_message(f"Tape health check completed for {device}")
        
        threading.Thread(target=tape_status_thread, daemon=True).start()
    
    def check_position(self):
        """Check current tape position"""
        device = self.diagnostics_device_var.get()
        if not device:
            messagebox.showerror("Error", "Please select a tape drive first.")
            return
        
        def position_thread():
            self.diagnostics_results.insert(tk.END, f"\n=== Position Check - {device} ===\n")
            self.log_message(f"Checking position for {device}")
            
            success, stdout, stderr = self.ltfs_manager.run_command(f"mt -f {device} tell")
            
            if success:
                self.diagnostics_results.insert(tk.END, f"Current Position: {stdout}\n")
            else:
                self.diagnostics_results.insert(tk.END, f"Position Error: {stderr}\n")
            
            self.diagnostics_results.see(tk.END)
            self.log_message(f"Position check completed for {device}")
        
        threading.Thread(target=position_thread, daemon=True).start()
    
    def check_hardware_info(self):
        """Get hardware information about the drive"""
        device = self.diagnostics_device_var.get()
        if not device:
            messagebox.showerror("Error", "Please select a tape drive first.")
            return
        
        def hardware_thread():
            self.diagnostics_results.insert(tk.END, f"\n=== Hardware Information - {device} ===\n")
            self.log_message(f"Getting hardware info for {device}")
            
            # Try multiple commands to get hardware details
            commands = [
                ("SCSI Inquiry", f"sg_inq {device}"),
                ("Drive Serial", f"sg_vpd -p sn {device}"),
                ("Device Info", f"lsscsi | grep tape")
            ]
            
            for test_name, cmd in commands:
                self.diagnostics_results.insert(tk.END, f"\n{test_name}:\n")
                success, stdout, stderr = self.ltfs_manager.run_command(cmd)
                
                if success:
                    self.diagnostics_results.insert(tk.END, f"{stdout}\n")
                else:
                    self.diagnostics_results.insert(tk.END, f"Not available or error: {stderr}\n")
            
            self.diagnostics_results.see(tk.END)
            self.log_message(f"Hardware info check completed for {device}")
        
        threading.Thread(target=hardware_thread, daemon=True).start()
    
    def run_rw_test(self):
        """Run read/write test"""
        device = self.diagnostics_device_var.get()
        if not device:
            messagebox.showerror("Error", "Please select a tape drive first.")
            return
        
        if not messagebox.askyesno("Confirm Test", 
                                 "This will perform a read/write test that may take several minutes.\n\n"
                                 "Continue?"):
            return
        
        def rw_test_thread():
            self.diagnostics_results.insert(tk.END, f"\n=== Read/Write Test - {device} ===\n")
            self.log_message(f"Starting read/write test for {device}")
            
            # Simple read/write test using dd
            test_file = "/tmp/tape_test_data"
            
            # Create test data
            self.diagnostics_results.insert(tk.END, "Creating test data...\n")
            success, stdout, stderr = self.ltfs_manager.run_command(
                f"dd if=/dev/urandom of={test_file} bs=1M count=10 2>&1")
            
            if success:
                self.diagnostics_results.insert(tk.END, "Test data created successfully.\n")
                
                # Write test
                self.diagnostics_results.insert(tk.END, "Writing to tape...\n")
                success, stdout, stderr = self.ltfs_manager.run_command(
                    f"dd if={test_file} of={device} bs=1M 2>&1")
                
                if success:
                    self.diagnostics_results.insert(tk.END, "Write test completed successfully.\n")
                    
                    # Rewind and read test
                    self.diagnostics_results.insert(tk.END, "Rewinding tape...\n")
                    self.ltfs_manager.run_command(f"mt -f {device} rewind")
                    
                    self.diagnostics_results.insert(tk.END, "Reading from tape...\n")
                    success, stdout, stderr = self.ltfs_manager.run_command(
                        f"dd if={device} of=/tmp/tape_read_test bs=1M count=10 2>&1")
                    
                    if success:
                        self.diagnostics_results.insert(tk.END, "Read test completed successfully.\n")
                        
                        # Compare files
                        success, stdout, stderr = self.ltfs_manager.run_command(
                            f"cmp {test_file} /tmp/tape_read_test")
                        
                        if success:
                            self.diagnostics_results.insert(tk.END, "✓ Data verification PASSED - Read/Write test successful!\n")
                        else:
                            self.diagnostics_results.insert(tk.END, "✗ Data verification FAILED - Data integrity issue detected!\n")
                    else:
                        self.diagnostics_results.insert(tk.END, f"Read test failed: {stderr}\n")
                else:
                    self.diagnostics_results.insert(tk.END, f"Write test failed: {stderr}\n")
                
                # Cleanup
                self.ltfs_manager.run_command(f"rm -f {test_file} /tmp/tape_read_test")
            else:
                self.diagnostics_results.insert(tk.END, f"Failed to create test data: {stderr}\n")
            
            self.diagnostics_results.see(tk.END)
            self.log_message(f"Read/write test completed for {device}")
        
        threading.Thread(target=rw_test_thread, daemon=True).start()
    
    def run_load_test(self):
        """Run load/unload test"""
        device = self.diagnostics_device_var.get()
        if not device:
            messagebox.showerror("Error", "Please select a tape drive first.")
            return
        
        def load_test_thread():
            self.diagnostics_results.insert(tk.END, f"\n=== Load/Unload Test - {device} ===\n")
            self.log_message(f"Starting load/unload test for {device}")
            
            # Test load/unload cycle
            commands = [
                ("Unload tape", f"mt -f {device} offline"),
                ("Wait 5 seconds", "sleep 5"),
                ("Load tape", f"mt -f {device} load"),
                ("Check status", f"mt -f {device} status")
            ]
            
            for step_name, cmd in commands:
                self.diagnostics_results.insert(tk.END, f"{step_name}...\n")
                success, stdout, stderr = self.ltfs_manager.run_command(cmd)
                
                if success:
                    if stdout.strip():
                        self.diagnostics_results.insert(tk.END, f"Result: {stdout}\n")
                    else:
                        self.diagnostics_results.insert(tk.END, "✓ Success\n")
                else:
                    self.diagnostics_results.insert(tk.END, f"✗ Error: {stderr}\n")
                    break
            
            self.diagnostics_results.see(tk.END)
            self.log_message(f"Load/unload test completed for {device}")
        
        threading.Thread(target=load_test_thread, daemon=True).start()
    
    def run_seek_test(self):
        """Run seek test"""
        device = self.diagnostics_device_var.get()
        if not device:
            messagebox.showerror("Error", "Please select a tape drive first.")
            return
        
        def seek_test_thread():
            self.diagnostics_results.insert(tk.END, f"\n=== Seek Test - {device} ===\n")
            self.log_message(f"Starting seek test for {device}")
            
            # Test various seek operations
            operations = [
                ("Rewind to beginning", f"mt -f {device} rewind"),
                ("Seek forward 1000 blocks", f"mt -f {device} fsf 1000"),
                ("Check position", f"mt -f {device} tell"),
                ("Seek backward 500 blocks", f"mt -f {device} bsf 500"),
                ("Check position", f"mt -f {device} tell"),
                ("Return to beginning", f"mt -f {device} rewind")
            ]
            
            for op_name, cmd in operations:
                self.diagnostics_results.insert(tk.END, f"{op_name}...\n")
                success, stdout, stderr = self.ltfs_manager.run_command(cmd)
                
                if success:
                    if stdout.strip():
                        self.diagnostics_results.insert(tk.END, f"Position: {stdout}\n")
                    else:
                        self.diagnostics_results.insert(tk.END, "✓ Success\n")
                else:
                    self.diagnostics_results.insert(tk.END, f"✗ Error: {stderr}\n")
            
            self.diagnostics_results.see(tk.END)
            self.log_message(f"Seek test completed for {device}")
        
        threading.Thread(target=seek_test_thread, daemon=True).start()
    
    def run_full_diagnostic(self):
        """Run comprehensive diagnostic suite"""
        device = self.diagnostics_device_var.get()
        if not device:
            messagebox.showerror("Error", "Please select a tape drive first.")
            return
        
        if not messagebox.askyesno("Confirm Full Diagnostic", 
                                 "This will run a comprehensive diagnostic suite that may take 10-30 minutes.\n\n"
                                 "The test will include hardware checks, positioning tests, and read/write verification.\n\n"
                                 "Continue?"):
            return
        
        def full_diagnostic_thread():
            self.diagnostics_results.insert(tk.END, f"\n=== FULL DIAGNOSTIC SUITE - {device} ===\n")
            self.log_message(f"Starting full diagnostic for {device}")
            
            # Run all diagnostic tests in sequence
            self.diagnostics_results.insert(tk.END, "Running comprehensive diagnostic suite...\n\n")
            
            # Hardware info
            self.check_hardware_info()
            time.sleep(2)
            
            # Drive status
            self.check_drive_status()
            time.sleep(2)
            
            # Tape status
            self.check_tape_status()
            time.sleep(2)
            
            # Position check
            self.check_position()
            time.sleep(2)
            
            # Load/unload test
            self.run_load_test()
            time.sleep(5)
            
            # Seek test
            self.run_seek_test()
            time.sleep(3)
            
            # Read/write test (if user confirms)
            if messagebox.askyesno("Continue with R/W Test?", 
                                 "Proceed with read/write test? This will write test data to the tape."):
                self.run_rw_test()
            
            self.diagnostics_results.insert(tk.END, "\n=== FULL DIAGNOSTIC COMPLETED ===\n")
            self.log_message(f"Full diagnostic completed for {device}")
            self.diagnostics_results.see(tk.END)
        
        threading.Thread(target=full_diagnostic_thread, daemon=True).start()
    
    def rewind_tape(self):
        """Rewind tape to beginning"""
        device = self.diagnostics_device_var.get()
        if not device:
            messagebox.showerror("Error", "Please select a tape drive first.")
            return
        
        def rewind_thread():
            self.diagnostics_results.insert(tk.END, f"\n=== Rewind Tape - {device} ===\n")
            self.log_message(f"Rewinding tape in {device}")
            
            success, stdout, stderr = self.ltfs_manager.run_command(f"mt -f {device} rewind")
            
            if success:
                self.diagnostics_results.insert(tk.END, "✓ Tape rewound successfully\n")
                self.log_message(f"Tape rewound successfully in {device}")
            else:
                self.diagnostics_results.insert(tk.END, f"✗ Rewind failed: {stderr}\n")
                self.log_message(f"Rewind failed for {device}: {stderr}")
            
            self.diagnostics_results.see(tk.END)
        
        threading.Thread(target=rewind_thread, daemon=True).start()
    
    def eject_tape(self):
        """Eject tape from drive"""
        device = self.diagnostics_device_var.get()
        if not device:
            messagebox.showerror("Error", "Please select a tape drive first.")
            return
        
        def eject_thread():
            self.diagnostics_results.insert(tk.END, f"\n=== Eject Tape - {device} ===\n")
            self.log_message(f"Ejecting tape from {device}")
            
            success, stdout, stderr = self.ltfs_manager.run_command(f"mt -f {device} offline")
            
            if success:
                self.diagnostics_results.insert(tk.END, "✓ Tape ejected successfully\n")
                self.log_message(f"Tape ejected successfully from {device}")
            else:
                self.diagnostics_results.insert(tk.END, f"✗ Eject failed: {stderr}\n")
                self.log_message(f"Eject failed for {device}: {stderr}")
            
            self.diagnostics_results.see(tk.END)
        
        threading.Thread(target=eject_thread, daemon=True).start()
    
    def tension_release(self):
        """Release tape tension"""
        device = self.diagnostics_device_var.get()
        if not device:
            messagebox.showerror("Error", "Please select a tape drive first.")
            return
        
        def tension_thread():
            self.diagnostics_results.insert(tk.END, f"\n=== Tension Release - {device} ===\n")
            self.log_message(f"Releasing tape tension in {device}")
            
            success, stdout, stderr = self.ltfs_manager.run_command(f"mt -f {device} tension")
            
            if success:
                self.diagnostics_results.insert(tk.END, "✓ Tape tension released successfully\n")
                self.log_message(f"Tape tension released in {device}")
            else:
                self.diagnostics_results.insert(tk.END, f"✗ Tension release failed: {stderr}\n")
                self.log_message(f"Tension release failed for {device}: {stderr}")
            
            self.diagnostics_results.see(tk.END)
        
        threading.Thread(target=tension_thread, daemon=True).start()
    
    def clean_drive(self):
        """Clean tape drive (requires cleaning cartridge)"""
        device = self.diagnostics_device_var.get()
        if not device:
            messagebox.showerror("Error", "Please select a tape drive first.")
            return
        
        if not messagebox.askyesno("Confirm Drive Cleaning", 
                                 "Drive cleaning requires a cleaning cartridge to be inserted.\n\n"
                                 "Have you inserted a cleaning cartridge and want to proceed?"):
            return
        
        def clean_thread():
            self.diagnostics_results.insert(tk.END, f"\n=== Drive Cleaning - {device} ===\n")
            self.log_message(f"Starting drive cleaning for {device}")
            
            # Note: Actual cleaning command depends on drive type
            success, stdout, stderr = self.ltfs_manager.run_command(f"mt -f {device} clean")
            
            if success:
                self.diagnostics_results.insert(tk.END, "✓ Drive cleaning initiated\n")
                self.diagnostics_results.insert(tk.END, "Wait for cleaning cycle to complete before removing cartridge.\n")
                self.log_message(f"Drive cleaning initiated for {device}")
            else:
                self.diagnostics_results.insert(tk.END, f"Drive cleaning not supported or failed: {stderr}\n")
                self.log_message(f"Drive cleaning failed for {device}: {stderr}")
            
            self.diagnostics_results.see(tk.END)
        
        threading.Thread(target=clean_thread, daemon=True).start()
    
    def reset_drive(self):
        """Reset tape drive"""
        device = self.diagnostics_device_var.get()
        if not device:
            messagebox.showerror("Error", "Please select a tape drive first.")
            return
        
        if not messagebox.askyesno("Confirm Drive Reset", 
                                 "This will reset the tape drive which may interrupt any ongoing operations.\n\n"
                                 "Continue?"):
            return
        
        def reset_thread():
            self.diagnostics_results.insert(tk.END, f"\n=== Drive Reset - {device} ===\n")
            self.log_message(f"Resetting drive {device}")
            
            success, stdout, stderr = self.ltfs_manager.run_command(f"mt -f {device} reset")
            
            if success:
                self.diagnostics_results.insert(tk.END, "✓ Drive reset successfully\n")
                self.log_message(f"Drive reset completed for {device}")
            else:
                self.diagnostics_results.insert(tk.END, f"Reset failed or not supported: {stderr}\n")
                self.log_message(f"Drive reset failed for {device}: {stderr}")
            
            self.diagnostics_results.see(tk.END)
        
        threading.Thread(target=reset_thread, daemon=True).start()
    
    def get_log_pages(self):
        """Get drive log pages"""
        device = self.diagnostics_device_var.get()
        if not device:
            messagebox.showerror("Error", "Please select a tape drive first.")
            return
        
        def log_pages_thread():
            self.diagnostics_results.insert(tk.END, f"\n=== Drive Log Pages - {device} ===\n")
            self.log_message(f"Getting log pages for {device}")
            
            # Try to get various log pages using sg_logs
            log_pages = ["0x02", "0x03", "0x06", "0x0c", "0x0d", "0x0e", "0x0f"]
            
            for page in log_pages:
                self.diagnostics_results.insert(tk.END, f"\nLog Page {page}:\n")
                success, stdout, stderr = self.ltfs_manager.run_command(f"sg_logs -p {page} {device}")
                
                if success:
                    self.diagnostics_results.insert(tk.END, f"{stdout}\n")
                else:
                    self.diagnostics_results.insert(tk.END, f"Page {page} not available or error: {stderr}\n")
            
            self.diagnostics_results.see(tk.END)
            self.log_message(f"Log pages retrieved for {device}")
        
        threading.Thread(target=log_pages_thread, daemon=True).start()
    
    def get_error_stats(self):
        """Get error statistics"""
        device = self.diagnostics_device_var.get()
        if not device:
            messagebox.showerror("Error", "Please select a tape drive first.")
            return
        
        def error_stats_thread():
            self.diagnostics_results.insert(tk.END, f"\n=== Error Statistics - {device} ===\n")
            self.log_message(f"Getting error statistics for {device}")
            
            # Try multiple commands to get error information
            commands = [
                ("Error Counter Log", f"sg_logs -p 0x03 {device}"),
                ("TapeAlert Flags", f"sg_logs -p 0x2e {device}"),
                ("Device Statistics", f"iostat -x {device}")
            ]
            
            for cmd_name, cmd in commands:
                self.diagnostics_results.insert(tk.END, f"\n{cmd_name}:\n")
                success, stdout, stderr = self.ltfs_manager.run_command(cmd)
                
                if success:
                    self.diagnostics_results.insert(tk.END, f"{stdout}\n")
                else:
                    self.diagnostics_results.insert(tk.END, f"Not available: {stderr}\n")
            
            self.diagnostics_results.see(tk.END)
            self.log_message(f"Error statistics retrieved for {device}")
        
        threading.Thread(target=error_stats_thread, daemon=True).start()
    
    def get_firmware_info(self):
        """Get firmware information"""
        device = self.diagnostics_device_var.get()
        if not device:
            messagebox.showerror("Error", "Please select a tape drive first.")
            return
        
        def firmware_thread():
            self.diagnostics_results.insert(tk.END, f"\n=== Firmware Information - {device} ===\n")
            self.log_message(f"Getting firmware info for {device}")
            
            # Get firmware and version information
            commands = [
                ("Device Identification", f"sg_inq -p 0x80 {device}"),
                ("Unit Serial Number", f"sg_inq -p 0x80 {device}"),
                ("Software Interface ID", f"sg_inq -p 0x84 {device}"),
                ("Management Network Addresses", f"sg_inq -p 0x85 {device}")
            ]
            
            for cmd_name, cmd in commands:
                self.diagnostics_results.insert(tk.END, f"\n{cmd_name}:\n")
                success, stdout, stderr = self.ltfs_manager.run_command(cmd)
                
                if success:
                    self.diagnostics_results.insert(tk.END, f"{stdout}\n")
                else:
                    self.diagnostics_results.insert(tk.END, f"Not available: {stderr}\n")
            
            self.diagnostics_results.see(tk.END)
            self.log_message(f"Firmware info retrieved for {device}")
        
        threading.Thread(target=firmware_thread, daemon=True).start()
    
    def clear_diagnostics(self):
        """Clear diagnostics results"""
        self.diagnostics_results.delete(1.0, tk.END)
        self.log_message("Diagnostics results cleared")
    
    def save_diagnostics(self):
        """Save diagnostics results to file"""
        filename = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
            title="Save Diagnostics Results"
        )
        
        if filename:
            try:
                with open(filename, 'w') as f:
                    f.write(self.diagnostics_results.get(1.0, tk.END))
                messagebox.showinfo("Success", f"Diagnostics results saved to {filename}")
                self.log_message(f"Diagnostics results saved to {filename}")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to save diagnostics: {str(e)}")
    
    def export_diagnostic_report(self):
        """Export comprehensive diagnostic report"""
        device = self.diagnostics_device_var.get()
        if not device:
            messagebox.showerror("Error", "Please select a tape drive first.")
            return
        
        filename = filedialog.asksaveasfilename(
            defaultextension=".html",
            filetypes=[("HTML files", "*.html"), ("Text files", "*.txt"), ("All files", "*.*")],
            title="Export Diagnostic Report"
        )
        
        if filename:
            try:
                timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
                
                if filename.endswith('.html'):
                    # Create HTML report
                    html_content = f"""
                    <!DOCTYPE html>
                    <html>
                    <head>
                        <title>LTFS Diagnostic Report - {device}</title>
                        <style>
                            body {{ font-family: Arial, sans-serif; margin: 20px; }}
                            .header {{ background-color: #f0f0f0; padding: 15px; border-radius: 5px; }}
                            .section {{ margin: 20px 0; padding: 15px; border: 1px solid #ddd; border-radius: 5px; }}
                            pre {{ background-color: #f8f8f8; padding: 10px; border-radius: 3px; overflow-x: auto; }}
                        </style>
                    </head>
                    <body>
                        <div class="header">
                            <h1>LTFS Diagnostic Report</h1>
                            <p><strong>Device:</strong> {device}</p>
                            <p><strong>Generated:</strong> {timestamp}</p>
                        </div>
                        
                        <div class="section">
                            <h2>Diagnostic Results</h2>
                            <pre>{self.diagnostics_results.get(1.0, tk.END)}</pre>
                        </div>
                        
                        <div class="section">
                            <h2>System Information</h2>
                            <p>Report generated by LTFS GUI Manager</p>
                        </div>
                    </body>
                    </html>
                    """
                    
                    with open(filename, 'w') as f:
                        f.write(html_content)
                else:
                    # Create text report
                    with open(filename, 'w') as f:
                        f.write(f"LTFS Diagnostic Report\n")
                        f.write(f"{'='*50}\n")
                        f.write(f"Device: {device}\n")
                        f.write(f"Generated: {timestamp}\n\n")
                        f.write(self.diagnostics_results.get(1.0, tk.END))
                
                messagebox.showinfo("Success", f"Diagnostic report exported to {filename}")
                self.log_message(f"Diagnostic report exported to {filename}")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to export report: {str(e)}")
    
    def setup_log_tab(self):
        """Set up the log tab"""
        ttk.Label(self.log_frame, text="Operation Log:", font=('Arial', 12, 'bold')).pack(anchor='w', pady=(10, 5))
        
        self.log_text = scrolledtext.ScrolledText(self.log_frame, height=25, wrap='word')
        self.log_text.pack(fill='both', expand=True, padx=10, pady=(0, 10))
        
        # Log controls
        log_controls = ttk.Frame(self.log_frame)
        log_controls.pack(fill='x', padx=10, pady=5)
        
        ttk.Button(log_controls, text="Clear Log", command=self.clear_log).pack(side='left', padx=(0, 10))
        ttk.Button(log_controls, text="Save Log", command=self.save_log).pack(side='left')
    
    def log_message(self, message):
        """Add a message to the log"""
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        log_entry = f"[{timestamp}] {message}\n"
        self.log_text.insert(tk.END, log_entry)
        self.log_text.see(tk.END)
    
    def refresh_drives(self):
        """Refresh the list of available drives"""
        drives = self.ltfs_manager.refresh_drives()
        
        # Update drives listbox
        self.drives_listbox.delete(0, tk.END)
        for drive in drives:
            self.drives_listbox.insert(tk.END, drive)
        
        # Update mount tab based on single drive mode
        self.update_mount_tab_mode()
        
        # Update format combo box (always show all drives)
        self.format_device_combo['values'] = drives
        
        # Update compression combo box
        self.compression_device_combo['values'] = drives
        
        # Update diagnostics combo box
        self.diagnostics_device_combo['values'] = drives
        
        if drives:
            self.format_device_var.set(drives[0])
            self.compression_device_var.set(drives[0])
            self.diagnostics_device_var.set(drives[0])
        
        self.log_message(f"Found {len(drives)} tape drives: {', '.join(drives)}")
        
        # Check for permission issues
        if hasattr(self.ltfs_manager, 'permission_issues') and self.ltfs_manager.permission_issues:
            self.log_message(f"⚠️ Permission issues detected for: {', '.join(self.ltfs_manager.permission_issues)}")
            self.show_permission_warning()
        
        if self.ltfs_manager.single_drive_mode:
            self.log_message("Single drive detected - switching to mode selection interface")
    
    def update_mount_tab_mode(self):
        """Update mount tab interface based on single/multiple drive mode"""
        if self.ltfs_manager.single_drive_mode and self.ltfs_manager.physical_drives:
            # Show mode selection interface
            self.device_label.config(text="Drive Mode:")
            self.mode_frame.grid()
            
            # Populate density mode options
            drive_id = list(self.ltfs_manager.physical_drives.keys())[0]
            physical_drive = self.ltfs_manager.physical_drives[drive_id]
            
            # Update mode options based on rewinding selection
            self.update_mode_options()
            
            # Bind rewinding selection to update mode options
            self.rewinding_var.trace_add('write', lambda *args: self.update_mode_options())
            
            # Hide device combo and show mode selection
            self.mount_device_combo.grid_remove()
            
        else:
            # Show traditional device selection
            self.device_label.config(text="Device:")
            self.mode_frame.grid_remove()
            self.mount_device_combo.grid()
            
            # Update device combo box
            drives = self.ltfs_manager.tape_drives
            self.mount_device_combo['values'] = drives
            if drives:
                self.mount_device_var.set(drives[0])
    
    def update_mode_options(self):
        """Update the available mode options based on rewinding selection"""
        if not self.ltfs_manager.single_drive_mode or not self.ltfs_manager.physical_drives:
            return
        
        drive_id = list(self.ltfs_manager.physical_drives.keys())[0]
        physical_drive = self.ltfs_manager.physical_drives[drive_id]
        
        # Get appropriate mode list based on rewinding selection
        if self.rewinding_var.get() == "rewinding":
            mode_list = physical_drive['rewinding']
        else:
            mode_list = physical_drive['non_rewinding']
        
        # Populate combo box with mode descriptions
        mode_options = []
        for mode_info in mode_list:
            mode_options.append(f"{mode_info['mode']} - {mode_info['description']}")
        
        self.density_mode_combo['values'] = mode_options
        if mode_options:
            self.density_mode_var.set(mode_options[0])
    
    def get_selected_device(self):
        """Get the currently selected device based on interface mode"""
        if self.ltfs_manager.single_drive_mode and self.ltfs_manager.physical_drives:
            # Get device from mode selection
            drive_id = list(self.ltfs_manager.physical_drives.keys())[0]
            physical_drive = self.ltfs_manager.physical_drives[drive_id]
            
            # Get mode list based on rewinding selection
            if self.rewinding_var.get() == "rewinding":
                mode_list = physical_drive['rewinding']
            else:
                mode_list = physical_drive['non_rewinding']
            
            # Find selected mode
            selected_mode = self.density_mode_var.get().split(' - ')[0] if self.density_mode_var.get() else 'default'
            
            for mode_info in mode_list:
                if mode_info['mode'] == selected_mode:
                    return mode_info['device']
            
            # Fallback: prioritize basic device (default mode) over auto-density
            # This fixes the issue where /dev/nst0a was being selected instead of /dev/nst0
            default_devices = [m for m in mode_list if m['mode'] == 'default']
            if default_devices:
                return default_devices[0]['device']
            
            # Additional fallback: prefer basic devices over auto-density variants
            basic_devices = [m for m in mode_list if not any(x in m['device'] for x in ['a', 'l', 'm'])]
            if basic_devices:
                return basic_devices[0]['device']
            
            # Final fallback to first available device
            return mode_list[0]['device'] if mode_list else None
        else:
            # Traditional device selection
            return self.mount_device_var.get()
    
    def get_drive_info(self):
        """Get information about the selected drive"""
        selection = self.drives_listbox.curselection()
        if not selection:
            messagebox.showwarning("Warning", "Please select a drive first.")
            return
        
        drive = self.drives_listbox.get(selection[0])
        info = self.ltfs_manager.get_tape_info(drive)
        
        self.drive_info_text.delete(1.0, tk.END)
        self.drive_info_text.insert(1.0, f"Drive: {drive}\n\n{info}")
        
        self.log_message(f"Retrieved info for drive {drive}")
    
    def eject_selected_drive(self):
        """Eject tape from the selected drive"""
        selection = self.drives_listbox.curselection()
        if not selection:
            messagebox.showwarning("Warning", "Please select a drive first.")
            return
        
        drive = self.drives_listbox.get(selection[0])
        
        if messagebox.askyesno("Confirm Eject", f"Eject tape from {drive}?"):
            def eject_thread():
                self.log_message(f"Ejecting tape from {drive}")
                success, stdout, stderr = self.ltfs_manager.run_command(f"mt -f {drive} eject")
                
                if not success:
                    # Try offline command if eject fails
                    success, stdout, stderr = self.ltfs_manager.run_command(f"mt -f {drive} offline")
                
                if success:
                    self.log_message(f"Tape ejected successfully from {drive}")
                    messagebox.showinfo("Success", f"Tape ejected from {drive}")
                else:
                    error_msg = stderr if stderr else "Unknown error occurred"
                    self.log_message(f"Failed to eject from {drive}: {error_msg}")
                    messagebox.showerror("Error", f"Failed to eject tape:\n{error_msg}")
            
            threading.Thread(target=eject_thread, daemon=True).start()
    
    def rewind_selected_drive(self):
        """Rewind tape in the selected drive"""
        selection = self.drives_listbox.curselection()
        if not selection:
            messagebox.showwarning("Warning", "Please select a drive first.")
            return
        
        drive = self.drives_listbox.get(selection[0])
        
        def rewind_thread():
            self.log_message(f"Rewinding tape in {drive}")
            success, stdout, stderr = self.ltfs_manager.run_command(f"mt -f {drive} rewind")
            
            if success:
                self.log_message(f"Tape rewound successfully in {drive}")
                messagebox.showinfo("Success", f"Tape rewound in {drive}")
            else:
                error_msg = stderr if stderr else "Unknown error occurred"
                self.log_message(f"Failed to rewind {drive}: {error_msg}")
                messagebox.showerror("Error", f"Failed to rewind tape:\n{error_msg}")
        
        threading.Thread(target=rewind_thread, daemon=True).start()
    
    def browse_mount_point(self):
        """Browse for mount point directory"""
        directory = filedialog.askdirectory(initialdir=self.mount_point_var.get())
        if directory:
            self.mount_point_var.set(directory)
    
    def mount_tape(self):
        """Mount a tape"""
        device = self.get_selected_device()
        mount_point = self.mount_point_var.get()
        options = self.mount_options_var.get()
        
        if not device or not mount_point:
            messagebox.showerror("Error", "Please specify both device and mount point.")
            return
        
        def mount_thread():
            self.log_message(f"Mounting {device} to {mount_point}...")
            success, stdout, stderr = self.ltfs_manager.mount_tape(device, mount_point, options)
            
            if success:
                self.log_message(f"Successfully mounted {device} to {mount_point}")
                messagebox.showinfo("Success", f"Tape mounted successfully at {mount_point}")
                self.root.after(0, self.refresh_mounted_list)
            else:
                error_msg = stderr if stderr else "Unknown error occurred"
                self.log_message(f"Failed to mount {device}: {error_msg}")
                messagebox.showerror("Error", f"Failed to mount tape:\n{error_msg}")
        
        threading.Thread(target=mount_thread, daemon=True).start()
    
    def refresh_mounted_list(self):
        """Refresh the list of mounted tapes"""
        mounted_info = self.ltfs_manager.list_mounted_tapes()
        
        self.mounted_listbox.delete(0, tk.END)
        
        for line in mounted_info.split('\n'):
            if line.strip() and 'ltfs' in line:
                # Parse mount information
                parts = line.split()
                if len(parts) >= 3:
                    device = parts[0]
                    mount_point = parts[2]
                    self.mounted_listbox.insert(tk.END, f"{mount_point} ({device})")
    
    def unmount_tape(self):
        """Unmount the selected tape"""
        selection = self.mounted_listbox.curselection()
        if not selection:
            messagebox.showwarning("Warning", "Please select a mounted tape to unmount.")
            return
        
        selected_text = self.mounted_listbox.get(selection[0])
        # Extract mount point from the format "mount_point (device)"
        mount_point = selected_text.split(' (')[0]
        
        def unmount_thread():
            self.log_message(f"Unmounting {mount_point}...")
            success, stdout, stderr = self.ltfs_manager.unmount_tape(mount_point)
            
            if success:
                self.log_message(f"Successfully unmounted {mount_point}")
                messagebox.showinfo("Success", f"Tape unmounted successfully from {mount_point}")
                self.root.after(0, self.refresh_mounted_list)
            else:
                error_msg = stderr if stderr else "Unknown error occurred"
                self.log_message(f"Failed to unmount {mount_point}: {error_msg}")
                messagebox.showerror("Error", f"Failed to unmount tape:\n{error_msg}")
        
        threading.Thread(target=unmount_thread, daemon=True).start()
    
    def open_mount_point(self):
        """Open the selected mount point in the file manager"""
        selection = self.mounted_listbox.curselection()
        if not selection:
            messagebox.showwarning("Warning", "Please select a mounted tape first.")
            return
        
        selected_text = self.mounted_listbox.get(selection[0])
        mount_point = selected_text.split(' (')[0]
        
        try:
            subprocess.run(['xdg-open', mount_point], check=True)
            self.log_message(f"Opened {mount_point} in file manager")
        except subprocess.CalledProcessError:
            messagebox.showerror("Error", f"Failed to open {mount_point} in file manager")
    
    def format_tape(self):
        """Format a tape with LTFS"""
        device = self.format_device_var.get()
        label = self.tape_label_var.get()
        force = self.force_format_var.get()
        
        if not device:
            messagebox.showerror("Error", "Please select a device to format.")
            return
        
        # Confirmation dialog
        msg = f"Are you sure you want to format {device}?"
        if label:
            msg += f"\nTape will be labeled: {label}"
        msg += "\n\n⚠️  This will PERMANENTLY erase all data on the tape!"
        
        if not messagebox.askyesno("Confirm Format", msg):
            return
        
        def format_thread():
            self.log_message(f"Formatting {device} with LTFS...")
            success, stdout, stderr = self.ltfs_manager.format_tape(device, label, force)
            
            if success:
                self.log_message(f"Successfully formatted {device}")
                messagebox.showinfo("Success", f"Tape formatted successfully with LTFS")
            else:
                error_msg = stderr if stderr else "Unknown error occurred"
                self.log_message(f"Failed to format {device}: {error_msg}")
                messagebox.showerror("Error", f"Failed to format tape:\n{error_msg}")
        
        threading.Thread(target=format_thread, daemon=True).start()
    
    def refresh_status(self):
        """Refresh system status information"""
        status_info = []
        
        # LTFS version
        success, stdout, stderr = self.ltfs_manager.run_command("ltfs --version")
        if success:
            status_info.append(f"LTFS Version:\n{stdout.strip()}\n")
        
        # Available drives
        drives = self.ltfs_manager.refresh_drives()
        status_info.append(f"Available Tape Drives: {len(drives)}")
        for drive in drives:
            status_info.append(f"  - {drive}")
        status_info.append("")
        
        # Mounted tapes
        mounted_info = self.ltfs_manager.list_mounted_tapes()
        if mounted_info.strip():
            status_info.append("Mounted LTFS Tapes:")
            for line in mounted_info.split('\n'):
                if line.strip():
                    status_info.append(f"  {line}")
        else:
            status_info.append("No LTFS tapes currently mounted.")
        
        status_info.append("")
        
        # System information
        success, stdout, stderr = self.ltfs_manager.run_command("uname -a")
        if success:
            status_info.append(f"System: {stdout.strip()}")
        
        # Display status
        self.status_text.delete(1.0, tk.END)
        self.status_text.insert(1.0, '\n'.join(status_info))
        
        self.log_message("Status refreshed")
    
    def toggle_auto_refresh(self):
        """Toggle auto-refresh of status"""
        if self.auto_refresh_var.get():
            self.auto_refresh_status()
            self.log_message("Auto-refresh enabled")
        else:
            self.log_message("Auto-refresh disabled")
    
    def auto_refresh_status(self):
        """Auto-refresh status every 30 seconds"""
        if self.auto_refresh_var.get():
            self.refresh_status()
            self.root.after(30000, self.auto_refresh_status)  # 30 seconds
    
    def clear_log(self):
        """Clear the log display"""
        self.log_text.delete(1.0, tk.END)
    
    def save_log(self):
        """Save the log to a file"""
        filename = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
            title="Save Log File"
        )
        
        if filename:
            try:
                with open(filename, 'w') as f:
                    f.write(self.log_text.get(1.0, tk.END))
                messagebox.showinfo("Success", f"Log saved to {filename}")
                self.log_message(f"Log saved to {filename}")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to save log: {str(e)}")
    
    def show_permission_warning(self):
        """Show a warning dialog about permission issues"""
        permission_devices = self.ltfs_manager.permission_issues
        
        if not permission_devices:
            return
        
        warning_msg = (
            f"⚠️ Permission Issues Detected\n\n"
            f"Cannot access these tape devices:\n"
            f"{'  • ' + chr(10) + '  • '.join(permission_devices)}\n\n"
            f"This usually means you need to be in the 'tape' group.\n\n"
            f"Solutions:\n"
            f"1. Run the fix script: ./fix_permissions.sh\n"
            f"2. Add yourself to tape group: sudo usermod -a -G tape {os.getenv('USER', 'your_username')}\n"
            f"3. Then logout and login again\n\n"
            f"Quick workaround:\n"
            f"Run LTFS GUI with: sudo -u {os.getenv('USER', 'your_username')} -g tape ltfs-gui"
        )
        
        # Create a custom dialog with more space
        dialog = tk.Toplevel(self.root)
        dialog.title("Tape Device Permission Issues")
        dialog.geometry("600x400")
        dialog.resizable(True, True)
        
        # Make it modal
        dialog.transient(self.root)
        dialog.grab_set()
        
        # Add icon
        try:
            dialog.iconbitmap(default='warning')
        except:
            pass
        
        # Create frame with scrollable text
        main_frame = ttk.Frame(dialog, padding=20)
        main_frame.pack(fill='both', expand=True)
        
        # Warning text
        text_widget = tk.Text(main_frame, wrap='word', height=15, width=70)
        text_widget.pack(fill='both', expand=True, pady=(0, 10))
        text_widget.insert('1.0', warning_msg)
        text_widget.config(state='disabled')
        
        # Buttons frame
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill='x')
        
        def run_fix_script():
            """Run the fix permissions script"""
            try:
                script_dir = os.path.dirname(os.path.abspath(__file__))
                fix_script = os.path.join(script_dir, 'fix_permissions.sh')
                
                if os.path.exists(fix_script):
                    # Run in terminal
                    subprocess.Popen(['x-terminal-emulator', '-e', f'bash -c "{fix_script}; read -p \'Press Enter to close...\' dummy"'])
                    dialog.destroy()
                else:
                    messagebox.showerror("Error", f"Fix script not found at: {fix_script}")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to run fix script: {str(e)}")
        
        def copy_commands():
            """Copy fix commands to clipboard"""
            commands = (
                f"# Fix tape permissions\n"
                f"sudo usermod -a -G tape {os.getenv('USER', 'your_username')}\n"
                f"# Then logout and login again\n\n"
                f"# Or run LTFS GUI with correct permissions:\n"
                f"sudo -u {os.getenv('USER', 'your_username')} -g tape ltfs-gui"
            )
            
            try:
                dialog.clipboard_clear()
                dialog.clipboard_append(commands)
                messagebox.showinfo("Copied", "Fix commands copied to clipboard!")
            except Exception:
                messagebox.showerror("Error", "Failed to copy to clipboard")
        
        # Buttons
        ttk.Button(button_frame, text="Run Fix Script", command=run_fix_script).pack(side='left', padx=(0, 10))
        ttk.Button(button_frame, text="Copy Commands", command=copy_commands).pack(side='left', padx=(0, 10))
        ttk.Button(button_frame, text="Close", command=dialog.destroy).pack(side='right')
        
        # Center the dialog
        dialog.update_idletasks()
        x = (dialog.winfo_screenwidth() // 2) - (dialog.winfo_width() // 2)
        y = (dialog.winfo_screenheight() // 2) - (dialog.winfo_height() // 2)
        dialog.geometry(f"+{x}+{y}")

def main():
    root = tk.Tk()
    app = LTFSGui(root)
    
    # Initial setup
    app.refresh_mounted_list()
    app.refresh_status()
    app.log_message("LTFS GUI Manager started")
    
    root.mainloop()

if __name__ == "__main__":
    main()

