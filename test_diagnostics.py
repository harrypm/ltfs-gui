#!/usr/bin/env python3
"""
Test script to verify LTFS GUI diagnostic functions work correctly
"""

import sys
import os
import subprocess

def test_command(name, command):
    """Test if a command runs successfully"""
    print(f"Testing {name}...")
    try:
        result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            print(f"  ✓ {name}: SUCCESS")
            if result.stdout.strip():
                print(f"    Output: {result.stdout.strip()[:100]}...")
            return True
        else:
            print(f"  ✗ {name}: FAILED")
            if result.stderr.strip():
                print(f"    Error: {result.stderr.strip()[:100]}...")
            return False
    except subprocess.TimeoutExpired:
        print(f"  ⚠ {name}: TIMEOUT")
        return False
    except Exception as e:
        print(f"  ✗ {name}: EXCEPTION - {str(e)}")
        return False

def test_tape_device_access():
    """Test if we can access tape devices"""
    print("=== Testing Tape Device Access ===")
    
    # Check for tape devices
    devices = []
    for device in ['/dev/st0', '/dev/nst0']:
        if os.path.exists(device):
            devices.append(device)
            print(f"  Found device: {device}")
    
    if not devices:
        print("  ✗ No tape devices found")
        return False
    
    # Test access to first device
    device = devices[0]
    try:
        # Try to open the device (this tests permissions)
        with open(device, 'rb') as f:
            pass
        print(f"  ✓ Can access {device}")
        return True
    except PermissionError:
        print(f"  ✗ Permission denied for {device}")
        return False
    except Exception as e:
        print(f"  ⚠ Cannot access {device}: {str(e)}")
        return True  # Device might be busy, but permissions are OK

def test_diagnostic_commands():
    """Test the actual diagnostic commands"""
    print("\n=== Testing Diagnostic Commands ===")
    
    device = '/dev/st0'  # Use first tape device
    
    commands = [
        ("MT Status", f"mt -f {device} status"),
        ("SCSI Inquiry", f"sg_inq {device}"),
        ("SCSI VPD Serial", f"sg_vpd -p sn {device}"),
        ("List SCSI Devices", "lsscsi | grep tape"),
        ("TapeInfo", f"tapeinfo -f {device}"),
        ("Position Tell", f"mt -f {device} tell"),
    ]
    
    results = []
    for name, cmd in commands:
        success = test_command(name, cmd)
        results.append((name, success))
    
    # Summary
    print(f"\n=== Test Summary ===")
    passed = sum(1 for _, success in results if success)
    total = len(results)
    print(f"Passed: {passed}/{total}")
    
    for name, success in results:
        status = "✓" if success else "✗"
        print(f"  {status} {name}")

def test_required_tools():
    """Test if required diagnostic tools are available"""
    print("\n=== Testing Required Tools ===")
    
    tools = [
        ("mt", "mt --version"),
        ("sg_inq", "sg_inq --version"),
        ("sg_vpd", "sg_vpd --version"),
        ("sg_logs", "sg_logs --version"),
        ("lsscsi", "lsscsi --version"),
        ("tapeinfo", "tapeinfo --help"),
    ]
    
    for tool, cmd in tools:
        success = test_command(f"{tool} availability", cmd)

if __name__ == "__main__":
    print("LTFS GUI Diagnostics Test")
    print("=" * 40)
    
    # Test required tools
    test_required_tools()
    
    # Test tape device access
    test_tape_device_access()
    
    # Test diagnostic commands
    test_diagnostic_commands()
    
    print("\n" + "=" * 40)
    print("Test completed. Check results above.")
