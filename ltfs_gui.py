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
from tkinter import ttk, messagebox, filedialog, scrolledtext, simpledialog
import subprocess
import threading
import os
import re
import time
import json
import sys
from pathlib import Path

class LTFSManager:
    def is_tape_loaded(self, device):
        success, _, _ = self.run_command(f'mt -f {device} status')
        return success

    def get_tape_barcode(self, device):
        """Get tape barcode/volser using multiple detection methods"""
        barcode = None
        
        # Method 1: Try tapeinfo command
        success, stdout, _ = self.run_command(f'tapeinfo -f {device}')
        if success:
            for line in stdout.split('\n'):
                line = line.strip()
                if 'Volser' in line or 'Barcode' in line:
                    parts = line.split(':', 1)
                    if len(parts) > 1:
                        barcode = parts[1].strip().strip('"\'')
                        if barcode and barcode not in ['Unknown', 'N/A', '']:
                            return barcode
                # Also check for Volume1 label format
                elif 'Volume1' in line:
                    parts = line.split()
                    if len(parts) > 1:
                        potential_barcode = parts[1]
                        if len(potential_barcode) >= 4:
                            barcode = potential_barcode
        
        # Method 2: Try reading MAM barcode attribute directly
        if not barcode or barcode == 'Unknown':
            barcode = self.get_mam_barcode(device)
            if barcode and barcode != 'Unknown':
                return barcode
        
        # Method 3: Try sg_logs for tape alert information
        if not barcode or barcode == 'Unknown':
            success, stdout, _ = self.run_command(f'sg_logs -p 0x17 {device}')
            if success:
                # Parse for barcode information in TapeAlert logs
                for line in stdout.split('\n'):
                    if 'barcode' in line.lower() or 'volume' in line.lower():
                        # Extract potential barcode from log line
                        import re
                        match = re.search(r'([A-Z0-9]{6,8})', line)
                        if match:
                            barcode = match.group(1)
                            return barcode
        
        # Method 4: Try LTFS volume label if tape is already formatted
        if not barcode or barcode == 'Unknown':
            barcode = self.get_ltfs_volume_label(device)
            if barcode and barcode != 'Unknown':
                return barcode
        
        return barcode if barcode else 'Unknown'
    
    def get_mam_barcode(self, device):
        """Get barcode from MAM attribute 0x0806"""
        try:
            # Read MAM attribute 0x0806 (Barcode) using sg_raw
            success, stdout, stderr = self.run_command(
                f"sg_raw -r 32 {device} 8C 00 00 08 06 00 00 00 20 00"
            )
            
            if success and stdout.strip():
                # Parse the hex output to extract ASCII barcode
                hex_lines = stdout.strip().split('\n')
                ascii_chars = []
                
                for line in hex_lines:
                    # Extract hex bytes and convert to ASCII
                    hex_bytes = re.findall(r'[0-9a-fA-F]{2}', line)
                    for hex_byte in hex_bytes:
                        try:
                            byte_val = int(hex_byte, 16)
                            # Only include printable ASCII characters
                            if 32 <= byte_val <= 126:
                                ascii_chars.append(chr(byte_val))
                            elif byte_val == 0:  # Null terminator
                                break
                        except ValueError:
                            continue
                
                barcode = ''.join(ascii_chars).strip()
                if barcode and len(barcode) >= 4:
                    return barcode
        
        except Exception as e:
            print(f"Error reading MAM barcode: {e}")
        
        return None
    
    def get_ltfs_volume_label(self, device):
        """Get volume label from LTFS-formatted tape"""
        try:
            # Try to read the LTFS label using ltfs utilities
            success, stdout, stderr = self.run_command(f"ltfs -o devname={device} --capture-index")
            if success:
                # Parse for volume identifier
                for line in stdout.split('\n'):
                    if 'volume' in line.lower() and 'identifier' in line.lower():
                        parts = line.split(':')
                        if len(parts) > 1:
                            return parts[1].strip()
        except Exception:
            pass
        
        return None
    def __init__(self):
        self.mounted_tapes = {}
        self.tape_drives = []
        self.physical_drives = {}  # Maps physical drive to its modes and hardware info
        self.drive_hardware_info = {}  # Maps device paths to hardware details
        self.single_drive_mode = False
        self.refresh_drives()
    
    def run_command(self, command, capture_output=True, shell=True):
        """Execute a shell command and return the result"""
        # Auto-detect correct tape device for SCSI commands
        if any(cmd in command for cmd in ['sg_inq', 'sg_vpd', 'sg_logs', 'tapeinfo']):
            # Use SCSI generic device for these commands
            command = self._replace_with_sg_device(command)
        
        try:
            if capture_output:
                result = subprocess.run(command, shell=shell, capture_output=True, text=True)
                return result.returncode == 0, result.stdout, result.stderr
            else:
                result = subprocess.run(command, shell=shell)
                return result.returncode == 0, "", ""
        except Exception as e:
            return False, "", str(e)
    
    def _replace_with_sg_device(self, command):
        """Replace tape device paths with the correct SCSI generic device"""
        # Map of common tape devices to their likely sg equivalents
        device_map = {
            '/dev/st0': '/dev/sg7',
            '/dev/nst0': '/dev/sg7',
            '/dev/st1': '/dev/sg8',
            '/dev/nst1': '/dev/sg8'
        }
        
        # Replace devices in the command
        modified_command = command
        for tape_dev, sg_dev in device_map.items():
            if tape_dev in command:
                # Check if sg device exists before replacing
                if os.path.exists(sg_dev):
                    modified_command = modified_command.replace(tape_dev, sg_dev)
                    print(f"LTFS: Replaced {tape_dev} with {sg_dev} for SCSI command")
                else:
                    print(f"LTFS: Warning: SCSI device {sg_dev} not found, keeping {tape_dev}")
        
        return modified_command
    
    def refresh_drives(self):
        """Scan for available tape drives and detect hardware information"""
        self.tape_drives = []
        self.physical_drives = {}
        self.drive_hardware_info = {}
        permission_issues = []
        
        # First, discover all tape devices using lsscsi
        discovered_drives = self._discover_tape_drives()
        
        # Process discovered drives
        for drive_info in discovered_drives:
            device_path = drive_info['device_path']
            
            # Check if device exists and is accessible
            if Path(device_path).exists() and Path(device_path).is_char_device():
                # Test if device responds to basic commands
                if self._test_device_functionality(device_path):
                    self.tape_drives.append(device_path)
                    
                    # Store hardware info
                    self.drive_hardware_info[device_path] = drive_info
                    
                    # Check permissions
                    if not self._can_access_device(device_path):
                        permission_issues.append(device_path)
        
        # Fallback: scan /dev/st* devices if no drives discovered via lsscsi
        if not self.tape_drives:
            print("LTFS: No drives found via lsscsi, falling back to /dev/st* scan")
            fallback_drives = self._fallback_device_scan()
            self.tape_drives.extend(fallback_drives)
            
            # Check permissions for fallback drives
            for device in fallback_drives:
                if not self._can_access_device(device):
                    permission_issues.append(device)
        
        # Store permission issues for later reference
        self.permission_issues = list(set(permission_issues))  # Remove duplicates
        
        # Group drives by physical device and organize interface modes
        self._organize_physical_drives()
        
        # Determine if we should use single drive mode
        self.single_drive_mode = len(self.physical_drives) == 1
        
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
    
    def _discover_tape_drives(self):
        """Discover tape drives using lsscsi and gather hardware information"""
        discovered_drives = []
        
        try:
            # Use lsscsi to find tape devices
            success, stdout, stderr = self.run_command("lsscsi -g | grep tape")
            
            if success and stdout.strip():
                for line in stdout.strip().split('\n'):
                    drive_info = self._parse_lsscsi_line(line)
                    if drive_info:
                        # Get additional hardware details
                        drive_info.update(self._get_drive_hardware_details(drive_info['device_path']))
                        discovered_drives.append(drive_info)
            
            # If lsscsi failed or found nothing, try alternative methods
            if not discovered_drives:
                # Try using /sys/class/scsi_tape to find tape devices
                discovered_drives = self._discover_via_sys_class()
        
        except Exception as e:
            print(f"LTFS: Error discovering drives: {e}")
        
        return discovered_drives
    
    def _parse_lsscsi_line(self, line):
        """Parse a line from lsscsi output to extract drive information"""
        try:
            # Example lsscsi line:
            # [2:0:0:0]    tape    IBM      ULTRIUM-HH6      H7G1  /dev/st0   /dev/sg7
            parts = line.strip().split()
            
            if len(parts) >= 6 and 'tape' in parts:
                scsi_id = parts[0].strip('[]')
                device_type = parts[1]
                vendor = parts[2] if len(parts) > 2 else "Unknown"
                model = parts[3] if len(parts) > 3 else "Unknown"
                revision = parts[4] if len(parts) > 4 else "Unknown"
                device_path = parts[5] if len(parts) > 5 else None
                sg_device = parts[6] if len(parts) > 6 else None
                
                # Clean up vendor/model names
                vendor = vendor.strip()
                model = model.strip()
                
                # Determine LTO generation from model
                lto_gen = self._extract_lto_generation(model)
                
                return {
                    'scsi_id': scsi_id,
                    'device_type': device_type,
                    'vendor': vendor,
                    'model': model,
                    'revision': revision,
                    'device_path': device_path,
                    'sg_device': sg_device,
                    'lto_generation': lto_gen,
                    'display_name': f"{vendor} {model}"
                }
        except Exception as e:
            print(f"LTFS: Error parsing lsscsi line '{line}': {e}")
        
        return None
    
    def _extract_lto_generation(self, model):
        """Extract LTO generation from model string"""
        # Common patterns for LTO generation identification
        lto_patterns = {
            'LTO-9': 'LTO-9',
            'LTO-8': 'LTO-8', 
            'LTO-7': 'LTO-7',
            'LTO-6': 'LTO-6',
            'LTO-5': 'LTO-5',
            'LTO-4': 'LTO-4',
            'LTO-3': 'LTO-3',
            'ULTRIUM-HH9': 'LTO-9',
            'ULTRIUM-HH8': 'LTO-8',
            'ULTRIUM-HH7': 'LTO-7',
            'ULTRIUM-HH6': 'LTO-6',
            'ULTRIUM-HH5': 'LTO-5',
            'ULTRIUM-HH4': 'LTO-4',
            'ULTRIUM-HH3': 'LTO-3',
        }
        
        model_upper = model.upper()
        for pattern, generation in lto_patterns.items():
            if pattern in model_upper:
                return generation
        
        return "Unknown"
    
    def _get_drive_hardware_details(self, device_path):
        """Get additional hardware details for a drive"""
        details = {
            'serial_number': 'Unknown',
            'firmware_version': 'Unknown',
            'wwn': 'Unknown'
        }
        
        if not device_path:
            return details
        
        try:
            # Method 1: Try to get serial number using sg_inq with VPD page 0x80
            success, stdout, stderr = self.run_command(f"sg_inq -p 0x80 {device_path}")
            if success and stdout:
                serial = self._extract_serial_from_sg_inq(stdout)
                if serial:
                    details['serial_number'] = serial
            
            # Method 2: If no serial found, try VPD page 0x83 (Device Identification)
            if details['serial_number'] == 'Unknown':
                success, stdout, stderr = self.run_command(f"sg_inq -p 0x83 {device_path}")
                if success and stdout:
                    serial = self._extract_serial_from_device_id(stdout)
                    if serial:
                        details['serial_number'] = serial
            
            # Method 3: Try using sg_vpd for serial number
            if details['serial_number'] == 'Unknown':
                success, stdout, stderr = self.run_command(f"sg_vpd -p sn {device_path}")
                if success and stdout:
                    serial = self._extract_serial_from_sg_vpd(stdout)
                    if serial:
                        details['serial_number'] = serial
            
            # Method 4: Try tapeinfo command for serial number
            if details['serial_number'] == 'Unknown':
                success, stdout, stderr = self.run_command(f"tapeinfo -f {device_path}")
                if success and stdout:
                    serial = self._extract_serial_from_tapeinfo(stdout)
                    if serial:
                        details['serial_number'] = serial
            
            # Get firmware version and other details using standard inquiry
            success, stdout, stderr = self.run_command(f"sg_inq {device_path}")
            if success and stdout:
                fw_version = self._extract_firmware_version(stdout)
                if fw_version:
                    details['firmware_version'] = fw_version
        
        except Exception as e:
            print(f"LTFS: Error getting hardware details for {device_path}: {e}")
        
        return details
    
    def _extract_serial_from_sg_inq(self, sg_inq_output):
        """Extract serial number from sg_inq VPD page 0x80 output"""
        try:
            lines = sg_inq_output.split('\n')
            for i, line in enumerate(lines):
                line = line.strip()
                
                # Look for the Unit serial number line
                if 'Unit serial number' in line and ':' in line:
                    # Extract everything after the colon
                    parts = line.split(':', 1)
                    if len(parts) > 1:
                        serial = parts[1].strip()
                        # Remove quotes and extra whitespace
                        serial = serial.strip('"\'\'').strip()
                        
                        # Validate the serial number
                        if (serial and 
                            serial not in ['VPD INQUIRY page', 'Unit serial number page', 'page'] and
                            len(serial) >= 4 and 
                            len(serial) <= 32 and
                            re.match(r'^[A-Za-z0-9]+$', serial)):
                            return serial
                
                # Look for serial in the next few lines after "Unit serial number" header
                elif 'Unit serial number' in line and i + 1 < len(lines):
                    # Check the next line for the actual serial
                    next_line = lines[i + 1].strip()
                    if next_line and re.match(r'^[A-Za-z0-9]{4,32}$', next_line):
                        return next_line
                
                # Look for lines that contain only valid serial number characters
                elif (re.match(r'^[A-Z0-9]{6,20}$', line) and 
                      line not in ['VPD', 'INQUIRY', 'PAGE']):
                    return line
                
                # Look for hex data that might contain ASCII serial
                elif re.match(r'^[0-9a-fA-F\s]{20,}$', line):
                    serial = self._extract_ascii_from_hex(line)
                    if (serial and 
                        len(serial) >= 4 and 
                        serial not in ['VPD INQUIRY page', 'Unit serial number page']):
                        return serial
        except Exception:
            pass
        return None
    
    def _extract_serial_from_device_id(self, sg_inq_output):
        """Extract serial number from sg_inq VPD page 0x83 (Device Identification) output"""
        try:
            lines = sg_inq_output.split('\n')
            for i, line in enumerate(lines):
                line = line.strip()
                if 'vendor specific' in line.lower() or 'T10 vendor identification' in line:
                    # Look for serial in the next few lines
                    for j in range(i+1, min(i+5, len(lines))):
                        next_line = lines[j].strip()
                        # Look for patterns that might be serial numbers
                        if re.search(r'[A-Z0-9]{6,}', next_line):
                            potential_serial = re.search(r'[A-Z0-9]{6,}', next_line).group()
                            if len(potential_serial) >= 6 and len(potential_serial) <= 20:
                                return potential_serial
        except Exception:
            pass
        return None
    
    def _extract_serial_from_sg_vpd(self, sg_vpd_output):
        """Extract serial number from sg_vpd -p sn output"""
        try:
            lines = sg_vpd_output.split('\n')
            for i, line in enumerate(lines):
                line = line.strip()
                
                # Look for Unit serial number with colon
                if 'Unit serial number' in line and ':' in line:
                    serial = line.split(':', 1)[1].strip()
                    # Remove any non-alphanumeric characters
                    serial = re.sub(r'[^A-Za-z0-9]', '', serial)
                    if (serial and 
                        len(serial) >= 4 and 
                        len(serial) <= 32 and
                        serial.upper() not in ['UNITNUMBER', 'SERIALNUMBER', 'VPDINQUIRY']):
                        return serial
                
                # Look for serial in the line after "Unit serial number"
                elif 'Unit serial number' in line and i + 1 < len(lines):
                    next_line = lines[i + 1].strip()
                    # Clean and validate
                    next_line = re.sub(r'[^A-Za-z0-9]', '', next_line)
                    if (next_line and 
                        len(next_line) >= 4 and 
                        len(next_line) <= 32):
                        return next_line
                
                # Look for standalone alphanumeric serial numbers
                elif (re.match(r'^[A-Z0-9]{6,20}$', line) and
                      line.upper() not in ['VPD', 'INQUIRY', 'PAGE', 'SERIAL', 'NUMBER']):
                    return line
        except Exception:
            pass
        return None
    
    def _extract_serial_from_tapeinfo(self, tapeinfo_output):
        """Extract serial number from tapeinfo output"""
        try:
            for line in tapeinfo_output.split('\n'):
                line = line.strip()
                if 'serial' in line.lower() and ('number' in line.lower() or 'num' in line.lower()):
                    # Look for serial number patterns
                    if ':' in line:
                        serial = line.split(':', 1)[1].strip()
                        # Clean up and validate
                        serial = re.sub(r'[^A-Za-z0-9]', '', serial)
                        if serial and len(serial) >= 4 and len(serial) <= 20:
                            return serial
                    # Look for patterns like "Serial: ABC123" or "S/N: ABC123"
                    match = re.search(r'(?:serial|s/n)\s*:?\s*([A-Z0-9]{4,20})', line, re.IGNORECASE)
                    if match:
                        return match.group(1)
        except Exception:
            pass
        return None
    
    def _extract_ascii_from_hex(self, hex_line):
        """Extract ASCII string from hex data line"""
        try:
            # Remove spaces and convert hex to ASCII
            hex_chars = re.findall(r'[0-9a-fA-F]{2}', hex_line)
            ascii_chars = []
            for hex_char in hex_chars:
                try:
                    char_val = int(hex_char, 16)
                    # Only include printable ASCII characters
                    if 32 <= char_val <= 126:
                        ascii_chars.append(chr(char_val))
                    elif char_val == 0:  # Null terminator
                        break
                except ValueError:
                    continue
            
            ascii_string = ''.join(ascii_chars).strip()
            
            # Look for patterns that might be serial numbers
            if ascii_string and len(ascii_string) >= 4:
                # Filter out common non-serial text
                invalid_strings = [
                    'unit serial number page', 'vpd inquiry page', 'serial number',
                    'unit serial', 'inquiry page', 'page', 'vpd', 'inquiry',
                    'vendor', 'product', 'revision'
                ]
                
                ascii_lower = ascii_string.lower()
                if not any(invalid in ascii_lower for invalid in invalid_strings):
                    # Check if it looks like a serial number (alphanumeric)
                    if re.match(r'^[A-Za-z0-9]{4,20}$', ascii_string):
                        return ascii_string
        except Exception:
            pass
        return None
    
    def _extract_firmware_version(self, sg_inq_output):
        """Extract firmware version from sg_inq output"""
        try:
            for line in sg_inq_output.split('\n'):
                if 'Product revision level' in line:
                    # Extract revision after the colon
                    parts = line.split(':')
                    if len(parts) > 1:
                        revision = parts[1].strip()
                        return revision if revision else None
        except Exception:
            pass
        return None
    
    def _discover_via_sys_class(self):
        """Alternative discovery method using /sys/class/scsi_tape"""
        discovered_drives = []
        
        try:
            sys_tape_path = Path('/sys/class/scsi_tape')
            if sys_tape_path.exists():
                for tape_dir in sys_tape_path.iterdir():
                    if tape_dir.is_dir():
                        # Extract device number (e.g., st0 from /sys/class/scsi_tape/st0)
                        device_name = tape_dir.name
                        device_path = f'/dev/{device_name}'
                        
                        if Path(device_path).exists():
                            # Try to get basic info
                            drive_info = {
                                'scsi_id': 'Unknown',
                                'device_type': 'tape',
                                'vendor': 'Unknown',
                                'model': 'Unknown',
                                'revision': 'Unknown',
                                'device_path': device_path,
                                'sg_device': None,
                                'lto_generation': 'Unknown',
                                'display_name': f'Tape Drive ({device_name})'
                            }
                            
                            # Try to get hardware details
                            drive_info.update(self._get_drive_hardware_details(device_path))
                            discovered_drives.append(drive_info)
        
        except Exception as e:
            print(f"LTFS: Error discovering via /sys/class: {e}")
        
        return discovered_drives
    
    def _fallback_device_scan(self):
        """Fallback method to scan /dev/st* devices directly"""
        fallback_drives = []
        
        # Primary device that actually works with LTFS mounting
        primary_device = '/dev/st0'
        
        # Check if primary device exists and is accessible
        if Path(primary_device).exists() and Path(primary_device).is_char_device():
            if self._test_device_functionality(primary_device):
                fallback_drives.append(primary_device)
                # Create basic hardware info for fallback device
                self.drive_hardware_info[primary_device] = {
                    'scsi_id': 'Unknown',
                    'device_type': 'tape',
                    'vendor': 'Unknown',
                    'model': 'Unknown',
                    'revision': 'Unknown',
                    'device_path': primary_device,
                    'sg_device': None,
                    'lto_generation': 'Unknown',
                    'display_name': f'Tape Drive (st0)',
                    'serial_number': 'Unknown',
                    'firmware_version': 'Unknown',
                    'wwn': 'Unknown'
                }
        
        # Check for other /dev/st* devices (rewinding only, avoid nst* as they cause issues)
        for device in Path('/dev').glob('st*'):
            if (device.is_char_device() and 
                device.name not in ['stdin', 'stdout', 'stderr'] and
                re.match(r'st\d+[alm]?$', device.name) and
                str(device) != primary_device):
                device_str = str(device)
                
                if self._test_device_functionality(device_str):
                    fallback_drives.append(device_str)
                    # Create basic hardware info for fallback device
                    self.drive_hardware_info[device_str] = {
                        'scsi_id': 'Unknown',
                        'device_type': 'tape',
                        'vendor': 'Unknown',
                        'model': 'Unknown',
                        'revision': 'Unknown',
                        'device_path': device_str,
                        'sg_device': None,
                        'lto_generation': 'Unknown',
                        'display_name': f'Tape Drive ({os.path.basename(device_str)})',
                        'serial_number': 'Unknown',
                        'firmware_version': 'Unknown',
                        'wwn': 'Unknown'
                    }
        
        return sorted(fallback_drives)
    
    def _test_device_functionality(self, device_path):
        """Test if a device responds to basic commands"""
        try:
            result = subprocess.run(['mt', '-f', device_path, 'status'], 
                                  capture_output=True, timeout=5)
            return result.returncode == 0 or 'No such device' not in result.stderr.decode()
        except (subprocess.TimeoutExpired, subprocess.CalledProcessError):
            return False
    
    def _organize_physical_drives(self):
        """Organize drives by physical device and create logical groupings"""
        drive_pattern = re.compile(r'/dev/(n?)st(\d+)([alm]?)$')
        
        for device_path in self.tape_drives:
            match = drive_pattern.match(device_path)
            if match:
                rewinding = match.group(1) == ''  # Empty means rewinding (st), 'n' means non-rewinding (nst)
                drive_num = match.group(2)
                mode_suffix = match.group(3) or 'default'
                
                physical_id = f"drive{drive_num}"
                
                # Get hardware info for this device
                hw_info = self.drive_hardware_info.get(device_path, {})
                
                if physical_id not in self.physical_drives:
                    self.physical_drives[physical_id] = {
                        'drive_number': drive_num,
                        'hardware_info': hw_info,
                        'primary_device': device_path,  # Use first device as primary
                        'rewinding': [],
                        'non_rewinding': [],
                        'interface_devices': []  # All related interface devices
                    }
                else:
                    # Update with better hardware info if available
                    if hw_info.get('vendor', 'Unknown') != 'Unknown':
                        self.physical_drives[physical_id]['hardware_info'] = hw_info
                
                mode_info = {
                    'device': device_path,
                    'mode': mode_suffix,
                    'description': self._get_mode_description(mode_suffix)
                }
                
                # Add to interface devices list
                self.physical_drives[physical_id]['interface_devices'].append(device_path)
                
                if rewinding:
                    self.physical_drives[physical_id]['rewinding'].append(mode_info)
                else:
                    self.physical_drives[physical_id]['non_rewinding'].append(mode_info)
    
    def get_drive_display_info(self, device_path):
        """Get formatted display information for a drive"""
        hw_info = self.drive_hardware_info.get(device_path, {})
        
        # Create display name
        vendor = hw_info.get('vendor', 'Unknown')
        model = hw_info.get('model', 'Unknown')
        lto_gen = hw_info.get('lto_generation', '')
        serial = hw_info.get('serial_number', 'Unknown')
        
        if vendor != 'Unknown' and model != 'Unknown':
            if lto_gen and lto_gen != 'Unknown':
                display_name = f"{vendor} {model} ({lto_gen})"
            else:
                display_name = f"{vendor} {model}"
        else:
            display_name = f"Tape Drive ({os.path.basename(device_path)})"
        
        # Add serial if available
        if serial != 'Unknown':
            display_name += f" [S/N: {serial}]"
        
        return {
            'display_name': display_name,
            'device_path': device_path,
            'vendor': vendor,
            'model': model,
            'lto_generation': lto_gen,
            'serial_number': serial,
            'firmware_version': hw_info.get('firmware_version', 'Unknown')
        }
    
    def get_physical_drives_display_list(self):
        """Get a list of physical drives for display in GUI"""
        display_list = []
        
        for physical_id, drive_info in self.physical_drives.items():
            hw_info = drive_info.get('hardware_info', {})
            primary_device = drive_info.get('primary_device')
            interface_devices = drive_info.get('interface_devices', [])
            
            # Get display info for the primary device
            display_info = self.get_drive_display_info(primary_device)
            
            # Add interface information
            interfaces = ', '.join([os.path.basename(dev) for dev in interface_devices])
            
            display_entry = {
                'display_name': display_info['display_name'],
                'primary_device': primary_device,
                'interface_devices': interface_devices,
                'interfaces_summary': f"Interfaces: {interfaces}",
                'hardware_info': hw_info,
                'vendor': display_info['vendor'],
                'model': display_info['model'],
                'lto_generation': display_info['lto_generation'],
                'serial_number': display_info['serial_number']
            }
            
            display_list.append(display_entry)
        
        return display_list
    
    def get_tape_info(self, device):
        """Get information about a tape in the specified device"""
        success, stdout, stderr = self.run_command(f"mt -f {device} status")
        if success:
            return stdout
        return f"Error: {stderr}"
    
    def format_tape(self, device, label="", barcode="", force=False, block_size=None, compression=True):
        """Format a tape with LTFS"""
        cmd = f"mkltfs -d {device}"
        
        # Add label if provided
        if label:
            cmd += f" -n '{label}'"
        
        # Add force flag if requested
        if force:
            cmd += " -f"
        
        # Add compression flag
        if not compression:
            cmd += " --no-compression"
        
        # Handle block size
        if block_size and block_size != "auto":
            cmd += f" -b {block_size}"
        elif block_size == "auto" or not block_size:
            # Check if this is a Quantum LTO drive and use optimal block size
            success, stdout, stderr = self.run_command(f"sg_inq {device}")
            if success and "QUANTUM" in stdout:
                # Use smaller block size for Quantum LTO drives for better compatibility
                cmd += " -b 65536"
                print(f"Detected Quantum LTO drive, using 64KB block size for better compatibility")
            # For other drives, let mkltfs choose the optimal block size
        
        # Execute the format command
        format_success, format_stdout, format_stderr = self.run_command(cmd)
        
        # If format was successful and barcode was provided, set the MAM barcode
        if format_success and barcode:
            print(f"Format successful, setting MAM barcode: {barcode}")
            barcode_success = self._set_mam_barcode(device, barcode)
            if not barcode_success:
                print(f"Warning: Format successful but failed to set MAM barcode")
                # Don't fail the entire operation for barcode issues
        
        return format_success, format_stdout, format_stderr
    
    def _set_mam_barcode(self, device, barcode):
        """Set MAM barcode attribute (0x0806) on the tape"""
        try:
            # Convert barcode to hex bytes
            barcode_bytes = barcode.encode('ascii')
            hex_data = ' '.join(f'{b:02x}' for b in barcode_bytes)
            
            # Use sg_raw to write MAM attribute 0x0806 (Barcode)
            # Command: WRITE ATTRIBUTE (0x8D)
            cmd = f"sg_raw -s {len(barcode_bytes)} {device} 8D 00 00 08 06 00 00 {hex_data}"
            
            success, stdout, stderr = self.run_command(cmd)
            
            if success:
                print(f"Successfully set MAM barcode to: {barcode}")
                return True
            else:
                print(f"Failed to set MAM barcode: {stderr}")
                
                # Try alternative method using tapeutil if available
                alt_cmd = f"tapeutil -f {device} setparam barcode {barcode}"
                alt_success, alt_stdout, alt_stderr = self.run_command(alt_cmd)
                
                if alt_success:
                    print(f"Successfully set MAM barcode using tapeutil: {barcode}")
                    return True
                else:
                    print(f"Alternative MAM barcode method also failed: {alt_stderr}")
                    return False
        
        except Exception as e:
            print(f"Exception setting MAM barcode: {e}")
            return False
    
    def mount_tape(self, device, mount_point, options="", auto_open=True):
        """Mount an LTFS tape like removable media"""
        # Create mount point if it doesn't exist
        # Handle /media/ locations that may require sudo
        if mount_point.startswith('/media/'):
            # Use sudo to create mount point in /media/
            success, stdout, stderr = self.run_command(f"sudo mkdir -p '{mount_point}'")
            if not success:
                print(f"Warning: Could not create mount point {mount_point}: {stderr}")
                return False, "", f"Failed to create mount point: {stderr}"
            
            # Change ownership to user so they can access it
            username = os.getenv('USER', 'user')
            success, stdout, stderr = self.run_command(f"sudo chown {username}:{username} '{mount_point}'")
            if not success:
                print(f"Warning: Could not change ownership of {mount_point}: {stderr}")
        else:
            # Regular directory creation for non-media locations
            try:
                os.makedirs(mount_point, exist_ok=True)
            except PermissionError as e:
                return False, "", f"Permission denied creating mount point: {str(e)}"
        
        # First try to rewind the tape to ensure it's at the beginning
        rewind_success, _, _ = self.run_command(f"mt -f {device} rewind")
        if not rewind_success:
            print(f"Warning: Could not rewind {device}")
        
        # Enhanced mount options for better compatibility
        enhanced_options = options
        if not enhanced_options:
            username = os.getenv('USER', 'user')
            uid = os.getuid()
            gid = os.getgid()
            enhanced_options = f"-o uid={uid},gid={gid},allow_other"
        
        # Try mounting with different options to handle compatibility issues
        mount_commands = [
            f"sudo ltfs -o devname={device} {enhanced_options} '{mount_point}'",
            f"sudo ltfs -o devname={device},force_mount_no_eod {enhanced_options} '{mount_point}'",
            f"sudo ltfs -o devname={device},sync_type=unmount {enhanced_options} '{mount_point}'",
            f"sudo ltfs -o devname={device},force_mount_no_eod,sync_type=unmount {enhanced_options} '{mount_point}'"
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
            # Store mount information
            self.mounted_tapes[mount_point] = {
                'device': device,
                'mount_point': mount_point,
                'options': enhanced_options,
                'mount_time': time.time()
            }
            
            # Create desktop shortcut if mounted in /media/
            if mount_point.startswith('/media/'):
                self.create_desktop_shortcut(mount_point, device)
            
            # Automatically open in file manager if requested
            if auto_open:
                self.auto_open_mount_point(mount_point)
            
            # Send desktop notification
            self.send_mount_notification(mount_point, device, True)
        else:
            # Send failure notification
            self.send_mount_notification(mount_point, device, False)
        
        return success, stdout, stderr
    
    def create_desktop_shortcut(self, mount_point, device):
        """Create a desktop shortcut for the mounted tape"""
        try:
            username = os.getenv('USER', 'user')
            desktop_path = f"/home/{username}/Desktop"
            
            if os.path.exists(desktop_path):
                mount_name = os.path.basename(mount_point)
                shortcut_path = os.path.join(desktop_path, f"{mount_name}.desktop")
                
                # Get LTO generation for icon
                lto_gen = self.detect_lto_generation(device)
                icon_name = "media-tape" if lto_gen != "Unknown" else "folder"
                
                desktop_content = f"""[Desktop Entry]
Version=1.0
Type=Link
Name={mount_name}
Comment=LTFS Tape ({device})
URL=file://{mount_point}
Icon={icon_name}
Categories=System;
"""
                
                with open(shortcut_path, 'w') as f:
                    f.write(desktop_content)
                
                # Make it executable
                os.chmod(shortcut_path, 0o755)
                
                print(f"Created desktop shortcut: {shortcut_path}")
        except Exception as e:
            print(f"Could not create desktop shortcut: {e}")
    
    def auto_open_mount_point(self, mount_point):
        """Automatically open the mount point in file manager"""
        try:
            # Try different file managers
            file_managers = ['nemo', 'nautilus', 'dolphin', 'thunar', 'pcmanfm', 'xdg-open']
            
            for fm in file_managers:
                try:
                    subprocess.run([fm, mount_point], check=True, 
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    print(f"Opened {mount_point} in {fm}")
                    return
                except (subprocess.CalledProcessError, FileNotFoundError):
                    continue
            
            print(f"Could not auto-open {mount_point} - no suitable file manager found")
        except Exception as e:
            print(f"Error auto-opening mount point: {e}")
    
    def send_mount_notification(self, mount_point, device, success):
        """Send desktop notification about mount status"""
        try:
            mount_name = os.path.basename(mount_point)
            
            if success:
                title = "LTFS Tape Mounted"
                message = f"'{mount_name}' is now available"
                icon = "media-tape"
            else:
                title = "LTFS Mount Failed"
                message = f"Could not mount tape from {device}"
                icon = "dialog-error"
            
            # Try to send notification using notify-send
            subprocess.run([
                'notify-send', 
                '--icon', icon,
                '--app-name', 'LTFS Manager',
                title, message
            ], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
        except Exception:
            # Notification failed, but don't error out
            pass
    
    def unmount_tape(self, mount_point):
        """Unmount an LTFS tape"""
        # Try different unmount methods in order
        unmount_commands = [
            f"sudo umount '{mount_point}'",  # Standard umount with sudo
            f"fusermount -u '{mount_point}'",  # FUSE unmount
            f"sudo fusermount -u '{mount_point}'"  # FUSE unmount with sudo
        ]
        
        success = False
        stdout = ""
        stderr = ""
        
        for cmd in unmount_commands:
            print(f"Trying unmount command: {cmd}")
            success, stdout, stderr = self.run_command(cmd)
            if success:
                break
            print(f"Unmount attempt failed: {stderr}")
        
        if success and mount_point in self.mounted_tapes:
            del self.mounted_tapes[mount_point]
        
        return success, stdout, stderr
    
    def generate_mount_point(self, device, tape_label=None, lto_generation=None):
        """Generate a user-friendly mount point like optical drives/USB drives"""
        import time
        import os
        
        # Extract device name (e.g., st0 from /dev/st0)
        device_name = os.path.basename(device)
        username = os.getenv('USER', 'user')
        
        # Get tape information for better naming
        tape_info = self.get_tape_volume_info(device)
        volume_label = tape_info.get('volume_label')
        
        # Generate a descriptive mount name
        if volume_label and volume_label.strip():
            # Use tape's volume label if available
            mount_name = self.sanitize_mount_name(volume_label)
        elif tape_label and tape_label.strip():
            # Use provided label
            mount_name = self.sanitize_mount_name(tape_label)
        else:
            # Generate descriptive name based on LTO type
            lto_type = lto_generation or self.detect_lto_generation(device)
            if lto_type and lto_type != 'Unknown':
                mount_name = f"{lto_type}_Tape"
            else:
                mount_name = "LTFS_Tape"
        
        # Primary location: /media/username/ (like USB drives and optical media)
        media_user_path = f"/media/{username}"
        
        # Ensure media directory exists with proper permissions
        success = self.ensure_media_directory(media_user_path)
        
        if success:
            mount_point = os.path.join(media_user_path, mount_name)
            
            # Handle naming conflicts by adding numbers
            counter = 1
            original_mount_point = mount_point
            while os.path.exists(mount_point):
                mount_point = f"{original_mount_point}_{counter}"
                counter += 1
            
            return mount_point
        
        # Fallback to desktop if media directory unavailable
        desktop_path = f"/home/{username}/Desktop"
        if os.path.exists(desktop_path) and os.access(desktop_path, os.W_OK):
            mount_point = os.path.join(desktop_path, mount_name)
            counter = 1
            original_mount_point = mount_point
            while os.path.exists(mount_point):
                mount_point = f"{original_mount_point}_{counter}"
                counter += 1
            return mount_point
        
        # Final fallback - user home directory
        home_mount_point = f"/home/{username}/{mount_name}"
        counter = 1
        original_mount_point = home_mount_point
        while os.path.exists(home_mount_point):
            home_mount_point = f"{original_mount_point}_{counter}"
            counter += 1
        
        return home_mount_point
    
    def get_tape_volume_info(self, device):
        """Get volume information from the tape"""
        volume_info = {
            'volume_label': None,
            'capacity': None,
            'used_space': None
        }
        
        try:
            # Try to get volume label using ltfs command
            success, stdout, stderr = self.run_command(f"ltfs -o devname={device} --help")
            
            # Try alternative methods to get tape info
            success, stdout, stderr = self.run_command(f"tapeinfo -f {device}")
            if success:
                for line in stdout.split('\n'):
                    if 'volume' in line.lower() and 'label' in line.lower():
                        parts = line.split(':')
                        if len(parts) > 1:
                            volume_info['volume_label'] = parts[1].strip()
                            break
        except Exception:
            pass
        
        return volume_info
    
    def sanitize_mount_name(self, name):
        """Sanitize a name for use as a mount point"""
        import re
        # Remove invalid characters and replace with underscores
        sanitized = re.sub(r'[^A-Za-z0-9_\-]', '_', name)
        # Remove multiple consecutive underscores
        sanitized = re.sub(r'_+', '_', sanitized)
        # Remove leading/trailing underscores
        sanitized = sanitized.strip('_')
        # Ensure it's not empty
        if not sanitized:
            sanitized = "LTFS_Tape"
        return sanitized
    
    def detect_lto_generation(self, device):
        """Detect LTO generation from device information"""
        hw_info = self.drive_hardware_info.get(device, {})
        return hw_info.get('lto_generation', 'Unknown')
    
    def ensure_media_directory(self, media_path):
        """Ensure media directory exists with proper permissions"""
        try:
            if not os.path.exists(media_path):
                # Try to create with sudo if needed
                success, stdout, stderr = self.run_command(f"sudo mkdir -p '{media_path}'")
                if not success:
                    print(f"Failed to create media directory: {stderr}")
                    return False
                
                # Set proper ownership
                username = os.getenv('USER', 'user')
                success, stdout, stderr = self.run_command(f"sudo chown {username}:{username} '{media_path}'")
                if not success:
                    print(f"Warning: Could not set ownership of {media_path}")
                
                print(f"Created media directory: {media_path}")
            
            # Check if we can write to it
            return os.access(media_path, os.W_OK)
        except Exception as e:
            print(f"Error ensuring media directory: {e}")
            return False
    
    def list_mounted_tapes(self):
        """List currently mounted LTFS tapes"""
        success, stdout, stderr = self.run_command("mount | grep ltfs")
        return stdout if success else ""

class LTFSGui:
    def refresh_tape_status(self):
        theme = self.themes.get(self.current_theme_name.get(), self.themes['light'])
        success_color = theme.get('success_fg', 'green')
        warning_color = theme.get('warning_fg', 'red')
        device = self.get_selected_device()
        if device and self.ltfs_manager.is_tape_loaded(device):
            barcode = self.ltfs_manager.get_tape_barcode(device)
            self.tape_status_label.config(text=f'Tape Loaded: {barcode}', foreground=success_color)
        else:
            self.tape_status_label.config(text='No Tape Loaded', foreground=warning_color)
        self.root.after(5000, self.refresh_tape_status)
    def __init__(self, root):
        self.root = root
        self.root.title("LTFS Manager")
        self.root.geometry("800x600")
        self._set_application_icon()
        
        # Theme settings with multiple options - will be initialized after theme definitions
        self.current_theme_name = tk.StringVar()
        self.themes = {
            'light': {
                'name': 'Light (Mint)',
                'bg': '#f7f7f7',               # Light window background
                'fg': '#2e2e2e',               # Dark text on light
                'select_bg': '#1f9ede',        # Mint accent color
                'select_fg': '#ffffff',        # White text on accent
                'entry_bg': '#ffffff',         # White input fields
                'entry_fg': '#2e2e2e',         # Dark text in inputs
                'frame_bg': '#f7f7f7',         # Light frame background
                'button_bg': '#e8e8e8',        # Light button background
                'button_hover': '#d4d4d4',     # Button hover state
                'text_bg': '#ffffff',          # Text widget background
                'text_fg': '#2e2e2e',          # Text widget foreground
                'notebook_bg': '#f7f7f7',      # Tab container background
                'tab_bg': '#e8e8e8',           # Tab background
                'tab_active': '#ffffff',       # Active tab background
                'border_color': '#d0d0d0',     # Border colors
                'warning_fg': '#d73502',       # Warning text
                'success_fg': '#5aa02c',       # Success text
                'info_fg': '#666666'           # Info text
            },
            'dark': {
                'name': 'Dark (Mint)',
                # Exact Linux Mint Mint-Y-Dark-Aqua colors
                'bg': '#383838',               # theme_bg_color from Mint
                'fg': '#DADADA',               # theme_text_color from Mint  
                'select_bg': '#1f9ede',        # theme_selected_bg_color from Mint
                'select_fg': '#ffffff',        # theme_selected_fg_color from Mint
                'entry_bg': '#404040',         # theme_base_color from Mint
                'entry_fg': '#DADADA',         # Text in entry fields
                'frame_bg': '#383838',         # Same as main background
                'button_bg': '#4a4a4a',        # Slightly lighter than base
                'button_hover': '#525252',     # Button hover state
                'text_bg': '#404040',          # Text widget background
                'text_fg': '#DADADA',          # Text widget text
                'notebook_bg': '#383838',      # Tab container
                'tab_bg': '#4a4a4a',           # Inactive tabs
                'tab_active': '#5a5a5a',       # Active tab
                'border_color': '#2a2a2a',     # Darker borders
                'warning_fg': '#ff6b6b',       # Warning text
                'success_fg': '#51cf66',       # Success text
                'info_fg': '#adb5bd'           # Info text
            },
            'blue_dark': {
                'name': 'Blue Dark',
                'bg': '#1a1d29',
                'fg': '#e8eaed',
                'select_bg': '#1e88e5',
                'select_fg': '#ffffff',
                'entry_bg': '#2d3748',
                'entry_fg': '#e8eaed',
                'frame_bg': '#1a1d29',
                'button_bg': '#2d3748',
                'button_hover': '#3d4758',
                'text_bg': '#0f172a',
                'text_fg': '#e8eaed',
                'notebook_bg': '#1a1d29',
                'tab_bg': '#2d3748',
                'tab_active': '#3d4758',
                'border_color': '#475569',
                'warning_fg': '#f87171',
                'success_fg': '#34d399',
                'info_fg': '#94a3b8'
            },
            'high_contrast': {
                'name': 'High Contrast',
                'bg': '#000000',
                'fg': '#ffffff',
                'select_bg': '#ffff00',
                'select_fg': '#000000',
                'entry_bg': '#111111',
                'entry_fg': '#ffffff',
                'frame_bg': '#000000',
                'button_bg': '#333333',
                'button_hover': '#444444',
                'text_bg': '#000000',
                'text_fg': '#ffffff',
                'notebook_bg': '#000000',
                'tab_bg': '#333333',
                'tab_active': '#444444',
                'border_color': '#ffffff',
                'warning_fg': '#ff0000',
                'success_fg': '#00ff00',
                'info_fg': '#cccccc'
            },
            'system': {
                'name': 'System Default',
                # Will be populated by detect_system_colors()
            }
        }
        
        # Populate system theme
        self.themes['system'].update(self.detect_system_colors())
        
        # Initialize current theme with saved preference or system detection
        try:
            saved_theme = self.load_theme_preference()
            if saved_theme in self.themes:
                self.current_theme_name.set(saved_theme)
            else:
                detected_theme = self.detect_system_theme()
                self.current_theme_name.set(detected_theme)
        except:
            self.current_theme_name.set('light')
        
        # Legacy dark_mode variable for backwards compatibility
        self.dark_mode = tk.BooleanVar(value=self.current_theme_name.get() in ['dark', 'blue_dark', 'high_contrast'])
        
        self.ltfs_manager = LTFSManager()
        self.setup_ui()
        
        # Add tape status label at the bottom
        self.tape_status_label = ttk.Label(self.root, text="Tape Status: Unknown", anchor='w')
        self.tape_status_label.pack(side='bottom', fill='x', padx=10, pady=5)
        
        # Start tape status monitoring after UI is fully setup
        self.refresh_tape_status()
        
        # Apply the saved/detected theme
        self.apply_selected_theme()
        self.refresh_drives()

    def _set_application_icon(self):
        """Set application icon for the main GUI window."""
        icon_candidates = []
        script_dir = Path(__file__).resolve().parent

        icon_candidates.append(script_dir / "packaging" / "appimage" / "ltfs-gui.png")
        icon_candidates.append(script_dir / "ltfs-gui.png")
        try:
            icon_candidates.append(Path(sys.executable).resolve().parent / "ltfs-gui.png")
        except Exception:
            pass

        for icon_path in icon_candidates:
            if not icon_path.exists():
                continue
            try:
                self._app_icon_image = tk.PhotoImage(file=str(icon_path))
                self.root.iconphoto(True, self._app_icon_image)
                return
            except Exception:
                continue
        
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
        
        # MAM tab (Medium Auxiliary Memory)
        self.mam_frame = ttk.Frame(notebook)
        notebook.add(self.mam_frame, text="MAM")
        self.setup_mam_tab()
        
        # Theme Control tab
        self.theme_control_frame = ttk.Frame(notebook)
        notebook.add(self.theme_control_frame, text="Theme")
        self.setup_theme_control_tab()
        
        # Log tab
        self.log_frame = ttk.Frame(notebook)
        notebook.add(self.log_frame, text="Log")
        self.setup_log_tab()
        
        # Add dark mode toggle to the main window
        self.setup_theme_controls()
    
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
        mount_section = ttk.LabelFrame(self.mount_frame, text="Mount Tape (Like Optical Drive)", padding=10)
        mount_section.pack(fill='x', padx=10, pady=10)
        
        # Info label
        info_text = "Tapes will be mounted like removable media (USB drives/CDs) and appear in your file manager."
        info_label = ttk.Label(mount_section, text=info_text, font=('Arial', 9), style='Info.TLabel')
        info_label.grid(row=0, column=0, columnspan=3, sticky='w', pady=(0, 10))
        
        # Device/Mode selection (will be updated based on drive count)
        self.device_label = ttk.Label(mount_section, text="Device:")
        self.device_label.grid(row=1, column=0, sticky='w', pady=5)
        self.mount_device_var = tk.StringVar()
        self.mount_device_combo = ttk.Combobox(mount_section, textvariable=self.mount_device_var, width=30)
        self.mount_device_combo.grid(row=1, column=1, sticky='ew', padx=(10, 0), pady=5)
        self.mount_device_combo.bind('<<ComboboxSelected>>', self.on_device_selected)
        
        # Mode selection frame (initially hidden)
        self.mode_frame = ttk.Frame(mount_section)
        self.mode_frame.grid(row=2, column=0, columnspan=3, sticky='ew', pady=5)
        
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
        ttk.Label(mount_section, text="Mount Point:").grid(row=3, column=0, sticky='w', pady=5)
        self.mount_point_var = tk.StringVar(value="")
        self.mount_point_entry = ttk.Entry(mount_section, textvariable=self.mount_point_var, width=30)
        self.mount_point_entry.grid(row=3, column=1, sticky='ew', padx=(10, 0), pady=5)
        ttk.Button(mount_section, text="Browse", command=self.browse_mount_point).grid(row=3, column=2, padx=(5, 0), pady=5)
        
        # Mount point help
        mount_help = ttk.Label(mount_section, text="Auto-generated based on tape label/type (appears in /media/ like USB drives)", 
                              font=('Arial', 8), style='Info.TLabel')
        mount_help.grid(row=4, column=0, columnspan=3, sticky='w', pady=(0, 5))
        
        # Auto-open option
        self.auto_open_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(mount_section, text="Automatically open in file manager after mounting", 
                       variable=self.auto_open_var).grid(row=5, column=0, columnspan=3, sticky='w', pady=5)
        
        # Mount options (advanced)
        ttk.Label(mount_section, text="Advanced Options:").grid(row=6, column=0, sticky='w', pady=5)
        self.mount_options_var = tk.StringVar(value="")
        ttk.Entry(mount_section, textvariable=self.mount_options_var, width=30).grid(row=6, column=1, sticky='ew', padx=(10, 0), pady=5)
        
        # Mount button
        mount_button = ttk.Button(mount_section, text="🗄️ Mount Tape", command=self.mount_tape)
        mount_button.grid(row=7, column=1, pady=15)
        
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
        
        # MAM Barcode field
        ttk.Label(format_section, text="MAM Barcode:").grid(row=2, column=0, sticky='w', pady=10)
        self.mam_barcode_var = tk.StringVar()
        barcode_entry = ttk.Entry(format_section, textvariable=self.mam_barcode_var, width=30)
        barcode_entry.grid(row=2, column=1, sticky='ew', padx=(10, 0), pady=10)
        
        # Barcode help text
        barcode_help = ttk.Label(format_section, text="Optional: Set MAM barcode attribute (e.g., LTO123456)", 
                                font=('Arial', 9), style='Info.TLabel')
        barcode_help.grid(row=3, column=0, columnspan=2, sticky='w', pady=(0, 10))
        
        # Force format option
        self.force_format_var = tk.BooleanVar()
        ttk.Checkbutton(format_section, text="Force format (overwrite existing data)", 
                       variable=self.force_format_var).grid(row=4, column=0, columnspan=2, sticky='w', pady=10)
        
        # Advanced options section
        advanced_frame = ttk.LabelFrame(format_section, text="Advanced Options", padding=10)
        advanced_frame.grid(row=5, column=0, columnspan=2, sticky='ew', pady=10)
        
        # Block size option
        block_frame = ttk.Frame(advanced_frame)
        block_frame.pack(fill='x', pady=5)
        
        ttk.Label(block_frame, text="Block Size:").pack(side='left')
        self.block_size_var = tk.StringVar(value="auto")
        block_combo = ttk.Combobox(block_frame, textvariable=self.block_size_var, 
                                  values=["auto", "32768", "65536", "131072", "262144", "524288"],
                                  width=15, state="readonly")
        block_combo.pack(side='left', padx=(10, 0))
        
        ttk.Label(block_frame, text="(auto = optimal for drive type)", 
                 font=('Arial', 9), style='Info.TLabel').pack(side='left', padx=(10, 0))
        
        # Compression option
        compression_frame = ttk.Frame(advanced_frame)
        compression_frame.pack(fill='x', pady=5)
        
        self.format_compression_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(compression_frame, text="Enable compression during format", 
                       variable=self.format_compression_var).pack(side='left')
        
        # Warning
        warning_label = ttk.Label(format_section, text="⚠️  WARNING: Formatting will erase all data on the tape!", 
                                 style='Warning.TLabel', font=('Arial', 10, 'bold'))
        warning_label.grid(row=6, column=0, columnspan=2, pady=20)
        
        # Format button
        ttk.Button(format_section, text="Format Tape", command=self.format_tape).grid(row=7, column=1, pady=20)
        
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
                                 wraplength=600, justify='left', style='Info.TLabel')
            desc_label.pack(anchor='w')
            
            # Effects
            effect_label = ttk.Label(desc_frame, text=mode_info["effect"], 
                                   font=('Arial', 9), style='Success.TLabel')
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
                               font=('Arial', 10), style='Status.TLabel')
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
    
    def _resolve_device_from_selection(self, selected_value):
        """Resolve a combo-box value to an actual /dev tape device path."""
        if not selected_value:
            return selected_value
        
        if hasattr(self, 'device_combo_mapping') and selected_value in self.device_combo_mapping:
            return self.device_combo_mapping[selected_value]
        
        match = re.search(r'\((/dev/[^)]+)\)$', selected_value)
        if match:
            return match.group(1)
        
        return selected_value
    
    def _get_selected_diagnostics_device(self):
        """Return diagnostics device as an actual /dev path."""
        selected_value = self.diagnostics_device_var.get()
        return self._resolve_device_from_selection(selected_value)
    
    def _get_selected_mam_device(self):
        """Return MAM device as an actual /dev path."""
        selected_value = self.mam_device_var.get()
        return self._resolve_device_from_selection(selected_value)
    
    @staticmethod
    def _parse_mt_compression_status(status_output):
        """Parse mt status output and return True/False/None for compression."""
        lowered = status_output.lower()
        
        if re.search(r'data\s*compression\s*enabled\s*=\s*0', lowered):
            return False
        if re.search(r'\bcompression\b[^\n]*(off|disabled)\b', lowered):
            return False
        if re.search(r'data\s*compression\s*enabled\s*=\s*1', lowered):
            return True
        if re.search(r'\bcompression\b[^\n]*(on|enabled)\b', lowered):
            return True
        
        return None
    
    def _compression_config_path(self):
        """Path for persisted per-device compression mode preferences."""
        config_dir = os.path.expanduser('~/.config/ltfs-gui')
        os.makedirs(config_dir, exist_ok=True)
        return os.path.join(config_dir, 'compression_modes.json')
    
    def _load_compression_preferences(self):
        """Load compression preferences from disk."""
        config_path = self._compression_config_path()
        if not os.path.exists(config_path):
            return {}
        
        try:
            with open(config_path, 'r') as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
        
        return {}
    
    def _save_compression_preferences(self, preferences):
        """Save compression preferences to disk."""
        config_path = self._compression_config_path()
        try:
            with open(config_path, 'w') as f:
                json.dump(preferences, f, indent=2)
        except Exception as e:
            self.log_message(f"Warning: Could not save compression preferences: {str(e)}")
    
    def _get_saved_compression_mode(self, device):
        """Return a previously saved mode for a device, if valid."""
        preferences = self._load_compression_preferences()
        mode = preferences.get(device)
        if mode in self.compression_modes:
            return mode
        return None
    
    def _set_saved_compression_mode(self, device, mode):
        """Persist compression mode for a specific device."""
        preferences = self._load_compression_preferences()
        preferences[device] = mode
        self._save_compression_preferences(preferences)
    
    def apply_compression_settings(self):
        """Apply the selected compression settings to the drive"""
        selected_device = self.compression_device_var.get()
        device = self._resolve_device_from_selection(selected_device)
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
            
            compression_value = "0" if mode == "none" else "1"
            success, stdout, stderr = self.ltfs_manager.run_command(
                f"mt -f {device} compression {compression_value}"
            )
            
            if success:
                self._set_saved_compression_mode(device, mode)
                
                verify_success, verify_stdout, _ = self.ltfs_manager.run_command(f"mt -f {device} status")
                detected_state = self._parse_mt_compression_status(verify_stdout) if verify_success else None
                if detected_state is None:
                    state_desc = "unknown (saved mode applied)"
                else:
                    state_desc = "enabled" if detected_state else "disabled"
                
                self.log_message(f"Successfully applied {mode_title} compression to {device}")
                self.compression_status_var.set(f"Applied: {mode_title} on {device} (hardware: {state_desc})")
                messagebox.showinfo("Success", f"Compression mode set to {mode_title} on {device}")
            else:
                self.log_message(f"Failed to apply compression settings to {device}")
                messagebox.showerror("Error", f"Failed to apply compression settings:\n{stderr}")
        
        threading.Thread(target=apply_compression_thread, daemon=True).start()
    
    def get_current_compression(self):
        """Get the current compression settings from the selected drive"""
        selected_device = self.compression_device_var.get()
        device = self._resolve_device_from_selection(selected_device)
        if not device:
            messagebox.showerror("Error", "Please select a tape drive first.")
            return
        
        def get_compression_thread():
            self.log_message(f"Getting compression settings for {device}...")
            
            success, stdout, stderr = self.ltfs_manager.run_command(f"mt -f {device} status")
            if not success:
                self.log_message(f"Failed to get compression status for {device}: {stderr}")
                messagebox.showerror("Error", f"Failed to get compression status:\n{stderr}")
                return
            
            detected_state = self._parse_mt_compression_status(stdout)
            saved_mode = self._get_saved_compression_mode(device)
            
            if detected_state is False:
                current_mode = "none"
                status_note = "detected from hardware"
            elif detected_state is True:
                current_mode = saved_mode if saved_mode and saved_mode != "none" else "default"
                status_note = "detected from hardware"
            else:
                current_mode = saved_mode if saved_mode else "default"
                status_note = "hardware status unavailable, using saved/default mode"
            
            mode_info = self.compression_modes.get(current_mode, self.compression_modes["default"])
            
            self.compression_mode_var.set(current_mode)
            self.compression_status_var.set(
                f"Current setting: {mode_info.get('title', current_mode)} ({status_note})"
            )
            self.log_message(
                f"Current compression mode for {device}: {mode_info.get('title', current_mode)} ({status_note})"
            )
        
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
                               font=('Arial', 10), style='Status.TLabel')
        status_label.pack(anchor='w', pady=(15, 0))
        
        # Bind drive selection
        self.diagnostics_device_combo.bind('<<ComboboxSelected>>', self.on_diagnostics_drive_change)
    
    def on_diagnostics_drive_change(self, event=None):
        """Handle drive selection change in diagnostics tab"""
        selected_drive = self._get_selected_diagnostics_device()
        if selected_drive:
            self.diagnostics_status_var.set(f"Drive selected: {selected_drive} - Choose diagnostic test")
    
    def check_drive_status(self):
        """Check basic drive status"""
        device = self._get_selected_diagnostics_device()
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
        device = self._get_selected_diagnostics_device()
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
        device = self._get_selected_diagnostics_device()
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
        device = self._get_selected_diagnostics_device()
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
        device = self._get_selected_diagnostics_device()
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
        device = self._get_selected_diagnostics_device()
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
        device = self._get_selected_diagnostics_device()
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
        device = self._get_selected_diagnostics_device()
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
        device = self._get_selected_diagnostics_device()
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
        device = self._get_selected_diagnostics_device()
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
        device = self._get_selected_diagnostics_device()
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
        device = self._get_selected_diagnostics_device()
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
        device = self._get_selected_diagnostics_device()
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
        device = self._get_selected_diagnostics_device()
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
        device = self._get_selected_diagnostics_device()
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
        device = self._get_selected_diagnostics_device()
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
        device = self._get_selected_diagnostics_device()
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
        
        # Add any pending log messages that were stored during initialization
        if hasattr(self, '_pending_log_messages'):
            for log_entry in self._pending_log_messages:
                self.log_text.insert(tk.END, log_entry)
            self.log_text.see(tk.END)
            # Clear pending messages
            delattr(self, '_pending_log_messages')
        
        # Log controls
        log_controls = ttk.Frame(self.log_frame)
        log_controls.pack(fill='x', padx=10, pady=5)
        
        ttk.Button(log_controls, text="Clear Log", command=self.clear_log).pack(side='left', padx=(0, 10))
        ttk.Button(log_controls, text="Save Log", command=self.save_log).pack(side='left')
    
    def log_message(self, message):
        """Add a message to the log"""
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        log_entry = f"[{timestamp}] {message}\n"
        
        # Safety check for early initialization calls
        if hasattr(self, 'log_text') and self.log_text is not None:
            self.log_text.insert(tk.END, log_entry)
            self.log_text.see(tk.END)
        else:
            # Store messages for later if log widget doesn't exist yet
            if not hasattr(self, '_pending_log_messages'):
                self._pending_log_messages = []
            self._pending_log_messages.append(log_entry)
    
    def refresh_drives(self):
        """Refresh the list of available drives"""
        drives = self.ltfs_manager.refresh_drives()
        
        # Get physical drives display list
        physical_drives = self.ltfs_manager.get_physical_drives_display_list()
        
        # Update drives listbox with enhanced display information
        self.drives_listbox.delete(0, tk.END)
        
        if physical_drives:
            for drive_info in physical_drives:
                display_name = drive_info['display_name']
                interfaces = drive_info['interfaces_summary']
                
                # Create a comprehensive display entry
                listbox_entry = f"{display_name}\n    {interfaces}"
                self.drives_listbox.insert(tk.END, listbox_entry)
                
                # Store mapping for later use
                if not hasattr(self, 'drive_mapping'):
                    self.drive_mapping = {}
                self.drive_mapping[listbox_entry] = drive_info
        else:
            # Fallback to simple device listing if no enhanced info available
            for drive in drives:
                display_info = self.ltfs_manager.get_drive_display_info(drive)
                display_name = display_info['display_name']
                self.drives_listbox.insert(tk.END, f"{display_name} ({drive})")
        
        # Create device lists for dropdowns (use primary devices for operations)
        device_list = []
        display_device_list = []
        
        if physical_drives:
            for drive_info in physical_drives:
                primary_device = drive_info['primary_device']
                display_name = drive_info['display_name']
                device_list.append(primary_device)
                display_device_list.append(f"{display_name} ({primary_device})")
        else:
            # Fallback to simple device list
            for drive in drives:
                display_info = self.ltfs_manager.get_drive_display_info(drive)
                device_list.append(drive)
                display_device_list.append(f"{display_info['display_name']} ({drive})")
        
        # Update mount tab based on single drive mode
        self.update_mount_tab_mode()
        
        # Update combo boxes with enhanced display names
        self.format_device_combo['values'] = display_device_list
        self.compression_device_combo['values'] = display_device_list
        self.diagnostics_device_combo['values'] = display_device_list
        self.mam_device_combo['values'] = display_device_list
        
        # Store device mapping for combo boxes
        self.device_combo_mapping = dict(zip(display_device_list, device_list))
        
        if display_device_list:
            self.format_device_var.set(display_device_list[0])
            self.compression_device_var.set(display_device_list[0])
            self.diagnostics_device_var.set(display_device_list[0])
            self.mam_device_var.set(display_device_list[0])
        
        # Log discovered drives with enhanced information
        if physical_drives:
            self.log_message(f"Found {len(physical_drives)} physical tape drives:")
            for drive_info in physical_drives:
                vendor = drive_info['vendor']
                model = drive_info['model']
                lto_gen = drive_info['lto_generation']
                serial = drive_info['serial_number']
                interfaces = len(drive_info['interface_devices'])
                
                log_msg = f"  • {vendor} {model}"
                if lto_gen != 'Unknown':
                    log_msg += f" ({lto_gen})"
                if serial != 'Unknown':
                    log_msg += f" [S/N: {serial}]"
                log_msg += f" - {interfaces} interface(s)"
                
                self.log_message(log_msg)
        else:
            self.log_message(f"Found {len(drives)} tape drive interface(s): {', '.join(drives)}")
        
        # Check for permission issues
        if hasattr(self.ltfs_manager, 'permission_issues') and self.ltfs_manager.permission_issues:
            self.log_message(f"⚠️ Permission issues detected for: {', '.join(self.ltfs_manager.permission_issues)}")
            self.show_permission_warning()
        
        if self.ltfs_manager.single_drive_mode:
            self.log_message("Single drive detected - interface selection available")
    
    def update_mount_tab_mode(self):
        """Update mount tab interface - use enhanced device selection"""
        # Always use simple device selection - no complex mode interface
        self.device_label.config(text="Device:")
        self.mode_frame.grid_remove()
        self.mount_device_combo.grid()
        
        # Use enhanced display device list if available
        if hasattr(self, 'device_combo_mapping') and self.device_combo_mapping:
            display_devices = list(self.device_combo_mapping.keys())
            self.mount_device_combo['values'] = display_devices
            
            # Set first available device as default
            if display_devices:
                self.mount_device_var.set(display_devices[0])
        else:
            # Fallback to simple device list
            drives = self.ltfs_manager.tape_drives
            self.mount_device_combo['values'] = drives
            
            # Set /dev/st0 as default if available, otherwise use first available
            if '/dev/st0' in drives:
                self.mount_device_var.set('/dev/st0')
            elif drives:
                self.mount_device_var.set(drives[0])
        
        # Log the default selection and auto-generate mount point
        default_selection = self.mount_device_var.get()
        if default_selection:
            # Get actual device path
            if hasattr(self, 'device_combo_mapping') and default_selection in self.device_combo_mapping:
                default_device = self.device_combo_mapping[default_selection]
                self.log_message(f"Default mount device set to: {default_selection}")
            else:
                default_device = default_selection
                self.log_message(f"Default mount device set to: {default_device}")
            
            # Auto-generate mount point if not already set
            if not self.mount_point_var.get().strip():
                mount_point = self.generate_mount_point(default_device)
                self.mount_point_var.set(mount_point)
                self.log_message(f"Auto-generated mount point: {mount_point}")
    
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
    
    def get_selected_device(self, use_sg_device=False):
        """Get the currently selected device - handle enhanced device selection"""
        selected_display = self.mount_device_var.get()
        selected_device = self._resolve_device_from_selection(selected_display)
        
        if use_sg_device and selected_device:
            hw_info = self.ltfs_manager.drive_hardware_info.get(selected_device, {})
            sg_device = hw_info.get('sg_device')
            if sg_device:
                selected_device = sg_device
        
        if not selected_device:
            # Auto-select first available device if none selected
            if self.ltfs_manager.tape_drives:
                selected_device = self.ltfs_manager.tape_drives[0]
                # Update display accordingly
                if hasattr(self, 'device_combo_mapping'):
                    # Find display name for this device
                    for display_name, device_path in self.device_combo_mapping.items():
                        if device_path == selected_device:
                            self.mount_device_var.set(display_name)
                            break
                else:
                    self.mount_device_var.set(selected_device)
        
        return selected_device
    
    def get_drive_info(self):
        """Get information about the selected drive"""
        selection = self.drives_listbox.curselection()
        if not selection:
            messagebox.showwarning("Warning", "Please select a drive first.")
            return
        
        selected_text = self.drives_listbox.get(selection[0])
        
        # Get drive info from mapping or extract device path
        if hasattr(self, 'drive_mapping') and selected_text in self.drive_mapping:
            drive_info = self.drive_mapping[selected_text]
            primary_device = drive_info['primary_device']
            
            # Get tape status
            tape_info = self.ltfs_manager.get_tape_info(primary_device)
            
            # Create comprehensive info display
            info_text = f"Physical Drive Information:\n"
            info_text += f"{'='*50}\n"
            info_text += f"Drive Model: {drive_info['vendor']} {drive_info['model']}\n"
            
            hw_info = drive_info['hardware_info']
            if drive_info['lto_generation'] != 'Unknown':
                info_text += f"LTO Generation: {drive_info['lto_generation']}\n"
            if drive_info['serial_number'] != 'Unknown':
                info_text += f"Serial Number: {drive_info['serial_number']}\n"
            if hw_info.get('firmware_version', 'Unknown') != 'Unknown':
                info_text += f"Firmware Version: {hw_info['firmware_version']}\n"
            
            info_text += f"\nInterface Devices:\n"
            for device in drive_info['interface_devices']:
                info_text += f"  • {device}\n"
            
            info_text += f"\nPrimary Device: {primary_device}\n"
            info_text += f"\nTape Status (from {primary_device}):\n"
            info_text += f"{'-'*30}\n"
            info_text += tape_info
            
        else:
            # Fallback: extract device path from display text
            if '(' in selected_text and ')' in selected_text:
                # Extract device path from parentheses
                device_start = selected_text.rfind('(') + 1
                device_end = selected_text.rfind(')')
                device = selected_text[device_start:device_end]
            else:
                device = selected_text
            
            tape_info = self.ltfs_manager.get_tape_info(device)
            info_text = f"Drive: {selected_text}\n\n{tape_info}"
        
        self.drive_info_text.delete(1.0, tk.END)
        self.drive_info_text.insert(1.0, info_text)
        
        self.log_message(f"Retrieved info for selected drive")
    
    def eject_selected_drive(self):
        """Eject tape from the selected drive"""
        selection = self.drives_listbox.curselection()
        if not selection:
            messagebox.showwarning("Warning", "Please select a drive first.")
            return
        
        selected_text = self.drives_listbox.get(selection[0])
        
        # Get primary device from mapping or extract from text
        if hasattr(self, 'drive_mapping') and selected_text in self.drive_mapping:
            drive_info = self.drive_mapping[selected_text]
            device = drive_info['primary_device']
            display_name = drive_info['display_name']
        else:
            # Fallback: extract device path from display text
            if '(' in selected_text and ')' in selected_text:
                device_start = selected_text.rfind('(') + 1
                device_end = selected_text.rfind(')')
                device = selected_text[device_start:device_end]
                display_name = selected_text[:device_start-1].strip()
            else:
                device = selected_text
                display_name = selected_text
        
        if messagebox.askyesno("Confirm Eject", f"Eject tape from {display_name}\n({device})?"):
            def eject_thread():
                self.log_message(f"Ejecting tape from {display_name} ({device})")
                success, stdout, stderr = self.ltfs_manager.run_command(f"mt -f {device} eject")
                
                if not success:
                    # Try offline command if eject fails
                    success, stdout, stderr = self.ltfs_manager.run_command(f"mt -f {device} offline")
                
                if success:
                    self.log_message(f"Tape ejected successfully from {display_name}")
                    messagebox.showinfo("Success", f"Tape ejected from {display_name}")
                else:
                    error_msg = stderr if stderr else "Unknown error occurred"
                    self.log_message(f"Failed to eject from {display_name}: {error_msg}")
                    messagebox.showerror("Error", f"Failed to eject tape:\n{error_msg}")
            
            threading.Thread(target=eject_thread, daemon=True).start()
    
    def rewind_selected_drive(self):
        """Rewind tape in the selected drive"""
        selection = self.drives_listbox.curselection()
        if not selection:
            messagebox.showwarning("Warning", "Please select a drive first.")
            return
        
        selected_text = self.drives_listbox.get(selection[0])
        
        # Get primary device from mapping or extract from text
        if hasattr(self, 'drive_mapping') and selected_text in self.drive_mapping:
            drive_info = self.drive_mapping[selected_text]
            device = drive_info['primary_device']
            display_name = drive_info['display_name']
        else:
            # Fallback: extract device path from display text
            if '(' in selected_text and ')' in selected_text:
                device_start = selected_text.rfind('(') + 1
                device_end = selected_text.rfind(')')
                device = selected_text[device_start:device_end]
                display_name = selected_text[:device_start-1].strip()
            else:
                device = selected_text
                display_name = selected_text
        
        def rewind_thread():
            self.log_message(f"Rewinding tape in {display_name} ({device})")
            success, stdout, stderr = self.ltfs_manager.run_command(f"mt -f {device} rewind")
            
            if success:
                self.log_message(f"Tape rewound successfully in {display_name}")
                messagebox.showinfo("Success", f"Tape rewound in {display_name}")
            else:
                error_msg = stderr if stderr else "Unknown error occurred"
                self.log_message(f"Failed to rewind {display_name}: {error_msg}")
                messagebox.showerror("Error", f"Failed to rewind tape:\n{error_msg}")
        
        threading.Thread(target=rewind_thread, daemon=True).start()
    
    def browse_mount_point(self):
        """Browse for mount point directory"""
        directory = filedialog.askdirectory(initialdir=self.mount_point_var.get())
        if directory:
            self.mount_point_var.set(directory)
    
    def mount_tape(self):
        """Mount a tape like removable media"""
        device = self.get_selected_device(use_sg_device=True)
        mount_point = self.mount_point_var.get().strip()
        options = self.mount_options_var.get()
        auto_open = self.auto_open_var.get()
        
        if not device:
            messagebox.showerror("Error", "Please specify a device.")
            return
        
        # Auto-generate user-friendly mount point if not specified
        if not mount_point:
            mount_point = self.generate_mount_point(device)
            self.mount_point_var.set(mount_point)
        
        def mount_thread():
            mount_name = os.path.basename(mount_point)
            self.log_message(f"Mounting {device} as '{mount_name}'...")
            
            success, stdout, stderr = self.ltfs_manager.mount_tape(device, mount_point, options, auto_open)
            
            if success:
                self.log_message(f"Successfully mounted {device} as '{mount_name}' at {mount_point}")
                if mount_point.startswith('/media/'):
                    messagebox.showinfo("Tape Mounted", 
                                       f"'{mount_name}' is now available in your file manager\n\n"
                                       f"Location: {mount_point}\n\n"
                                       f"The tape appears like a USB drive or CD and will automatically " 
                                       f"open in your file manager.")
                else:
                    messagebox.showinfo("Tape Mounted", f"Tape mounted successfully at {mount_point}")
                self.root.after(0, self.refresh_mounted_list)
            else:
                error_msg = stderr if stderr else "Unknown error occurred"
                self.log_message(f"Failed to mount {device}: {error_msg}")
                
                # Provide helpful error messages
                if "medium consistency check failed" in error_msg.lower():
                    messagebox.showerror("Mount Failed - Tape Issue", 
                                       f"Cannot mount tape - the tape may be corrupted or needs repair.\n\n"
                                       f"Try running 'ltfsck' to check and repair the tape, or format " 
                                       f"the tape if it's blank.\n\n"
                                       f"Error: {error_msg}")
                else:
                    messagebox.showerror("Mount Failed", f"Failed to mount tape:\n\n{error_msg}")
        
        threading.Thread(target=mount_thread, daemon=True).start()
    
    def on_device_selected(self, event=None):
        """Auto-populate mount point when device is selected"""
        device_display = self.mount_device_var.get()
        if device_display and not self.mount_point_var.get().strip():
            # Get actual device path
            if hasattr(self, 'device_combo_mapping') and device_display in self.device_combo_mapping:
                device = self.device_combo_mapping[device_display]
            else:
                device = device_display
            
            # Auto-generate descriptive mount point
            mount_point = self.generate_mount_point(device)
            self.mount_point_var.set(mount_point)
            self.log_message(f"Auto-generated mount point: {mount_point}")
    
    def generate_mount_point(self, device):
        """Generate a user-friendly mount point - wrapper for LTFSManager method"""
        return self.ltfs_manager.generate_mount_point(device)
    
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
        barcode = self.mam_barcode_var.get().strip()
        force = self.force_format_var.get()
        block_size = self.block_size_var.get()
        compression = self.format_compression_var.get()
        
        # Convert display name to actual device path if needed
        if hasattr(self, 'device_combo_mapping') and device in self.device_combo_mapping:
            actual_device = self.device_combo_mapping[device]
        else:
            actual_device = device
        
        if not actual_device:
            messagebox.showerror("Error", "Please select a device to format.")
            return
        
        # Validate barcode if provided
        if barcode:
            if not re.match(r'^[A-Za-z0-9]{1,32}$', barcode):
                messagebox.showerror("Error", "Barcode must be alphanumeric and 1-32 characters long.")
                return
        
        # Confirmation dialog
        msg = f"Are you sure you want to format {device}?"
        if label:
            msg += f"\nTape will be labeled: {label}"
        if barcode:
            msg += f"\nMAM Barcode will be set to: {barcode}"
        if block_size != "auto":
            msg += f"\nBlock size: {block_size} bytes"
        msg += f"\nCompression: {'Enabled' if compression else 'Disabled'}"
        msg += "\n\n⚠️  This will PERMANENTLY erase all data on the tape!"
        
        if not messagebox.askyesno("Confirm Format", msg):
            return
        
        def format_thread():
            self.log_message(f"Formatting {actual_device} with LTFS...")
            if label:
                self.log_message(f"Label: {label}")
            if barcode:
                self.log_message(f"MAM Barcode: {barcode}")
            if block_size != "auto":
                self.log_message(f"Block size: {block_size} bytes")
            self.log_message(f"Compression: {'Enabled' if compression else 'Disabled'}")
            
            success, stdout, stderr = self.ltfs_manager.format_tape(
                actual_device, label, barcode, force, block_size, compression
            )
            
            if success:
                success_msg = f"Successfully formatted {actual_device}"
                if barcode:
                    success_msg += f" with MAM barcode: {barcode}"
                self.log_message(success_msg)
                messagebox.showinfo("Success", "Tape formatted successfully with LTFS")
            else:
                error_msg = stderr if stderr else "Unknown error occurred"
                self.log_message(f"Failed to format {actual_device}: {error_msg}")
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
    
    def detect_system_theme(self):
        """Detect system theme preference"""
        try:
            # Try to detect system dark mode preference
            import subprocess
            result = subprocess.run(['gsettings', 'get', 'org.gnome.desktop.interface', 'color-scheme'], 
                                  capture_output=True, text=True, timeout=5)
            if result.returncode == 0 and 'dark' in result.stdout.lower():
                return 'dark'
            
            # Alternative: check GTK theme name
            result = subprocess.run(['gsettings', 'get', 'org.gnome.desktop.interface', 'gtk-theme'], 
                                  capture_output=True, text=True, timeout=5)
            if result.returncode == 0 and ('dark' in result.stdout.lower() or 'mint-y-dark' in result.stdout.lower()):
                return 'dark'
        except:
            pass
        
        # Default to light theme
        return 'light'
    
    def detect_system_colors(self):
        """Detect system colors for system theme"""
        try:
            # Try to get system colors
            import subprocess
            
            # Get background color
            bg_result = subprocess.run(['gsettings', 'get', 'org.gnome.desktop.background', 'primary-color'], 
                                     capture_output=True, text=True, timeout=5)
            
            # For now, return a reasonable default based on detected theme
            if self.detect_system_theme() == 'dark':
                return {
                    'name': 'System Default',
                    'bg': '#2d2d2d',
                    'fg': '#eeeeee',
                    'select_bg': '#4a90e2',
                    'select_fg': '#ffffff',
                    'entry_bg': '#3d3d3d',
                    'entry_fg': '#eeeeee',
                    'frame_bg': '#2d2d2d',
                    'button_bg': '#454545',
                    'text_bg': '#1e1e1e',
                    'text_fg': '#eeeeee',
                    'notebook_bg': '#2d2d2d',
                    'tab_bg': '#454545',
                    'border_color': '#666666',
                    'warning_fg': '#ff7979',
                    'success_fg': '#00b894',
                    'info_fg': '#a29bfe'
                }
            else:
                return {
                    'name': 'System Default',
                    'bg': '#f5f5f5',
                    'fg': '#2d3748',
                    'select_bg': '#4a90e2',
                    'select_fg': '#ffffff',
                    'entry_bg': '#ffffff',
                    'entry_fg': '#2d3748',
                    'frame_bg': '#f5f5f5',
                    'button_bg': '#e2e8f0',
                    'text_bg': '#ffffff',
                    'text_fg': '#2d3748',
                    'notebook_bg': '#f5f5f5',
                    'tab_bg': '#e2e8f0',
                    'border_color': '#cbd5e0',
                    'warning_fg': '#e53e3e',
                    'success_fg': '#38a169',
                    'info_fg': '#718096'
                }
        except:
            # Fallback to light theme colors
            return self.themes['light'].copy()
    
    def setup_theme_controls(self):
        """Set up enhanced theme controls"""
        theme_frame = ttk.Frame(self.root)
        theme_frame.pack(side='bottom', fill='x', padx=10, pady=5)
        
        # Theme selection label
        ttk.Label(theme_frame, text="Theme:").pack(side='left', padx=(0, 10))
        
        # Theme dropdown
        theme_names = [info['name'] for info in self.themes.values()]
        self.theme_combo = ttk.Combobox(theme_frame, values=theme_names, 
                                       state="readonly", width=15)
        self.theme_combo.pack(side='left', padx=(0, 10))
        
        # Set current theme
        current_theme_info = self.themes[self.current_theme_name.get()]
        self.theme_combo.set(current_theme_info['name'])
        
        # Bind theme change
        self.theme_combo.bind('<<ComboboxSelected>>', self.on_theme_changed)
        
        # Legacy dark mode checkbox for backwards compatibility
        ttk.Checkbutton(theme_frame, text="Dark Mode (Legacy)", 
                       variable=self.dark_mode, 
                       command=self.toggle_theme).pack(side='right', padx=(20, 0))
        
        # Auto-detect system theme button
        ttk.Button(theme_frame, text="Auto-Detect", 
                  command=self.auto_detect_theme).pack(side='right', padx=(10, 0))
    
    def toggle_theme(self):
        """Toggle between dark and light themes"""
        self.apply_theme()
        self.log_message(f"Switched to {'dark' if self.dark_mode.get() else 'light'} mode")
    
    def apply_theme(self):
        """Apply the selected theme to all GUI elements (legacy method)"""
        # Use the new theme system instead
        self.apply_selected_theme()
    
    def update_themed_labels(self, theme):
        """Update special labels that need themed colors"""
        # Warning labels - use warning color
        warning_color = theme['warning_fg']
        
        # Update format warning label
        if hasattr(self, 'warning_label') and self.warning_label is not None:
            try:
                self.warning_label.configure(foreground=warning_color)
            except (tk.TclError, AttributeError):
                pass
        
        # Update MAM warning label
        if hasattr(self, 'mam_warning_label') and self.mam_warning_label is not None:
            try:
                self.mam_warning_label.configure(foreground=warning_color)
            except (tk.TclError, AttributeError):
                pass
        
        # Info labels - use info color
        info_color = theme['info_fg']
        
        # Update compression status labels
        if hasattr(self, 'compression_status_var'):
            # This is handled through ttk style
            pass
        
        # Update diagnostics status labels
        if hasattr(self, 'diagnostics_status_var'):
            # This is handled through ttk style
            pass
    
    def on_theme_changed(self, event=None):
        """Handle theme selection change from dropdown"""
        selected_theme_name = self.theme_combo.get()
        
        # Find the theme key by name
        theme_key = None
        for key, theme_info in self.themes.items():
            if theme_info['name'] == selected_theme_name:
                theme_key = key
                break
        
        if theme_key:
            self.current_theme_name.set(theme_key)
            
            # Update legacy dark_mode variable
            self.dark_mode.set(theme_key in ['dark', 'blue_dark', 'high_contrast'])
            
            # Apply the new theme
            self.apply_selected_theme()
            
            # Save theme preference
            self.save_theme_preference(theme_key)
            
            self.log_message(f"Theme changed to: {selected_theme_name}")
    
    def apply_selected_theme(self):
        """Apply the currently selected theme with proper scaling preservation"""
        theme_name = self.current_theme_name.get()
        theme = self.themes[theme_name]
        
        # Apply theme to root window
        self.root.configure(bg=theme['bg'])
        
        # Configure ttk style with balanced theming
        style = ttk.Style()
        
        # Use a ttk theme that supports full color overrides consistently.
        try:
            style.theme_use('clam')
        except:
            pass

        # Base defaults applied to ttk widgets.
        style.configure('.',
                       background=theme['bg'],
                       foreground=theme['fg'],
                       fieldbackground=theme['entry_bg'],
                       bordercolor=theme['border_color'],
                       lightcolor=theme['button_bg'],
                       darkcolor=theme['button_bg'])

        # Semantic text styles used throughout the UI.
        style.configure('Info.TLabel', background=theme['bg'], foreground=theme['info_fg'])
        style.configure('Status.TLabel', background=theme['bg'], foreground=theme['fg'])
        style.configure('Success.TLabel', background=theme['bg'], foreground=theme['success_fg'])
        style.configure('Warning.TLabel', background=theme['bg'], foreground=theme['warning_fg'])
        
        # Configure key ttk styles without breaking scaling
        
        # Notebook (tabs) - minimal styling to preserve appearance
        style.configure('TNotebook', 
                       background=theme['bg'])
        style.configure('TNotebook.Tab', 
                       background=theme['tab_bg'],
                       foreground=theme['fg'])
        style.map('TNotebook.Tab', 
                 background=[('selected', theme['tab_active']), ('active', theme['button_hover'])],
                 foreground=[('selected', theme['fg']), ('active', theme['fg'])])
        
        # Frames - minimal styling
        style.configure('TFrame', 
                       background=theme['bg'])
        style.configure('TLabelFrame', 
                       background=theme['bg'],
                       foreground=theme['fg'])
        style.configure('TLabelFrame.Label', 
                       background=theme['bg'],
                       foreground=theme['fg'])
        
        # Labels
        style.configure('TLabel', 
                       background=theme['bg'],
                       foreground=theme['fg'])
        
        # Buttons - preserve default styling but change colors
        style.configure('TButton', 
                       background=theme['button_bg'],
                       foreground=theme['fg'])
        style.map('TButton',
                 background=[('active', theme['button_hover']), ('disabled', theme['entry_bg'])],
                 foreground=[('disabled', theme['info_fg'])])
        
        # Entry fields and comboboxes - focus on background colors
        style.configure('TEntry', 
                       fieldbackground=theme['entry_bg'],
                       foreground=theme['entry_fg'],
                       insertcolor=theme['entry_fg'])
        style.map('TEntry',
                 fieldbackground=[('disabled', theme['text_bg']), ('readonly', theme['entry_bg'])],
                 foreground=[('disabled', theme['info_fg']), ('readonly', theme['entry_fg'])])
        
        style.configure('TCombobox', 
                       fieldbackground=theme['entry_bg'],
                       foreground=theme['entry_fg'],
                       background=theme['button_bg'],
                       arrowcolor=theme['fg'])
        style.map('TCombobox',
                 fieldbackground=[('readonly', theme['entry_bg']), ('disabled', theme['text_bg'])],
                 foreground=[('readonly', theme['entry_fg']), ('disabled', theme['info_fg'])],
                 selectbackground=[('readonly', theme['select_bg'])],
                 selectforeground=[('readonly', theme['select_fg'])])
        
        # Checkbuttons and radiobuttons
        style.configure('TCheckbutton', 
                       background=theme['bg'],
                       foreground=theme['fg'])
        style.map('TCheckbutton',
                 background=[('active', theme['bg'])],
                 foreground=[('disabled', theme['info_fg'])])
        
        style.configure('TRadiobutton', 
                       background=theme['bg'],
                       foreground=theme['fg'])
        style.map('TRadiobutton',
                 background=[('active', theme['bg'])],
                 foreground=[('disabled', theme['info_fg'])])
        
        style.configure('TSpinbox',
                       fieldbackground=theme['entry_bg'],
                       background=theme['button_bg'],
                       foreground=theme['entry_fg'],
                       arrowcolor=theme['fg'])
        style.map('TSpinbox',
                 fieldbackground=[('disabled', theme['text_bg']), ('readonly', theme['entry_bg'])],
                 foreground=[('disabled', theme['info_fg']), ('readonly', theme['entry_fg'])])

        # Ensure combobox dropdown list and menus use themed colors.
        self.root.option_add('*TCombobox*Listbox*Background', theme['entry_bg'])
        self.root.option_add('*TCombobox*Listbox*Foreground', theme['entry_fg'])
        self.root.option_add('*TCombobox*Listbox*selectBackground', theme['select_bg'])
        self.root.option_add('*TCombobox*Listbox*selectForeground', theme['select_fg'])
        self.root.option_add('*Menu*background', theme['bg'])
        self.root.option_add('*Menu*foreground', theme['fg'])
        self.root.option_add('*Menu*activeBackground', theme['select_bg'])
        self.root.option_add('*Menu*activeForeground', theme['select_fg'])
        self.root.option_add('*Listbox*Background', theme['text_bg'])
        self.root.option_add('*Listbox*Foreground', theme['text_fg'])
        self.root.option_add('*Listbox*selectBackground', theme['select_bg'])
        self.root.option_add('*Listbox*selectForeground', theme['select_fg'])
        self.root.option_add('*Text*Background', theme['text_bg'])
        self.root.option_add('*Text*Foreground', theme['text_fg'])
        self.root.option_add('*Text*insertBackground', theme['text_fg'])
        self.root.option_add('*Entry*Background', theme['entry_bg'])
        self.root.option_add('*Entry*Foreground', theme['entry_fg'])
        self.root.option_add('*Entry*insertBackground', theme['entry_fg'])
        
        # Apply theme to Tkinter widgets (listboxes, text widgets)
        listbox_config = {
            'bg': theme['text_bg'],
            'fg': theme['text_fg'],
            'selectbackground': theme['select_bg'],
            'selectforeground': theme['select_fg'],
            'disabledforeground': theme['info_fg']
        }
        text_widget_config = {
            'bg': theme['text_bg'],
            'fg': theme['text_fg'],
            'selectbackground': theme['select_bg'],
            'selectforeground': theme['select_fg'],
            'insertbackground': theme['text_fg']
        }
        
        # Update all listboxes
        listbox_widgets = []
        if hasattr(self, 'drives_listbox'):
            listbox_widgets.append(self.drives_listbox)
        if hasattr(self, 'mounted_listbox'):
            listbox_widgets.append(self.mounted_listbox)
            
        for widget in listbox_widgets:
            try:
                widget.configure(**listbox_config)
            except (tk.TclError, AttributeError):
                pass
        
        # Update all text widgets
        text_widgets = []
        if hasattr(self, 'drive_info_text'):
            text_widgets.append(self.drive_info_text)
        if hasattr(self, 'status_text'):
            text_widgets.append(self.status_text)
        if hasattr(self, 'diagnostics_results'):
            text_widgets.append(self.diagnostics_results)
        if hasattr(self, 'log_text'):
            text_widgets.append(self.log_text)
        if hasattr(self, 'mam_read_results'):
            text_widgets.append(self.mam_read_results)
        if hasattr(self, 'mam_write_results'):
            text_widgets.append(self.mam_write_results)
        if hasattr(self, 'mam_summary_text'):
            text_widgets.append(self.mam_summary_text)
        if hasattr(self, 'theme_info_text'):
            text_widgets.append(self.theme_info_text)
        
        for widget in text_widgets:
            try:
                widget.configure(**text_widget_config)
            except (tk.TclError, AttributeError):
                pass
        
        # Force theme application to all frames recursively
        def apply_theme_to_widget(widget, theme):
            """Recursively apply theme to widget and all its children"""
            try:
                widget_class = widget.winfo_class()
                
                # Apply theme based on widget type
                if widget_class in ['Frame', 'Toplevel']:
                    widget.configure(bg=theme['bg'])
                elif widget_class == 'Label':
                    widget.configure(bg=theme['bg'], fg=theme['fg'])
                elif widget_class == 'Text':
                    widget.configure(
                        bg=theme['text_bg'],
                        fg=theme['text_fg'],
                        selectbackground=theme['select_bg'],
                        selectforeground=theme['select_fg'],
                        insertbackground=theme['text_fg'],
                        disabledbackground=theme['text_bg'],
                        disabledforeground=theme['info_fg']
                    )
                elif widget_class == 'Listbox':
                    widget.configure(
                        bg=theme['text_bg'],
                        fg=theme['text_fg'],
                        selectbackground=theme['select_bg'],
                        selectforeground=theme['select_fg'],
                        disabledforeground=theme['info_fg']
                    )
                elif widget_class == 'Entry':
                    widget.configure(
                        bg=theme['entry_bg'],
                        fg=theme['entry_fg'],
                        selectbackground=theme['select_bg'],
                        selectforeground=theme['select_fg'],
                        insertbackground=theme['entry_fg'],
                        disabledbackground=theme['text_bg'],
                        disabledforeground=theme['info_fg']
                    )
                elif widget_class == 'Button':
                    widget.configure(
                        bg=theme['button_bg'],
                        fg=theme['fg'],
                        activebackground=theme['select_bg'],
                        activeforeground=theme['select_fg']
                    )
                elif widget_class in ['Checkbutton', 'Radiobutton']:
                    widget.configure(
                        bg=theme['bg'],
                        fg=theme['fg'],
                        selectcolor=theme['entry_bg'],
                        activebackground=theme['bg'],
                        activeforeground=theme['fg']
                    )
                elif widget_class == 'Scale':
                    widget.configure(
                        bg=theme['bg'],
                        fg=theme['fg'],
                        troughcolor=theme['entry_bg'],
                        activebackground=theme['select_bg']
                    )
                elif widget_class == 'Scrollbar':
                    widget.configure(
                        bg=theme['button_bg'],
                        troughcolor=theme['entry_bg'],
                        activebackground=theme['select_bg']
                    )
                elif widget_class == 'Canvas':
                    widget.configure(
                        bg=theme['bg'],
                        highlightbackground=theme['border_color'],
                        highlightcolor=theme['select_bg']
                    )
                elif widget_class == 'Menu':
                    widget.configure(
                        bg=theme['bg'],
                        fg=theme['fg'],
                        activebackground=theme['select_bg'],
                        activeforeground=theme['select_fg']
                    )
                elif widget_class == 'Menubutton':
                    widget.configure(
                        bg=theme['button_bg'],
                        fg=theme['fg'],
                        activebackground=theme['select_bg'],
                        activeforeground=theme['select_fg']
                    )
                elif widget_class == 'PanedWindow':
                    widget.configure(bg=theme['bg'])
                elif widget_class == 'LabelFrame':
                    widget.configure(bg=theme['bg'], fg=theme['fg'])
                elif widget_class == 'Spinbox':
                    widget.configure(
                        bg=theme['entry_bg'],
                        fg=theme['entry_fg'],
                        selectbackground=theme['select_bg'],
                        selectforeground=theme['select_fg'],
                        insertbackground=theme['entry_fg'],
                        buttonbackground=theme['button_bg']
                    )
                
                # Recursively apply to children
                for child in widget.winfo_children():
                    apply_theme_to_widget(child, theme)
                    
            except (tk.TclError, AttributeError):
                # Some widgets might not support all configurations
                pass
        
        # Apply theme to all widgets in the main window
        apply_theme_to_widget(self.root, theme)
        
        # Force update of all ttk styles for theme consistency
        self.force_ttk_theme_update(style, theme)
        
        # Update themed labels with appropriate colors
        self.update_themed_labels(theme)
        
        # Force refresh all widgets to apply theme immediately
        self.root.update_idletasks()
    
    def force_ttk_theme_update(self, style, theme):
        """Force update of all ttk widget styles for complete theme consistency"""
        try:
            # Update all possible ttk widget styles with theme colors
            
            # Additional ttk widget styles that might not be covered
            style.configure('Treeview', 
                           background=theme['text_bg'],
                           foreground=theme['text_fg'],
                           fieldbackground=theme['text_bg'])
            style.configure('Treeview.Heading',
                           background=theme['button_bg'],
                           foreground=theme['fg'])
            
            style.configure('Vertical.TScrollbar',
                           background=theme['button_bg'],
                           troughcolor=theme['entry_bg'],
                           bordercolor=theme['border_color'],
                           arrowcolor=theme['fg'],
                           darkcolor=theme['button_bg'],
                           lightcolor=theme['button_bg'])
            
            style.configure('Horizontal.TScrollbar',
                           background=theme['button_bg'],
                           troughcolor=theme['entry_bg'],
                           bordercolor=theme['border_color'],
                           arrowcolor=theme['fg'],
                           darkcolor=theme['button_bg'],
                           lightcolor=theme['button_bg'])
            
            # Update progressbar if needed
            style.configure('TProgressbar',
                           background=theme['select_bg'],
                           troughcolor=theme['entry_bg'],
                           bordercolor=theme['border_color'])
            
            # Update separator
            style.configure('TSeparator',
                           background=theme['border_color'])
            
            # Update scale
            style.configure('TScale',
                           background=theme['bg'],
                           troughcolor=theme['entry_bg'],
                           bordercolor=theme['border_color'])
            
            # Update spinbox
            style.configure('TSpinbox',
                           fieldbackground=theme['entry_bg'],
                           background=theme['button_bg'],
                           foreground=theme['entry_fg'],
                           bordercolor=theme['select_bg'])
            
            # Update sizegrip
            style.configure('TSizegrip',
                           background=theme['bg'])
            
            # Update panedwindow
            style.configure('TPanedwindow',
                           background=theme['bg'])
            
            # Force theme refresh
            self.root.update()
            
        except Exception as e:
            # If any style configuration fails, continue anyway
            pass
    
    def auto_detect_theme(self):
        """Auto-detect and apply system theme"""
        detected_theme = self.detect_system_theme()
        
        # Update system theme colors
        self.themes['system'].update(self.detect_system_colors())
        
        # Set to system theme
        self.current_theme_name.set('system')
        
        # Update combo box
        self.theme_combo.set(self.themes['system']['name'])
        
        # Update legacy dark mode
        self.dark_mode.set(detected_theme == 'dark')
        
        # Apply theme
        self.apply_selected_theme()
        
        # Save preference
        self.save_theme_preference('system')
        
        self.log_message(f"Auto-detected system theme: {detected_theme} (applied as System Default)")
        messagebox.showinfo("Theme Auto-Detection", 
                          f"Detected and applied system theme: {detected_theme}\n\n"
                          f"Theme has been set to 'System Default'")
    
    def save_theme_preference(self, theme_name):
        """Save theme preference to config file"""
        try:
            config_dir = os.path.expanduser('~/.config/ltfs-gui')
            os.makedirs(config_dir, exist_ok=True)
            
            config_file = os.path.join(config_dir, 'theme.conf')
            with open(config_file, 'w') as f:
                f.write(f"theme={theme_name}\n")
        except Exception as e:
            # Don't show error to user, just log it
            pass
    
    def load_theme_preference(self):
        """Load saved theme preference"""
        try:
            config_file = os.path.expanduser('~/.config/ltfs-gui/theme.conf')
            if os.path.exists(config_file):
                with open(config_file, 'r') as f:
                    for line in f:
                        if line.strip().startswith('theme='):
                            theme_name = line.strip().split('=', 1)[1]
                            if theme_name in self.themes:
                                return theme_name
        except Exception:
            pass
        
        # Return default
        return self.detect_system_theme()
    
    def setup_theme_control_tab(self):
        """Set up the comprehensive theme control tab"""
        # Main theme control section
        theme_section = ttk.LabelFrame(self.theme_control_frame, text="Theme Settings", padding=20)
        theme_section.pack(fill='both', expand=True, padx=20, pady=20)
        
        # Introduction text
        intro_text = (
            "Customize the LTFS GUI appearance. "
            "Themes control colors, contrast, and style across the entire interface."
        )
        intro_label = ttk.Label(theme_section, text=intro_text, wraplength=700, justify='left')
        intro_label.pack(anchor='w', pady=(0, 20))
        
        # Current theme display
        current_frame = ttk.LabelFrame(theme_section, text="Current Theme", padding=15)
        current_frame.pack(fill='x', pady=(0, 20))
        
        current_info_frame = ttk.Frame(current_frame)
        current_info_frame.pack(fill='x')
        
        ttk.Label(current_info_frame, text="Current Theme:").pack(side='left', padx=(0, 10))
        self.current_theme_display = ttk.Label(current_info_frame, text="", font=('Arial', 10, 'bold'))
        self.current_theme_display.pack(side='left')
        
        # Theme selection area
        selection_frame = ttk.LabelFrame(theme_section, text="Available Themes", padding=15)
        selection_frame.pack(fill='both', expand=True, pady=(10, 0))
        
        # Create notebook for theme categories
        theme_notebook = ttk.Notebook(selection_frame)
        theme_notebook.pack(fill='both', expand=True)
        
        # Theme options frame
        options_frame = ttk.Frame(theme_notebook)
        theme_notebook.add(options_frame, text="Select Theme")
        
        # Theme preview frame
        preview_frame = ttk.Frame(theme_notebook)
        theme_notebook.add(preview_frame, text="Preview")
        
        # Advanced settings frame
        advanced_frame = ttk.Frame(theme_notebook)
        theme_notebook.add(advanced_frame, text="Advanced Settings")
        
        # Color picker frame
        color_picker_frame = ttk.Frame(theme_notebook)
        theme_notebook.add(color_picker_frame, text="Custom Colors")
        
        # Set up theme selection
        self.setup_theme_selection(options_frame)
        
        # Set up theme preview
        self.setup_theme_preview(preview_frame)
        
        # Set up advanced theme settings
        self.setup_advanced_theme_settings(advanced_frame)
        
        # Set up color picker
        self.setup_color_picker(color_picker_frame)
        
        # Update current theme display
        self.update_current_theme_display()
    
    def setup_theme_selection(self, parent):
        """Set up the theme selection interface"""
        # Theme categories
        categories_frame = ttk.Frame(parent)
        categories_frame.pack(fill='both', expand=True, padx=10, pady=10)
        
        # Left column - Theme list
        left_col = ttk.Frame(categories_frame)
        left_col.pack(side='left', fill='both', expand=True, padx=(0, 10))
        
        ttk.Label(left_col, text="Available Themes:", font=('Arial', 12, 'bold')).pack(anchor='w', pady=(0, 10))
        
        theme_list_container = ttk.Frame(left_col)
        theme_list_container.pack(fill='both', expand=True)
        
        theme_list_canvas = tk.Canvas(theme_list_container, highlightthickness=0, borderwidth=0)
        theme_list_scrollbar = ttk.Scrollbar(theme_list_container, orient='vertical', command=theme_list_canvas.yview)
        theme_list_scrollable = ttk.Frame(theme_list_canvas)
        
        def _update_theme_list_scrollregion(event):
            theme_list_canvas.configure(scrollregion=theme_list_canvas.bbox("all"))
        
        theme_list_scrollable.bind("<Configure>", _update_theme_list_scrollregion)
        theme_list_window = theme_list_canvas.create_window((0, 0), window=theme_list_scrollable, anchor="nw")
        
        def _resize_theme_list_window(event):
            theme_list_canvas.itemconfigure(theme_list_window, width=event.width)
        
        theme_list_canvas.bind("<Configure>", _resize_theme_list_window)
        theme_list_canvas.configure(yscrollcommand=theme_list_scrollbar.set)
        
        theme_list_canvas.pack(side='left', fill='both', expand=True)
        theme_list_scrollbar.pack(side='right', fill='y')
        
        # Theme selection variable
        self.theme_selection_var = tk.StringVar(value=self.current_theme_name.get())
        
        # Create theme options with descriptions
        self.theme_details = {
            'light': {
                'title': 'Light (Linux Mint)',
                'description': 'Clean, bright theme based on Linux Mint\'s light palette.',
                'best_for': 'General use, bright spaces, accessibility'
            },
            'dark': {
                'title': 'Dark (Linux Mint)',
                'description': 'Dark theme using Linux Mint dark colors to reduce glare and eye strain.',
                'best_for': 'Low-light use, long sessions, reduced glare'
            },
            'blue_dark': {
                'title': 'Blue Dark',
                'description': 'Dark theme with blue accents and strong contrast.',
                'best_for': 'Technical work, coding, high readability'
            },
            'high_contrast': {
                'title': 'High Contrast',
                'description': 'Maximum-contrast theme for accessibility needs.',
                'best_for': 'Visual accessibility and clarity'
            },
            'system': {
                'title': 'System Default',
                'description': 'Follows your system theme settings when detected.',
                'best_for': 'Keeping app and desktop appearance aligned'
            }
        }
        
        # Create radio buttons for themes
        for theme_key, theme_info in self.theme_details.items():
            theme_frame = ttk.Frame(theme_list_scrollable)
            theme_frame.pack(fill='x', pady=5)
            
            # Radio button
            radio = ttk.Radiobutton(theme_frame, text=theme_info['title'], 
                                  variable=self.theme_selection_var, value=theme_key,
                                  command=self.on_theme_selection_change)
            radio.pack(anchor='w')
            
            # Description
            desc_frame = ttk.Frame(theme_frame)
            desc_frame.pack(fill='x', padx=20, pady=(2, 0))
            
            desc_label = ttk.Label(desc_frame, text=theme_info['description'], 
                                 wraplength=400, justify='left', font=('Arial', 9))
            desc_label.pack(anchor='w')
            
            # Best for info
            best_label = ttk.Label(desc_frame, text=f"Best for: {theme_info['best_for']}", 
                                 font=('Arial', 8, 'italic'), style='Info.TLabel')
            best_label.pack(anchor='w', pady=(2, 10))
        
        # Right column - Theme actions
        right_col = ttk.Frame(categories_frame)
        right_col.pack(side='right', fill='y', padx=(10, 0))
        
        ttk.Label(right_col, text="Actions:", font=('Arial', 12, 'bold')).pack(anchor='w', pady=(0, 10))
        
        # Action buttons
        ttk.Button(right_col, text="Apply Theme", 
                  command=self.apply_selected_theme_from_tab).pack(fill='x', pady=2)
        ttk.Button(right_col, text="Preview Selected Theme", 
                  command=self.preview_selected_theme).pack(fill='x', pady=2)
        ttk.Button(right_col, text="Use System Theme", 
                  command=self.auto_detect_theme).pack(fill='x', pady=2)
        ttk.Button(right_col, text="Reset Theme", 
                  command=self.reset_to_default_theme).pack(fill='x', pady=2)
        
        # Separator
        ttk.Separator(right_col, orient='horizontal').pack(fill='x', pady=10)
        
        # Theme management
        ttk.Label(right_col, text="Import / Export:", font=('Arial', 10, 'bold')).pack(anchor='w', pady=(0, 5))
        ttk.Button(right_col, text="Export Theme", 
                  command=self.export_theme_settings).pack(fill='x', pady=2)
        ttk.Button(right_col, text="Import Theme", 
                  command=self.import_theme_settings).pack(fill='x', pady=2)
    
    def setup_theme_preview(self, parent):
        """Set up the theme preview interface"""
        preview_main = ttk.Frame(parent)
        preview_main.pack(fill='both', expand=True, padx=10, pady=10)
        
        ttk.Label(preview_main, text="Theme Preview", font=('Arial', 14, 'bold')).pack(anchor='w', pady=(0, 15))
        
        # Create preview area
        preview_area = ttk.LabelFrame(preview_main, text="Preview Area", padding=15)
        preview_area.pack(fill='both', expand=True)
        
        # Sample UI elements for preview
        sample_frame = ttk.Frame(preview_area)
        sample_frame.pack(fill='both', expand=True)
        
        # Sample notebook
        sample_notebook = ttk.Notebook(sample_frame)
        sample_notebook.pack(fill='both', expand=True, pady=(0, 10))
        
        # Sample tab 1
        tab1 = ttk.Frame(sample_notebook)
        sample_notebook.add(tab1, text="Sample Tab")
        
        # Sample elements in tab 1
        ttk.Label(tab1, text="Sample Label").pack(anchor='w', pady=5)
        
        entry_frame = ttk.Frame(tab1)
        entry_frame.pack(fill='x', pady=5)
        ttk.Label(entry_frame, text="Input:").pack(side='left')
        sample_entry = ttk.Entry(entry_frame, width=30)
        sample_entry.pack(side='left', padx=(10, 0))
        sample_entry.insert(0, "Sample text")
        
        button_frame = ttk.Frame(tab1)
        button_frame.pack(fill='x', pady=10)
        ttk.Button(
            button_frame,
            text="Sample Button",
            command=self.on_theme_preview_sample_button
        ).pack(side='left', padx=(0, 10))
        
        # Sample checkbox
        sample_check = tk.BooleanVar(value=True)
        ttk.Checkbutton(button_frame, text="Sample Checkbox", variable=sample_check).pack(side='left')
        
        # Sample listbox
        list_frame = ttk.LabelFrame(tab1, text="Sample List", padding=10)
        list_frame.pack(fill='both', expand=True, pady=(10, 0))
        
        sample_listbox = tk.Listbox(list_frame, height=6)
        sample_listbox.pack(fill='both', expand=True)
        for i in range(5):
            sample_listbox.insert(tk.END, f"Sample Item {i+1}")
        
        # Sample tab 2
        tab2 = ttk.Frame(sample_notebook)
        sample_notebook.add(tab2, text="Text Preview")
        
        # Sample text widget
        sample_text = tk.Text(tab2, height=10, wrap='word')
        sample_text.pack(fill='both', expand=True, padx=10, pady=10)
        sample_text.insert('1.0', 
            "This is a sample text area showing how text will appear in the selected theme. "
            "You can see the background color, text color, and selection colors here. "
            "\n\nThis helps you preview how the theme will look across different interface elements "
            "before applying it to the entire application.")
        
        # Store preview elements for theme updates
        self.preview_elements = {
            'notebook': sample_notebook,
            'entry': sample_entry,
            'listbox': sample_listbox,
            'text': sample_text,
            'frames': [sample_frame, tab1, tab2, entry_frame, button_frame]
        }
    
    def on_theme_preview_sample_button(self):
        """Handle clicks for non-functional preview/sample buttons."""
        self.log_message("Theme preview sample button clicked")
    
    def setup_advanced_theme_settings(self, parent):
        """Set up advanced theme settings"""
        advanced_main = ttk.Frame(parent)
        advanced_main.pack(fill='both', expand=True, padx=10, pady=10)
        
        ttk.Label(advanced_main, text="Advanced Theme Settings", font=('Arial', 14, 'bold')).pack(anchor='w', pady=(0, 15))
        
        # Theme persistence settings
        persistence_frame = ttk.LabelFrame(advanced_main, text="Saving & Startup", padding=10)
        persistence_frame.pack(fill='x', pady=(0, 10))
        
        self.auto_save_theme_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(persistence_frame, text="Automatically save theme changes", 
                       variable=self.auto_save_theme_var).pack(anchor='w')
        
        self.auto_detect_startup_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(persistence_frame, text="Detect system theme on startup", 
                       variable=self.auto_detect_startup_var).pack(anchor='w')
        
        # System integration
        integration_frame = ttk.LabelFrame(advanced_main, text="System Integration", padding=10)
        integration_frame.pack(fill='x', pady=(0, 10))
        
        ttk.Button(integration_frame, text="Apply Theme to System (GTK)", 
                  command=self.apply_theme_to_system).pack(anchor='w', pady=2)
        ttk.Button(integration_frame, text="Detect Current System Theme", 
                  command=self.detect_and_show_system_theme).pack(anchor='w', pady=2)
        
        # Theme information
        info_frame = ttk.LabelFrame(advanced_main, text="Theme Details", padding=10)
        info_frame.pack(fill='both', expand=True, pady=(0, 10))
        
        self.theme_info_text = scrolledtext.ScrolledText(info_frame, height=10, wrap='word')
        self.theme_info_text.pack(fill='both', expand=True)
        
        # Update theme info
        self.update_theme_info()
        
        # Actions
        actions_frame = ttk.Frame(advanced_main)
        actions_frame.pack(fill='x')
        
        ttk.Button(actions_frame, text="Refresh Details", 
                  command=self.update_theme_info).pack(side='left', padx=(0, 10))
        ttk.Button(actions_frame, text="Clear Saved Theme", 
                  command=self.clear_theme_config).pack(side='left')
    
    def update_current_theme_display(self):
        """Update the current theme display"""
        current_theme = self.current_theme_name.get()
        theme_info = self.themes.get(current_theme, {})
        theme_name = theme_info.get('name', current_theme)
        
        if hasattr(self, 'current_theme_display'):
            self.current_theme_display.config(text=theme_name)
    
    def on_theme_selection_change(self):
        """Handle theme selection change in the theme tab"""
        selected_theme = self.theme_selection_var.get()
        if hasattr(self, 'preview_elements'):
            self.update_preview_theme(selected_theme)
    
    def update_preview_theme(self, theme_name):
        """Update the preview area with the selected theme"""
        if theme_name not in self.themes:
            return
            
        theme = self.themes[theme_name]
        
        # Update preview elements
        widget_config = {
            'bg': theme['text_bg'],
            'fg': theme['text_fg'],
            'selectbackground': theme['select_bg'],
            'selectforeground': theme['select_fg'],
            'insertbackground': theme['text_fg']
        }
        
        # Update listbox
        try:
            self.preview_elements['listbox'].configure(**widget_config)
        except:
            pass
        
        # Update text widget
        try:
            self.preview_elements['text'].configure(**widget_config)
        except:
            pass
        
        # Update entry
        try:
            self.preview_elements['entry'].configure(
                bg=theme['entry_bg'],
                fg=theme['entry_fg'],
                selectbackground=theme['select_bg'],
                selectforeground=theme['select_fg'],
                insertbackground=theme['entry_fg']
            )
        except:
            pass
    
    def apply_selected_theme_from_tab(self):
        """Apply the selected theme from the theme tab"""
        selected_theme = self.theme_selection_var.get()
        
        # Update current theme
        self.current_theme_name.set(selected_theme)
        
        # Update legacy dark mode
        self.dark_mode.set(selected_theme in ['dark', 'blue_dark', 'high_contrast'])
        
        # Apply theme
        self.apply_selected_theme()
        
        # Update displays
        self.update_current_theme_display()
        
        # Update dropdown in bottom bar
        if hasattr(self, 'theme_combo'):
            theme_info = self.themes[selected_theme]
            self.theme_combo.set(theme_info['name'])
        
        # Save preference if auto-save is enabled
        if getattr(self, 'auto_save_theme_var', tk.BooleanVar(value=True)).get():
            self.save_theme_preference(selected_theme)
        
        self.log_message(f"Applied theme: {self.themes[selected_theme]['name']}")
        messagebox.showinfo("Theme Applied", f"Successfully applied theme: {self.themes[selected_theme]['name']}")
    
    def preview_selected_theme(self):
        """Preview the selected theme temporarily"""
        selected_theme = self.theme_selection_var.get()
        
        if messagebox.askyesno("Preview Theme", 
                             f"Preview theme '{self.themes[selected_theme]['name']}'?\n\n"
                             "This will temporarily apply the theme. You can revert using 'Reset Theme'."):
            # Store current theme for reverting
            self.previous_theme = self.current_theme_name.get()
            
            # Apply preview theme
            self.current_theme_name.set(selected_theme)
            self.apply_selected_theme()
            self.update_current_theme_display()
            
            self.log_message(f"Previewing theme: {self.themes[selected_theme]['name']}")
    
    def reset_to_default_theme(self):
        """Reset to default theme"""
        if hasattr(self, 'previous_theme') and self.previous_theme:
            # Revert to previous theme if we were previewing
            self.current_theme_name.set(self.previous_theme)
            self.theme_selection_var.set(self.previous_theme)
            self.previous_theme = None
        else:
            # Reset to system default
            detected_theme = self.detect_system_theme()
            self.current_theme_name.set(detected_theme)
            self.theme_selection_var.set(detected_theme)
        
        self.apply_selected_theme()
        self.update_current_theme_display()
        self.log_message("Reset to default theme")
    
    def export_theme_settings(self):
        """Export current theme settings to file"""
        filename = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            title="Export Theme Settings"
        )
        
        if filename:
            try:
                import json
                theme_settings = {
                    'current_theme': self.current_theme_name.get(),
                    'auto_save': getattr(self, 'auto_save_theme_var', tk.BooleanVar(value=True)).get(),
                    'auto_detect_startup': getattr(self, 'auto_detect_startup_var', tk.BooleanVar(value=False)).get(),
                    'timestamp': time.strftime("%Y-%m-%d %H:%M:%S"),
                    'themes': self.themes
                }
                
                with open(filename, 'w') as f:
                    json.dump(theme_settings, f, indent=2)
                
                messagebox.showinfo("Success", f"Theme settings exported to {filename}")
                self.log_message(f"Theme settings exported to {filename}")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to export theme settings: {str(e)}")
    
    def import_theme_settings(self):
        """Import theme settings from file"""
        filename = filedialog.askopenfilename(
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            title="Import Theme Settings"
        )
        
        if filename:
            try:
                import json
                with open(filename, 'r') as f:
                    theme_settings = json.load(f)
                
                # Apply imported settings
                if 'current_theme' in theme_settings:
                    imported_theme = theme_settings['current_theme']
                    if imported_theme in self.themes:
                        self.current_theme_name.set(imported_theme)
                        self.theme_selection_var.set(imported_theme)
                        self.apply_selected_theme()
                        self.update_current_theme_display()
                
                messagebox.showinfo("Success", f"Theme settings imported from {filename}")
                self.log_message(f"Theme settings imported from {filename}")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to import theme settings: {str(e)}")
    
    def apply_theme_to_system(self):
        """Apply current theme to system GTK settings"""
        current_theme = self.current_theme_name.get()
        
        if messagebox.askyesno("Apply to System", 
                             f"Apply current theme '{self.themes[current_theme]['name']}' to system GTK settings?\n\n"
                             "This will change your system-wide theme."):
            try:
                if current_theme == 'dark':
                    # Apply dark theme to system
                    subprocess.run(['gsettings', 'set', 'org.gnome.desktop.interface', 'color-scheme', 'prefer-dark'])
                    subprocess.run(['gsettings', 'set', 'org.cinnamon.desktop.interface', 'gtk-theme', 'Mint-Y-Dark-Aqua'])
                else:
                    # Apply light theme to system
                    subprocess.run(['gsettings', 'set', 'org.gnome.desktop.interface', 'color-scheme', 'prefer-light'])
                    subprocess.run(['gsettings', 'set', 'org.cinnamon.desktop.interface', 'gtk-theme', 'Mint-Y-Aqua'])
                
                messagebox.showinfo("Success", "Theme applied to system GTK settings")
                self.log_message("Applied theme to system GTK settings")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to apply theme to system: {str(e)}")
    
    def detect_and_show_system_theme(self):
        """Detect and show current system theme"""
        detected_theme = self.detect_system_theme()
        system_colors = self.detect_system_colors()
        
        info = f"Detected System Theme: {detected_theme}\n\n"
        info += "System Colors:\n"
        for key, value in system_colors.items():
            if key != 'name':
                info += f"  {key}: {value}\n"
        
        messagebox.showinfo("System Theme Detection", info)
        self.log_message(f"Detected system theme: {detected_theme}")
    
    def update_theme_info(self):
        """Update the theme information display"""
        if not hasattr(self, 'theme_info_text'):
            return
        
        current_theme = self.current_theme_name.get()
        theme = self.themes.get(current_theme, {})
        
        info = f"Current Theme: {theme.get('name', current_theme)}\n"
        info += f"Theme Key: {current_theme}\n\n"
        
        info += "Theme Colors:\n"
        for key, value in theme.items():
            if key != 'name':
                info += f"  {key}: {value}\n"
        
        info += "\n" + "="*50 + "\n"
        info += "All Available Themes:\n\n"
        
        for theme_key, theme_info in self.themes.items():
            info += f"{theme_key}: {theme_info.get('name', theme_key)}\n"
        
        info += "\n" + "="*50 + "\n"
        info += "Theme Configuration:\n"
        info += f"Auto-save: {getattr(self, 'auto_save_theme_var', tk.BooleanVar(value=True)).get()}\n"
        info += f"Auto-detect on startup: {getattr(self, 'auto_detect_startup_var', tk.BooleanVar(value=False)).get()}\n"
        
        config_file = os.path.expanduser('~/.config/ltfs-gui/theme.conf')
        info += f"Config file: {config_file}\n"
        info += f"Config exists: {os.path.exists(config_file)}\n"
        
        self.theme_info_text.delete(1.0, tk.END)
        self.theme_info_text.insert(1.0, info)
    
    def clear_theme_config(self):
        """Clear saved theme configuration"""
        if messagebox.askyesno("Clear Configuration", 
                             "Clear saved theme configuration?\n\n"
                             "This will remove your saved theme preferences."):
            try:
                config_file = os.path.expanduser('~/.config/ltfs-gui/theme.conf')
                if os.path.exists(config_file):
                    os.remove(config_file)
                    messagebox.showinfo("Success", "Theme configuration cleared")
                    self.log_message("Cleared theme configuration")
                else:
                    messagebox.showinfo("Info", "No theme configuration file found")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to clear theme configuration: {str(e)}")
    
    def setup_mam_tab(self):
        """Set up the MAM (Medium Auxiliary Memory) tab"""
        # Main MAM section
        mam_section = ttk.LabelFrame(self.mam_frame, text="Medium Auxiliary Memory (MAM) Operations", padding=20)
        mam_section.pack(fill='both', expand=True, padx=20, pady=20)
        
        # Introduction text
        intro_text = (
            "MAM (Medium Auxiliary Memory) allows reading and writing metadata attributes directly "
            "to the tape cartridge. This includes information like tape capacity, usage statistics, "
            "cartridge history, and custom attributes."
        )
        intro_label = ttk.Label(mam_section, text=intro_text, wraplength=700, justify='left')
        intro_label.pack(anchor='w', pady=(0, 20))
        
        # Device selection for MAM
        device_frame = ttk.Frame(mam_section)
        device_frame.pack(fill='x', pady=(0, 20))
        
        ttk.Label(device_frame, text="Select Device:").pack(side='left', padx=(0, 10))
        self.mam_device_var = tk.StringVar()
        self.mam_device_combo = ttk.Combobox(device_frame, textvariable=self.mam_device_var, 
                                           width=40, state="readonly")
        self.mam_device_combo.pack(side='left', fill='x', expand=True)
        
        # Create main content area with notebook for different MAM operations
        mam_notebook = ttk.Notebook(mam_section)
        mam_notebook.pack(fill='both', expand=True, pady=(10, 0))
        
        # Read MAM tab
        self.mam_read_frame = ttk.Frame(mam_notebook)
        mam_notebook.add(self.mam_read_frame, text="Read MAM")
        self.setup_mam_read_tab()
        
        # Write MAM tab
        self.mam_write_frame = ttk.Frame(mam_notebook)
        mam_notebook.add(self.mam_write_frame, text="Write MAM")
        self.setup_mam_write_tab()
        
        # MAM Info tab
        self.mam_info_frame = ttk.Frame(mam_notebook)
        mam_notebook.add(self.mam_info_frame, text="MAM Info")
        self.setup_mam_info_tab()
        
        # Bind device selection
        self.mam_device_combo.bind('<<ComboboxSelected>>', self.on_mam_device_change)
    
    def setup_mam_read_tab(self):
        """Set up the MAM read operations tab"""
        # MAM attribute selection
        attr_frame = ttk.LabelFrame(self.mam_read_frame, text="Select MAM Attributes to Read", padding=10)
        attr_frame.pack(fill='x', padx=10, pady=10)
        
        # Common MAM attributes
        self.mam_attributes = {
            '0x0000': 'Remaining Capacity in Partition',
            '0x0001': 'Maximum Capacity in Partition',
            '0x0002': 'TapeAlert Flags',
            '0x0003': 'Load Count',
            '0x0004': 'MAM Space Remaining',
            '0x0005': 'Assigning Organization',
            '0x0006': 'Formatted Density Code',
            '0x0007': 'Initialization Count',
            '0x0008': 'Volume Identifier',
            '0x0009': 'Volume Change Reference',
            '0x020A': 'Device Vendor/Serial at Last Load',
            '0x020B': 'Device Vendor/Serial at Load-1',
            '0x020C': 'Device Vendor/Serial at Load-2',
            '0x020D': 'Device Vendor/Serial at Load-3',
            '0x0220': 'Total MB Written in Medium Life',
            '0x0221': 'Total MB Read in Medium Life',
            '0x0222': 'Total MB Written in Current/Last Load',
            '0x0223': 'Total MB Read in Current/Last Load',
            '0x0224': 'Logical Position of First Encrypted Block',
            '0x0225': 'Logical Position of First Unencrypted Block'
        }
        
        # Create checkboxes for attributes
        self.mam_attr_vars = {}
        
        # Split into two columns
        left_col = ttk.Frame(attr_frame)
        left_col.pack(side='left', fill='both', expand=True, padx=(0, 10))
        
        right_col = ttk.Frame(attr_frame)
        right_col.pack(side='right', fill='both', expand=True, padx=(10, 0))
        
        attr_items = list(self.mam_attributes.items())
        mid_point = len(attr_items) // 2
        
        # Left column attributes
        for attr_code, attr_desc in attr_items[:mid_point]:
            var = tk.BooleanVar()
            self.mam_attr_vars[attr_code] = var
            cb = ttk.Checkbutton(left_col, text=f"{attr_code}: {attr_desc}", variable=var)
            cb.pack(anchor='w', pady=2)
        
        # Right column attributes
        for attr_code, attr_desc in attr_items[mid_point:]:
            var = tk.BooleanVar()
            self.mam_attr_vars[attr_code] = var
            cb = ttk.Checkbutton(right_col, text=f"{attr_code}: {attr_desc}", variable=var)
            cb.pack(anchor='w', pady=2)
        
        # Control buttons
        button_frame = ttk.Frame(self.mam_read_frame)
        button_frame.pack(fill='x', padx=10, pady=10)
        
        ttk.Button(button_frame, text="Select All", command=self.select_all_mam_attrs).pack(side='left', padx=(0, 10))
        ttk.Button(button_frame, text="Select None", command=self.select_no_mam_attrs).pack(side='left', padx=(0, 10))
        ttk.Button(button_frame, text="Select Common", command=self.select_common_mam_attrs).pack(side='left', padx=(0, 10))
        ttk.Button(button_frame, text="Read Selected MAM", command=self.read_mam_attributes).pack(side='right')
        
        # Results display
        results_frame = ttk.LabelFrame(self.mam_read_frame, text="MAM Read Results", padding=10)
        results_frame.pack(fill='both', expand=True, padx=10, pady=10)
        
        self.mam_read_results = scrolledtext.ScrolledText(results_frame, height=15, wrap='word')
        self.mam_read_results.pack(fill='both', expand=True)
        
        # Save/Export buttons
        save_frame = ttk.Frame(self.mam_read_frame)
        save_frame.pack(fill='x', padx=10, pady=5)
        
        ttk.Button(save_frame, text="Clear Results", command=self.clear_mam_read_results).pack(side='left', padx=(0, 10))
        ttk.Button(save_frame, text="Save Results", command=self.save_mam_read_results).pack(side='left', padx=(0, 10))
        ttk.Button(save_frame, text="Export MAM Report", command=self.export_mam_report).pack(side='left')
    
    def setup_mam_write_tab(self):
        """Set up the MAM write operations tab"""
        # Warning
        warning_frame = ttk.Frame(self.mam_write_frame)
        warning_frame.pack(fill='x', padx=10, pady=10)
        
        warning_label = ttk.Label(warning_frame, text="⚠️  WARNING: Writing MAM attributes can affect tape behavior. Use with caution!", 
                                style='Warning.TLabel', font=('Arial', 10, 'bold'))
        warning_label.pack()
        
        # Writable attributes
        write_frame = ttk.LabelFrame(self.mam_write_frame, text="Write MAM Attributes", padding=10)
        write_frame.pack(fill='both', expand=True, padx=10, pady=10)
        
        # Common writable attributes
        self.writable_mam_attrs = {
            '0x0005': 'Assigning Organization',
            '0x0008': 'Volume Identifier',
            '0x0009': 'Volume Change Reference',
            '0x0400': 'Medium Manufacturer',
            '0x0401': 'Medium Serial Number',
            '0x0402': 'Medium Length',
            '0x0403': 'Medium Width',
            '0x0404': 'Assigning Organization',
            '0x0800': 'Application Vendor',
            '0x0801': 'Application Name',
            '0x0802': 'Application Version',
            '0x0803': 'User Medium Text Label',
            '0x0804': 'Date and Time Last Written',
            '0x0805': 'Text Localization Identifier',
            '0x0806': 'Barcode',
            '0x0807': 'Owning Host Textual Name',
            '0x0808': 'Media Pool'
        }
        
        # Attribute selection for writing
        ttk.Label(write_frame, text="Select Attribute to Write:").grid(row=0, column=0, sticky='w', pady=5)
        self.mam_write_attr_var = tk.StringVar()
        self.mam_write_attr_combo = ttk.Combobox(write_frame, textvariable=self.mam_write_attr_var, 
                                               values=[f"{code}: {desc}" for code, desc in self.writable_mam_attrs.items()],
                                               width=50, state="readonly")
        self.mam_write_attr_combo.grid(row=0, column=1, sticky='ew', padx=(10, 0), pady=5)
        
        # Value input
        ttk.Label(write_frame, text="Value:").grid(row=1, column=0, sticky='w', pady=5)
        self.mam_write_value_var = tk.StringVar()
        self.mam_write_value_entry = ttk.Entry(write_frame, textvariable=self.mam_write_value_var, width=50)
        self.mam_write_value_entry.grid(row=1, column=1, sticky='ew', padx=(10, 0), pady=5)
        
        # Data format selection
        ttk.Label(write_frame, text="Data Format:").grid(row=2, column=0, sticky='w', pady=5)
        self.mam_write_format_var = tk.StringVar(value="ascii")
        format_frame = ttk.Frame(write_frame)
        format_frame.grid(row=2, column=1, sticky='ew', padx=(10, 0), pady=5)
        
        ttk.Radiobutton(format_frame, text="ASCII Text", variable=self.mam_write_format_var, value="ascii").pack(side='left', padx=(0, 10))
        ttk.Radiobutton(format_frame, text="Hexadecimal", variable=self.mam_write_format_var, value="hex").pack(side='left', padx=(0, 10))
        ttk.Radiobutton(format_frame, text="Decimal", variable=self.mam_write_format_var, value="decimal").pack(side='left')
        
        # Write button
        ttk.Button(write_frame, text="Write MAM Attribute", command=self.write_mam_attribute).grid(row=3, column=1, pady=10)
        
        write_frame.columnconfigure(1, weight=1)
        
        # Write results
        write_results_frame = ttk.LabelFrame(self.mam_write_frame, text="Write Results", padding=10)
        write_results_frame.pack(fill='both', expand=True, padx=10, pady=10)
        
        self.mam_write_results = scrolledtext.ScrolledText(write_results_frame, height=10, wrap='word')
        self.mam_write_results.pack(fill='both', expand=True)
    
    def setup_mam_info_tab(self):
        """Set up the MAM information tab"""
        # MAM overview
        overview_frame = ttk.LabelFrame(self.mam_info_frame, text="MAM Overview", padding=10)
        overview_frame.pack(fill='x', padx=10, pady=10)
        
        overview_text = (
            "Medium Auxiliary Memory (MAM) is a small non-volatile memory area on LTO tape cartridges "
            "that stores metadata about the tape. MAM attributes include:\n\n"
            "• Tape capacity and usage statistics\n"
            "• Load count and device history\n"
            "• Volume identification and labeling\n"
            "• Application-specific data\n"
            "• Cartridge manufacturer information\n"
            "• Custom user-defined attributes"
        )
        
        ttk.Label(overview_frame, text=overview_text, wraplength=700, justify='left').pack(anchor='w')
        
        # Quick MAM summary
        summary_frame = ttk.LabelFrame(self.mam_info_frame, text="Quick MAM Summary", padding=10)
        summary_frame.pack(fill='both', expand=True, padx=10, pady=10)
        
        ttk.Button(summary_frame, text="Get Basic MAM Info", command=self.get_basic_mam_info).pack(pady=10)
        
        self.mam_summary_text = scrolledtext.ScrolledText(summary_frame, height=15, wrap='word')
        self.mam_summary_text.pack(fill='both', expand=True)
        
        # MAM utilities
        utils_frame = ttk.LabelFrame(self.mam_info_frame, text="MAM Utilities", padding=10)
        utils_frame.pack(fill='x', padx=10, pady=10)
        
        utils_button_frame = ttk.Frame(utils_frame)
        utils_button_frame.pack(fill='x')
        
        ttk.Button(utils_button_frame, text="Dump All MAM", command=self.dump_all_mam).pack(side='left', padx=(0, 10))
        ttk.Button(utils_button_frame, text="MAM Space Usage", command=self.get_mam_space_usage).pack(side='left', padx=(0, 10))
        ttk.Button(utils_button_frame, text="Validate MAM", command=self.validate_mam).pack(side='left')
    
    def on_mam_device_change(self, event=None):
        """Handle device selection change in MAM tab"""
        selected_device = self._get_selected_mam_device()
        if selected_device:
            self.log_message(f"MAM operations device set to: {selected_device}")
    
    def select_all_mam_attrs(self):
        """Select all MAM attributes"""
        for var in self.mam_attr_vars.values():
            var.set(True)
    
    def select_no_mam_attrs(self):
        """Deselect all MAM attributes"""
        for var in self.mam_attr_vars.values():
            var.set(False)
    
    def select_common_mam_attrs(self):
        """Select commonly used MAM attributes"""
        self.select_no_mam_attrs()
        common_attrs = ['0x0000', '0x0001', '0x0003', '0x0008', '0x0220', '0x0221']
        for attr in common_attrs:
            if attr in self.mam_attr_vars:
                self.mam_attr_vars[attr].set(True)
    
    def read_mam_attributes(self):
        """Read selected MAM attributes from tape"""
        device = self._get_selected_mam_device()
        if not device:
            messagebox.showerror("Error", "Please select a tape device first.")
            return
        
        # Get selected attributes
        selected_attrs = [attr for attr, var in self.mam_attr_vars.items() if var.get()]
        
        if not selected_attrs:
            messagebox.showerror("Error", "Please select at least one MAM attribute to read.")
            return
        
        def read_mam_thread():
            self.mam_read_results.insert(tk.END, f"\n=== Reading MAM Attributes from {device} ===\n")
            self.log_message(f"Reading MAM attributes from {device}")
            
            for attr_code in selected_attrs:
                attr_desc = self.mam_attributes.get(attr_code, "Unknown")
                self.mam_read_results.insert(tk.END, f"\nReading {attr_code} ({attr_desc})...\n")
                
                # Use sg_raw or similar tool to read MAM
                # This is a simplified example - actual implementation would use proper MAM commands
                success, stdout, stderr = self.ltfs_manager.run_command(
                    f"sg_raw -r 512 {device} 8C 00 00 {attr_code[2:]} 00 00 02 00 00 00"
                )
                
                if success:
                    # Parse the MAM data (this would need proper parsing logic)
                    self.mam_read_results.insert(tk.END, f"Raw data: {stdout}\n")
                else:
                    # Try alternative method using mt or tapeinfo
                    success, stdout, stderr = self.ltfs_manager.run_command(
                        f"tapeinfo -f {device} | grep -A5 -B5 {attr_code}"
                    )
                    
                    if success and stdout.strip():
                        self.mam_read_results.insert(tk.END, f"Value: {stdout.strip()}\n")
                    else:
                        self.mam_read_results.insert(tk.END, f"Error reading attribute: {stderr}\n")
            
            self.mam_read_results.insert(tk.END, "\n=== MAM Read Complete ===\n")
            self.mam_read_results.see(tk.END)
            self.log_message(f"MAM read completed for {device}")
        
        threading.Thread(target=read_mam_thread, daemon=True).start()
    
    def write_mam_attribute(self):
        """Write a MAM attribute to tape"""
        device = self._get_selected_mam_device()
        if not device:
            messagebox.showerror("Error", "Please select a tape device first.")
            return
        
        attr_selection = self.mam_write_attr_var.get()
        if not attr_selection:
            messagebox.showerror("Error", "Please select a MAM attribute to write.")
            return
        
        attr_code = attr_selection.split(':')[0]
        value = self.mam_write_value_var.get()
        data_format = self.mam_write_format_var.get()
        
        if not value:
            messagebox.showerror("Error", "Please enter a value to write.")
            return
        
        # Confirmation dialog
        if not messagebox.askyesno("Confirm MAM Write", 
                                 f"Write MAM attribute {attr_code}?\n\n"
                                 f"Value: {value}\n"
                                 f"Format: {data_format}\n\n"
                                 f"This will modify the tape cartridge metadata."):
            return
        
        def write_mam_thread():
            self.mam_write_results.insert(tk.END, f"\n=== Writing MAM Attribute {attr_code} to {device} ===\n")
            self.log_message(f"Writing MAM attribute {attr_code} to {device}")
            
            # Convert value based on format
            if data_format == "hex":
                try:
                    # Convert hex string to bytes
                    hex_value = value.replace(' ', '').replace('0x', '')
                    byte_data = bytes.fromhex(hex_value)
                    formatted_value = ' '.join(f'{b:02x}' for b in byte_data)
                except ValueError:
                    self.mam_write_results.insert(tk.END, f"Error: Invalid hexadecimal value\n")
                    return
            elif data_format == "decimal":
                try:
                    int_value = int(value)
                    formatted_value = f"{int_value:08x}"
                except ValueError:
                    self.mam_write_results.insert(tk.END, f"Error: Invalid decimal value\n")
                    return
            else:  # ASCII
                # Convert ASCII to hex bytes
                byte_data = value.encode('ascii')
                formatted_value = ' '.join(f'{b:02x}' for b in byte_data)
            
            # Use sg_raw to write MAM (simplified example)
            cmd = f"sg_raw -s {len(formatted_value.split())} {device} 8D 00 00 {attr_code[2:]} 00 00 {formatted_value}"
            success, stdout, stderr = self.ltfs_manager.run_command(cmd)
            
            if success:
                self.mam_write_results.insert(tk.END, f"Successfully wrote MAM attribute {attr_code}\n")
                self.mam_write_results.insert(tk.END, f"Value: {value} ({data_format})\n")
                self.log_message(f"MAM write successful for {attr_code}")
                messagebox.showinfo("Success", f"MAM attribute {attr_code} written successfully")
            else:
                self.mam_write_results.insert(tk.END, f"Error writing MAM attribute: {stderr}\n")
                self.log_message(f"MAM write failed for {attr_code}: {stderr}")
                messagebox.showerror("Error", f"Failed to write MAM attribute:\n{stderr}")
            
            self.mam_write_results.see(tk.END)
        
        threading.Thread(target=write_mam_thread, daemon=True).start()
    
    def get_basic_mam_info(self):
        """Get basic MAM information summary"""
        device = self._get_selected_mam_device()
        if not device:
            messagebox.showerror("Error", "Please select a tape device first.")
            return
        
        def mam_info_thread():
            self.mam_summary_text.insert(tk.END, f"\n=== Basic MAM Information - {device} ===\n")
            self.log_message(f"Getting basic MAM info for {device}")
            
            # Get basic tape information using tapeinfo
            basic_commands = [
                ("Tape Info", f"tapeinfo -f {device}"),
                ("MAM Dump (if supported)", f"sg_raw -r 4096 {device} 8C 00 00 00 00 00 10 00 00 00")
            ]
            
            for info_type, cmd in basic_commands:
                self.mam_summary_text.insert(tk.END, f"\n{info_type}:\n")
                success, stdout, stderr = self.ltfs_manager.run_command(cmd)
                
                if success and stdout.strip():
                    self.mam_summary_text.insert(tk.END, f"{stdout}\n")
                else:
                    self.mam_summary_text.insert(tk.END, f"Not available or error: {stderr}\n")
            
            self.mam_summary_text.see(tk.END)
            self.log_message(f"Basic MAM info completed for {device}")
        
        threading.Thread(target=mam_info_thread, daemon=True).start()
    
    def dump_all_mam(self):
        """Dump all available MAM data"""
        device = self._get_selected_mam_device()
        if not device:
            messagebox.showerror("Error", "Please select a tape device first.")
            return
        
        def dump_mam_thread():
            self.mam_summary_text.insert(tk.END, f"\n=== Complete MAM Dump - {device} ===\n")
            self.log_message(f"Dumping all MAM data for {device}")
            
            # Try to read all known MAM attributes
            for attr_code, attr_desc in self.mam_attributes.items():
                self.mam_summary_text.insert(tk.END, f"\n{attr_code} - {attr_desc}:\n")
                
                # Use sg_raw to read MAM attribute
                success, stdout, stderr = self.ltfs_manager.run_command(
                    f"sg_raw -r 512 {device} 8C 00 00 {attr_code[2:]} 00 00 02 00 00 00"
                )
                
                if success and stdout.strip():
                    self.mam_summary_text.insert(tk.END, f"  {stdout.strip()}\n")
                else:
                    self.mam_summary_text.insert(tk.END, f"  Not available\n")
            
            self.mam_summary_text.insert(tk.END, "\n=== MAM Dump Complete ===\n")
            self.mam_summary_text.see(tk.END)
            self.log_message(f"Complete MAM dump finished for {device}")
        
        threading.Thread(target=dump_mam_thread, daemon=True).start()
    
    def get_mam_space_usage(self):
        """Get MAM space usage information"""
        device = self._get_selected_mam_device()
        if not device:
            messagebox.showerror("Error", "Please select a tape device first.")
            return
        
        def mam_space_thread():
            self.mam_summary_text.insert(tk.END, f"\n=== MAM Space Usage - {device} ===\n")
            self.log_message(f"Checking MAM space usage for {device}")
            
            # Read MAM space remaining attribute
            success, stdout, stderr = self.ltfs_manager.run_command(
                f"sg_raw -r 512 {device} 8C 00 00 04 00 00 02 00 00 00"
            )
            
            if success:
                self.mam_summary_text.insert(tk.END, f"MAM Space Remaining: {stdout}\n")
            else:
                self.mam_summary_text.insert(tk.END, f"Could not read MAM space info: {stderr}\n")
            
            self.mam_summary_text.see(tk.END)
            self.log_message(f"MAM space usage check completed for {device}")
        
        threading.Thread(target=mam_space_thread, daemon=True).start()
    
    def validate_mam(self):
        """Validate MAM data integrity"""
        device = self._get_selected_mam_device()
        if not device:
            messagebox.showerror("Error", "Please select a tape device first.")
            return
        
        def validate_mam_thread():
            self.mam_summary_text.insert(tk.END, f"\n=== MAM Validation - {device} ===\n")
            self.log_message(f"Validating MAM data for {device}")
            
            # Check key MAM attributes for consistency
            validation_attrs = {
                '0x0000': 'Remaining Capacity',
                '0x0001': 'Maximum Capacity',
                '0x0003': 'Load Count',
                '0x0008': 'Volume Identifier'
            }
            
            valid_count = 0
            total_count = len(validation_attrs)
            
            for attr_code, attr_name in validation_attrs.items():
                success, stdout, stderr = self.ltfs_manager.run_command(
                    f"sg_raw -r 512 {device} 8C 00 00 {attr_code[2:]} 00 00 02 00 00 00"
                )
                
                if success and stdout.strip():
                    self.mam_summary_text.insert(tk.END, f"✓ {attr_name}: Valid\n")
                    valid_count += 1
                else:
                    self.mam_summary_text.insert(tk.END, f"✗ {attr_name}: Invalid or missing\n")
            
            self.mam_summary_text.insert(tk.END, f"\nValidation Summary: {valid_count}/{total_count} attributes valid\n")
            
            if valid_count == total_count:
                self.mam_summary_text.insert(tk.END, "✓ MAM data appears to be valid\n")
            else:
                self.mam_summary_text.insert(tk.END, "⚠ Some MAM data may be corrupted or missing\n")
            
            self.mam_summary_text.see(tk.END)
            self.log_message(f"MAM validation completed for {device}")
        
        threading.Thread(target=validate_mam_thread, daemon=True).start()
    
    def clear_mam_read_results(self):
        """Clear MAM read results"""
        self.mam_read_results.delete(1.0, tk.END)
        self.log_message("MAM read results cleared")
    
    def save_mam_read_results(self):
        """Save MAM read results to file"""
        filename = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
            title="Save MAM Read Results"
        )
        
        if filename:
            try:
                with open(filename, 'w') as f:
                    f.write(self.mam_read_results.get(1.0, tk.END))
                messagebox.showinfo("Success", f"MAM results saved to {filename}")
                self.log_message(f"MAM results saved to {filename}")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to save MAM results: {str(e)}")
    
    def export_mam_report(self):
        """Export comprehensive MAM report"""
        device = self._get_selected_mam_device()
        if not device:
            messagebox.showerror("Error", "Please select a tape device first.")
            return
        
        filename = filedialog.asksaveasfilename(
            defaultextension=".html",
            filetypes=[("HTML files", "*.html"), ("Text files", "*.txt"), ("All files", "*.*")],
            title="Export MAM Report"
        )
        
        if filename:
            try:
                timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
                
                if filename.endswith('.html'):
                    # Create HTML MAM report
                    html_content = f"""
                    <!DOCTYPE html>
                    <html>
                    <head>
                        <title>MAM Report - {device}</title>
                        <style>
                            body {{ font-family: Arial, sans-serif; margin: 20px; }}
                            .header {{ background-color: #f0f0f0; padding: 15px; border-radius: 5px; }}
                            .section {{ margin: 20px 0; padding: 15px; border: 1px solid #ddd; border-radius: 5px; }}
                            pre {{ background-color: #f8f8f8; padding: 10px; border-radius: 3px; overflow-x: auto; }}
                            .attribute {{ margin: 10px 0; padding: 10px; background-color: #f9f9f9; border-left: 4px solid #007acc; }}
                        </style>
                    </head>
                    <body>
                        <div class="header">
                            <h1>MAM (Medium Auxiliary Memory) Report</h1>
                            <p><strong>Device:</strong> {device}</p>
                            <p><strong>Generated:</strong> {timestamp}</p>
                        </div>
                        
                        <div class="section">
                            <h2>MAM Read Results</h2>
                            <pre>{self.mam_read_results.get(1.0, tk.END)}</pre>
                        </div>
                        
                        <div class="section">
                            <h2>MAM Summary</h2>
                            <pre>{self.mam_summary_text.get(1.0, tk.END)}</pre>
                        </div>
                        
                        <div class="section">
                            <h2>Available MAM Attributes</h2>
                    """
                    
                    for attr_code, attr_desc in self.mam_attributes.items():
                        html_content += f'<div class="attribute"><strong>{attr_code}:</strong> {attr_desc}</div>\n'
                    
                    html_content += """
                        </div>
                    </body>
                    </html>
                    """
                    
                    with open(filename, 'w') as f:
                        f.write(html_content)
                else:
                    # Create text report
                    with open(filename, 'w') as f:
                        f.write(f"MAM (Medium Auxiliary Memory) Report\n")
                        f.write(f"{'='*50}\n")
                        f.write(f"Device: {device}\n")
                        f.write(f"Generated: {timestamp}\n\n")
                        f.write("MAM Read Results:\n")
                        f.write("-" * 30 + "\n")
                        f.write(self.mam_read_results.get(1.0, tk.END))
                        f.write("\n\nMAM Summary:\n")
                        f.write("-" * 30 + "\n")
                        f.write(self.mam_summary_text.get(1.0, tk.END))
                
                messagebox.showinfo("Success", f"MAM report exported to {filename}")
                self.log_message(f"MAM report exported to {filename}")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to export MAM report: {str(e)}")
    
    def setup_color_picker(self, parent):
        """Set up the color picker tool for custom theme editing"""
        color_main = ttk.Frame(parent)
        color_main.pack(fill='both', expand=True, padx=10, pady=10)
        
        ttk.Label(color_main, text="Color Editor", font=('Arial', 14, 'bold')).pack(anchor='w', pady=(0, 15))
        
        # Introduction
        intro_text = (
            "Create custom themes by selecting colors for different interface elements. "
            "Click the color buttons to open a color picker and customize each element."
        )
        ttk.Label(color_main, text=intro_text, wraplength=700, justify='left').pack(anchor='w', pady=(0, 20))
        
        # Custom theme setup
        custom_frame = ttk.LabelFrame(color_main, text="Custom Theme Editor", padding=15)
        custom_frame.pack(fill='both', expand=True)
        
        # Theme name input
        name_frame = ttk.Frame(custom_frame)
        name_frame.pack(fill='x', pady=(0, 15))
        
        ttk.Label(name_frame, text="Custom Theme Name:").pack(side='left', padx=(0, 10))
        self.custom_theme_name_var = tk.StringVar(value="My Custom Theme")
        ttk.Entry(name_frame, textvariable=self.custom_theme_name_var, width=30).pack(side='left')
        
        # Base theme selection
        base_frame = ttk.Frame(custom_frame)
        base_frame.pack(fill='x', pady=(0, 15))
        
        ttk.Label(base_frame, text="Base Theme:").pack(side='left', padx=(0, 10))
        self.base_theme_var = tk.StringVar(value='dark')
        base_combo = ttk.Combobox(base_frame, textvariable=self.base_theme_var, 
                                values=['light', 'dark', 'blue_dark', 'high_contrast'], 
                                state="readonly", width=20)
        base_combo.pack(side='left', padx=(0, 10))
        base_combo.bind('<<ComboboxSelected>>', self.on_base_theme_changed)
        
        ttk.Button(base_frame, text="Load Base Colors", 
                  command=self.load_base_theme_colors).pack(side='left', padx=(10, 0))
        
        # Color editing area
        colors_frame = ttk.LabelFrame(custom_frame, text="Color Settings", padding=10)
        colors_frame.pack(fill='both', expand=True, pady=(15, 0))
        
        # Create scrollable frame for color options
        canvas = tk.Canvas(colors_frame, height=300)
        scrollbar = ttk.Scrollbar(colors_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        # Initialize custom theme colors
        self.custom_theme_colors = {}
        self.color_buttons = {}
        self.color_previews = {}
        
        # Color definitions with descriptions
        self.color_definitions = {
            'bg': 'Main Background - Primary window background color',
            'fg': 'Main Text - Primary text color for labels and content',
            'select_bg': 'Selection Background - Highlight color for selected items',
            'select_fg': 'Selection Text - Text color for selected items',
            'entry_bg': 'Input Background - Background for text fields and inputs',
            'entry_fg': 'Input Text - Text color in input fields',
            'frame_bg': 'Frame Background - Background for container frames',
            'button_bg': 'Button Background - Default button background color',
            'button_hover': 'Button Hover - Button color when mouse hovers over',
            'text_bg': 'Text Widget Background - Background for large text areas',
            'text_fg': 'Text Widget Text - Text color in text widgets',
            'notebook_bg': 'Tab Container - Background for tab containers',
            'tab_bg': 'Inactive Tab - Background for inactive tabs',
            'tab_active': 'Active Tab - Background for the currently selected tab',
            'border_color': 'Borders - Color for widget borders and separators',
            'warning_fg': 'Warning Text - Color for warning messages',
            'success_fg': 'Success Text - Color for success messages',
            'info_fg': 'Info Text - Color for informational text'
        }
        
        # Initialize color picker buttons first, then load colors
        # Create color picker buttons in a grid
        row = 0
        for color_key, description in self.color_definitions.items():
            color_frame = ttk.Frame(scrollable_frame)
            color_frame.pack(fill='x', pady=2)
            
            # Color preview button
            color_button = tk.Button(color_frame, width=4, height=1, 
                                   command=lambda k=color_key: self.pick_color(k))
            color_button.pack(side='left', padx=(0, 10))
            self.color_buttons[color_key] = color_button
            
            # Color code entry
            color_var = tk.StringVar(value=self.custom_theme_colors.get(color_key, '#000000'))
            color_entry = ttk.Entry(color_frame, textvariable=color_var, width=10)
            color_entry.pack(side='left', padx=(0, 10))
            color_entry.bind('<KeyRelease>', lambda e, k=color_key, v=color_var: self.on_color_code_changed(k, v))
            self.color_previews[color_key] = color_var
            
            # Description
            ttk.Label(color_frame, text=description, font=('Arial', 9)).pack(side='left')
            
            row += 1
        
        # Update color button appearances
        self.update_color_buttons()
        
        # Control buttons
        control_frame = ttk.Frame(custom_frame)
        control_frame.pack(fill='x', pady=(15, 0))
        
        ttk.Button(control_frame, text="Preview Custom Theme", 
                  command=self.preview_custom_theme).pack(side='left', padx=(0, 10))
        ttk.Button(control_frame, text="Apply Custom Theme", 
                  command=self.apply_custom_theme).pack(side='left', padx=(0, 10))
        ttk.Button(control_frame, text="Save Custom Theme", 
                  command=self.save_custom_theme).pack(side='left', padx=(0, 10))
        ttk.Button(control_frame, text="Load Custom Theme", 
                  command=self.load_custom_theme).pack(side='left', padx=(0, 10))
        
        # Color dropper tool
        dropper_button = ttk.Button(control_frame, text="🎨 Color Dropper", 
                  command=self.activate_color_dropper)
        dropper_button.pack(side='right', padx=(10, 0))
        
        reset_button = ttk.Button(control_frame, text="Reset Colors", 
                  command=self.reset_custom_colors)
        reset_button.pack(side='right')
        
        # Live preview area
        preview_frame = ttk.LabelFrame(color_main, text="Live Preview", padding=10)
        preview_frame.pack(fill='x', pady=(15, 0))
        
        # Mini preview widgets
        preview_content = ttk.Frame(preview_frame)
        preview_content.pack(fill='x')
        
        # Sample elements for live preview
        self.preview_label = tk.Label(preview_content, text="Sample Label")
        self.preview_label.pack(side='left', padx=(0, 10))
        
        self.preview_entry = tk.Entry(preview_content, width=15)
        self.preview_entry.pack(side='left', padx=(0, 10))
        self.preview_entry.insert(0, "Sample Input")
        
        self.preview_button = tk.Button(
            preview_content,
            text="Sample Button",
            command=self.on_theme_preview_sample_button
        )
        self.preview_button.pack(side='left', padx=(0, 10))
        
        self.preview_text = tk.Text(preview_content, height=3, width=25)
        self.preview_text.pack(side='left')
        self.preview_text.insert('1.0', "Sample text area\nwith multiple lines\nfor preview")
        
        # Store preview widgets for easy access
        self.preview_widgets = {
            'label': self.preview_label,
            'entry': self.preview_entry,
            'button': self.preview_button,
            'text': self.preview_text
        }
        
        # Now load base colors after all widgets are created
        self.load_base_theme_colors()
    
    def on_base_theme_changed(self, event=None):
        """Handle base theme selection change"""
        base_theme = self.base_theme_var.get()
        self.log_message(f"Base theme changed to: {base_theme}")
    
    def load_base_theme_colors(self):
        """Load colors from the selected base theme"""
        base_theme = self.base_theme_var.get()
        if base_theme in self.themes:
            base_colors = self.themes[base_theme].copy()
            # Remove the 'name' key if it exists
            base_colors.pop('name', None)
            
            # Update custom theme colors
            self.custom_theme_colors.update(base_colors)
            
            # Update color preview entries
            for color_key, color_value in base_colors.items():
                if color_key in self.color_previews:
                    self.color_previews[color_key].set(color_value)
            
            # Update color buttons
            self.update_color_buttons()
            
            # Update live preview
            self.update_live_preview()
            
            self.log_message(f"Loaded base colors from {base_theme} theme")
    
    def pick_color(self, color_key):
        """Open color picker for a specific color element"""
        current_color = self.custom_theme_colors.get(color_key, '#000000')
        
        try:
            from tkinter import colorchooser
            color = colorchooser.askcolor(initialcolor=current_color, title=f"Choose {color_key} color")
            
            if color[1]:  # If user didn't cancel
                new_color = color[1]
                self.custom_theme_colors[color_key] = new_color
                self.color_previews[color_key].set(new_color)
                self.update_color_buttons()
                self.update_live_preview()
                self.log_message(f"Color {color_key} changed to {new_color}")
        except ImportError:
            # Fallback if colorchooser is not available
            new_color = tk.simpledialog.askstring("Color Input", 
                                                 f"Enter hex color for {color_key} (e.g., #ff0000):",
                                                 initialvalue=current_color)
            if new_color and new_color.startswith('#') and len(new_color) == 7:
                self.custom_theme_colors[color_key] = new_color
                self.color_previews[color_key].set(new_color)
                self.update_color_buttons()
                self.update_live_preview()
                self.log_message(f"Color {color_key} changed to {new_color}")
    
    def on_color_code_changed(self, color_key, color_var):
        """Handle manual color code entry"""
        new_color = color_var.get()
        if self.is_valid_color(new_color):
            self.custom_theme_colors[color_key] = new_color
            self.update_color_buttons()
            self.update_live_preview()
    
    def is_valid_color(self, color_string):
        """Validate if a string is a valid color code"""
        try:
            # Try to use the color - this will raise an exception if invalid
            root = tk.Tk()
            root.withdraw()
            label = tk.Label(root, bg=color_string)
            root.destroy()
            return True
        except tk.TclError:
            return False
    
    def update_color_buttons(self):
        """Update the appearance of color picker buttons"""
        for color_key, button in self.color_buttons.items():
            color = self.custom_theme_colors.get(color_key, '#000000')
            try:
                button.configure(bg=color)
                # Set contrasting text color
                if self.is_dark_color(color):
                    button.configure(fg='white')
                else:
                    button.configure(fg='black')
            except tk.TclError:
                pass
    
    def is_dark_color(self, color_hex):
        """Determine if a color is dark (for contrasting text)"""
        try:
            # Remove # if present
            color_hex = color_hex.lstrip('#')
            # Convert to RGB
            r, g, b = tuple(int(color_hex[i:i+2], 16) for i in (0, 2, 4))
            # Calculate perceived brightness
            brightness = (r * 299 + g * 587 + b * 114) / 1000
            return brightness < 128
        except:
            return False
    
    def update_live_preview(self):
        """Update the live preview widgets with current colors"""
        try:
            # Update preview label
            self.preview_label.configure(
                bg=self.custom_theme_colors.get('bg', '#ffffff'),
                fg=self.custom_theme_colors.get('fg', '#000000')
            )
            
            # Update preview entry
            self.preview_entry.configure(
                bg=self.custom_theme_colors.get('entry_bg', '#ffffff'),
                fg=self.custom_theme_colors.get('entry_fg', '#000000'),
                selectbackground=self.custom_theme_colors.get('select_bg', '#0078d4'),
                selectforeground=self.custom_theme_colors.get('select_fg', '#ffffff'),
                insertbackground=self.custom_theme_colors.get('entry_fg', '#000000')
            )
            
            # Update preview button
            self.preview_button.configure(
                bg=self.custom_theme_colors.get('button_bg', '#e1e1e1'),
                fg=self.custom_theme_colors.get('fg', '#000000'),
                activebackground=self.custom_theme_colors.get('button_hover', '#d4d4d4')
            )
            
            # Update preview text
            self.preview_text.configure(
                bg=self.custom_theme_colors.get('text_bg', '#ffffff'),
                fg=self.custom_theme_colors.get('text_fg', '#000000'),
                selectbackground=self.custom_theme_colors.get('select_bg', '#0078d4'),
                selectforeground=self.custom_theme_colors.get('select_fg', '#ffffff'),
                insertbackground=self.custom_theme_colors.get('text_fg', '#000000')
            )
        except tk.TclError:
            pass
    
    def preview_custom_theme(self):
        """Preview the custom theme temporarily"""
        theme_name = self.custom_theme_name_var.get()
        
        if messagebox.askyesno("Preview Custom Theme", 
                             f"Preview custom theme '{theme_name}'?\n\n"
                             "This will temporarily apply your custom colors."):
            # Store current theme for reverting
            self.previous_theme = self.current_theme_name.get()
            
            # Create temporary theme
            temp_theme = self.custom_theme_colors.copy()
            temp_theme['name'] = theme_name
            self.themes['custom_preview'] = temp_theme
            
            # Apply preview theme
            self.current_theme_name.set('custom_preview')
            self.apply_selected_theme()
            
            self.log_message(f"Previewing custom theme: {theme_name}")
    
    def apply_custom_theme(self):
        """Apply the custom theme permanently"""
        theme_name = self.custom_theme_name_var.get()
        
        if not theme_name.strip():
            messagebox.showerror("Error", "Please enter a name for your custom theme.")
            return
        
        # Create the custom theme
        custom_theme = self.custom_theme_colors.copy()
        custom_theme['name'] = theme_name
        
        # Add to themes dictionary
        theme_key = 'custom_' + theme_name.lower().replace(' ', '_')
        self.themes[theme_key] = custom_theme
        
        # Apply the theme
        self.current_theme_name.set(theme_key)
        self.apply_selected_theme()
        
        # Update displays
        self.update_current_theme_display()
        
        # Save preference
        self.save_theme_preference(theme_key)
        
        self.log_message(f"Applied custom theme: {theme_name}")
        messagebox.showinfo("Theme Applied", f"Custom theme '{theme_name}' has been applied and saved!")
    
    def save_custom_theme(self):
        """Save custom theme to file"""
        theme_name = self.custom_theme_name_var.get()
        
        if not theme_name.strip():
            messagebox.showerror("Error", "Please enter a name for your custom theme.")
            return
        
        filename = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            title="Save Custom Theme",
            initialvalue=f"{theme_name.replace(' ', '_')}_theme.json"
        )
        
        if filename:
            try:
                import json
                theme_data = {
                    'name': theme_name,
                    'colors': self.custom_theme_colors,
                    'created': time.strftime("%Y-%m-%d %H:%M:%S"),
                    'base_theme': self.base_theme_var.get()
                }
                
                with open(filename, 'w') as f:
                    json.dump(theme_data, f, indent=2)
                
                messagebox.showinfo("Success", f"Custom theme saved to {filename}")
                self.log_message(f"Custom theme saved: {filename}")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to save custom theme: {str(e)}")
    
    def load_custom_theme(self):
        """Load custom theme from file"""
        filename = filedialog.askopenfilename(
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            title="Load Custom Theme"
        )
        
        if filename:
            try:
                import json
                with open(filename, 'r') as f:
                    theme_data = json.load(f)
                
                # Load theme data
                if 'name' in theme_data:
                    self.custom_theme_name_var.set(theme_data['name'])
                
                if 'colors' in theme_data:
                    self.custom_theme_colors.update(theme_data['colors'])
                    
                    # Update color preview entries
                    for color_key, color_value in theme_data['colors'].items():
                        if color_key in self.color_previews:
                            self.color_previews[color_key].set(color_value)
                
                if 'base_theme' in theme_data:
                    self.base_theme_var.set(theme_data['base_theme'])
                
                # Update interface
                self.update_color_buttons()
                self.update_live_preview()
                
                messagebox.showinfo("Success", f"Custom theme loaded from {filename}")
                self.log_message(f"Custom theme loaded: {filename}")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to load custom theme: {str(e)}")
    
    def reset_custom_colors(self):
        """Reset custom colors to base theme"""
        if messagebox.askyesno("Reset Colors", "Reset all colors to the base theme?"):
            self.load_base_theme_colors()
            self.log_message("Custom colors reset to base theme")
    
    def activate_color_dropper(self):
        """Activate the color dropper tool for interactive color selection"""
        # Create color dropper window
        dropper_window = tk.Toplevel(self.root)
        dropper_window.title("Color Dropper Tool")
        dropper_window.geometry("500x600")
        dropper_window.resizable(True, True)
        
        # Make it stay on top
        dropper_window.attributes('-topmost', True)
        
        # Main frame
        main_frame = ttk.Frame(dropper_window, padding=20)
        main_frame.pack(fill='both', expand=True)
        
        # Instructions
        instructions = (
            "🎨 Color Dropper Tool\n\n"
            "Click on any interface element below to inspect its color properties.\n"
            "You can then use these colors in your custom theme or modify them.\n\n"
            "Instructions:\n"
            "1. Click 'Start Color Inspection' to begin\n"
            "2. Click on any GUI element to see its colors\n"
            "3. Use the 'Apply to Theme' button to add colors to your custom theme"
        )
        
        ttk.Label(main_frame, text=instructions, wraplength=450, justify='left', 
                 font=('Arial', 10)).pack(anchor='w', pady=(0, 20))
        
        # Control buttons
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill='x', pady=(0, 20))
        
        self.dropper_active = tk.BooleanVar(value=False)
        
        def toggle_dropper():
            if self.dropper_active.get():
                self.start_color_inspection()
                dropper_btn.config(text="Stop Color Inspection")
            else:
                self.stop_color_inspection()
                dropper_btn.config(text="Start Color Inspection")
        
        dropper_btn = ttk.Button(button_frame, text="Start Color Inspection", 
                               command=toggle_dropper)
        dropper_btn.pack(side='left', padx=(0, 10))
        
        ttk.Button(button_frame, text="Close Dropper", 
                  command=dropper_window.destroy).pack(side='right')
        
        # Color inspection results
        results_frame = ttk.LabelFrame(main_frame, text="Color Inspection Results", padding=10)
        results_frame.pack(fill='both', expand=True)
        
        # Current element info
        self.current_element_var = tk.StringVar(value="Click an element to inspect its colors")
        ttk.Label(results_frame, textvariable=self.current_element_var, 
                 font=('Arial', 10, 'bold')).pack(anchor='w', pady=(0, 10))
        
        # Color properties display
        self.color_properties_frame = ttk.Frame(results_frame)
        self.color_properties_frame.pack(fill='both', expand=True)
        
        # Initialize color properties display
        self.color_properties = {}
        self.color_apply_buttons = {}
        
        self.setup_color_properties_display()
        
        # Store dropper window reference
        self.dropper_window = dropper_window
        
        # Bind window close event
        dropper_window.protocol("WM_DELETE_WINDOW", self.on_dropper_close)
        
        self.log_message("Color dropper tool activated")
    
    def setup_color_properties_display(self):
        """Set up the color properties display area"""
        # Clear existing widgets
        for widget in self.color_properties_frame.winfo_children():
            widget.destroy()
        
        # Color property types to display
        property_types = [
            ('bg', 'Background Color'),
            ('fg', 'Foreground Color'),
            ('selectbackground', 'Selection Background'),
            ('selectforeground', 'Selection Foreground'),
            ('insertbackground', 'Cursor Color'),
            ('activebackground', 'Active Background'),
            ('activeforeground', 'Active Foreground')
        ]
        
        for prop_key, prop_name in property_types:
            prop_frame = ttk.Frame(self.color_properties_frame)
            prop_frame.pack(fill='x', pady=2)
            
            # Property name
            ttk.Label(prop_frame, text=f"{prop_name}:", width=20).pack(side='left')
            
            # Color preview
            color_preview = tk.Label(prop_frame, text="N/A", width=10, height=1, 
                                   relief='solid', borderwidth=1)
            color_preview.pack(side='left', padx=(5, 5))
            
            # Color value
            color_value = tk.StringVar(value="Not detected")
            ttk.Label(prop_frame, textvariable=color_value, width=15).pack(side='left', padx=(5, 5))
            
            # Apply to theme button
            apply_btn = ttk.Button(prop_frame, text="Apply to Theme", state='disabled',
                                 command=lambda k=prop_key: self.apply_color_to_theme(k))
            apply_btn.pack(side='right')
            
            # Store references
            self.color_properties[prop_key] = {
                'preview': color_preview,
                'value': color_value,
                'button': apply_btn
            }
    
    def start_color_inspection(self):
        """Start the color inspection mode"""
        self.dropper_active.set(True)
        self.current_element_var.set("Color inspection active - click on any GUI element")
        
        # Bind click events to all widgets
        self.bind_click_events_recursively(self.root)
        
        # Change cursor to crosshair
        self.root.configure(cursor="crosshair")
        
        self.log_message("Color inspection started - click on any element")
    
    def stop_color_inspection(self):
        """Stop the color inspection mode"""
        self.dropper_active.set(False)
        self.current_element_var.set("Color inspection stopped")
        
        # Unbind click events
        self.unbind_click_events_recursively(self.root)
        
        # Reset cursor
        self.root.configure(cursor="")
        
        self.log_message("Color inspection stopped")
    
    def bind_click_events_recursively(self, widget):
        """Recursively bind click events to all widgets"""
        try:
            # Bind click event to this widget
            widget.bind("<Button-1>", self.on_widget_clicked, add=True)
            
            # Recursively bind to children
            for child in widget.winfo_children():
                self.bind_click_events_recursively(child)
        except tk.TclError:
            pass
    
    def unbind_click_events_recursively(self, widget):
        """Recursively unbind click events from all widgets"""
        try:
            # Unbind click event from this widget
            widget.unbind("<Button-1>")
            
            # Recursively unbind from children
            for child in widget.winfo_children():
                self.unbind_click_events_recursively(child)
        except tk.TclError:
            pass
    
    def on_widget_clicked(self, event):
        """Handle widget click during color inspection"""
        if not self.dropper_active.get():
            return
        
        widget = event.widget
        widget_class = widget.winfo_class()
        widget_name = str(widget)
        
        # Update current element info
        self.current_element_var.set(f"Inspecting: {widget_class} - {widget_name}")
        
        # Get widget color properties
        self.inspect_widget_colors(widget)
        
        self.log_message(f"Inspected widget: {widget_class}")
        
        # Prevent event propagation
        return "break"
    
    def inspect_widget_colors(self, widget):
        """Inspect and display color properties of a widget"""
        widget_class = widget.winfo_class()
        
        # Properties to check based on widget type
        properties_to_check = ['bg', 'fg', 'selectbackground', 'selectforeground', 
                             'insertbackground', 'activebackground', 'activeforeground']
        
        # TTK widgets have different property names
        if widget_class.startswith('T'):
            # TTK widgets - we'll need to get style information
            self.inspect_ttk_widget_colors(widget)
        else:
            # Regular Tkinter widgets
            self.inspect_tk_widget_colors(widget, properties_to_check)
    
    def inspect_tk_widget_colors(self, widget, properties):
        """Inspect colors of a regular Tkinter widget"""
        for prop_key in properties:
            if prop_key in self.color_properties:
                try:
                    color_value = widget.cget(prop_key)
                    if color_value and color_value != '':
                        # Update the display
                        self.update_color_property_display(prop_key, color_value)
                    else:
                        self.clear_color_property_display(prop_key)
                except tk.TclError:
                    # Property doesn't exist for this widget type
                    self.clear_color_property_display(prop_key)
    
    def inspect_ttk_widget_colors(self, widget):
        """Inspect colors of a TTK widget using style information"""
        try:
            style = ttk.Style()
            widget_style = widget.winfo_class()
            
            # Get style configuration
            style_config = style.configure(widget_style)
            
            # Map TTK style properties to our property keys
            ttk_property_map = {
                'background': 'bg',
                'foreground': 'fg',
                'fieldbackground': 'bg',  # For Entry widgets
                'selectbackground': 'selectbackground',
                'selectforeground': 'selectforeground'
            }
            
            # Clear all displays first
            for prop_key in self.color_properties:
                self.clear_color_property_display(prop_key)
            
            # Update with available TTK properties
            if style_config:
                for ttk_prop, our_prop in ttk_property_map.items():
                    if ttk_prop in style_config and our_prop in self.color_properties:
                        color_value = style_config[ttk_prop]
                        if color_value:
                            self.update_color_property_display(our_prop, color_value)
            
        except Exception as e:
            # If TTK inspection fails, show a generic message
            self.current_element_var.set(f"TTK widget detected - style inspection limited")
    
    def update_color_property_display(self, prop_key, color_value):
        """Update the display for a specific color property"""
        if prop_key in self.color_properties:
            prop_info = self.color_properties[prop_key]
            
            # Update color value
            prop_info['value'].set(color_value)
            
            # Update color preview
            try:
                prop_info['preview'].configure(bg=color_value, text=color_value[:7])
                
                # Set contrasting text color
                if self.is_dark_color(color_value):
                    prop_info['preview'].configure(fg='white')
                else:
                    prop_info['preview'].configure(fg='black')
                
                # Enable apply button
                prop_info['button'].configure(state='normal')
                
            except tk.TclError:
                # Invalid color value
                prop_info['preview'].configure(bg='gray', text='Invalid', fg='black')
                prop_info['button'].configure(state='disabled')
    
    def clear_color_property_display(self, prop_key):
        """Clear the display for a specific color property"""
        if prop_key in self.color_properties:
            prop_info = self.color_properties[prop_key]
            prop_info['value'].set("Not available")
            prop_info['preview'].configure(bg='lightgray', text='N/A', fg='black')
            prop_info['button'].configure(state='disabled')
    
    def apply_color_to_theme(self, prop_key):
        """Apply an inspected color to the custom theme"""
        if prop_key in self.color_properties:
            color_value = self.color_properties[prop_key]['value'].get()
            
            if color_value and color_value != "Not available":
                # Map property to theme color key
                theme_color_map = {
                    'bg': 'bg',
                    'fg': 'fg',
                    'selectbackground': 'select_bg',
                    'selectforeground': 'select_fg',
                    'insertbackground': 'entry_fg',
                    'activebackground': 'button_hover',
                    'activeforeground': 'fg'
                }
                
                theme_key = theme_color_map.get(prop_key, prop_key)
                
                # Apply to custom theme
                if theme_key in self.custom_theme_colors:
                    self.custom_theme_colors[theme_key] = color_value
                    
                    # Update color preview entry if it exists
                    if theme_key in self.color_previews:
                        self.color_previews[theme_key].set(color_value)
                    
                    # Update color buttons and live preview
                    self.update_color_buttons()
                    self.update_live_preview()
                    
                    self.log_message(f"Applied color {color_value} to theme property {theme_key}")
                    messagebox.showinfo("Color Applied", 
                                       f"Color {color_value} applied to {theme_key} in your custom theme!")
                else:
                    messagebox.showwarning("Warning", f"Cannot map {prop_key} to a theme property")
    
    def on_dropper_close(self):
        """Handle color dropper window close"""
        self.stop_color_inspection()
        if hasattr(self, 'dropper_window'):
            self.dropper_window.destroy()
            delattr(self, 'dropper_window')
        self.log_message("Color dropper tool closed")

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

