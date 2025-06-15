#!/usr/bin/python3
"""
Test script for LTFS GUI functionality
Tests the core functionality without launching the GUI
"""

import sys
import os

# Add current directory to path for local imports
script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, script_dir)

# Test import without GUI components
try:
    import subprocess
    
    # Import only the backend components to avoid tkinter requirements
    import importlib.util
    spec = importlib.util.spec_from_file_location("ltfs_backend", os.path.join(script_dir, "ltfs_gui.py"))
    ltfs_backend = importlib.util.module_from_spec(spec)
    
    # Mock tkinter to avoid import errors
    class MockTkinter:
        def __getattr__(self, name):
            return self
        def __call__(self, *args, **kwargs):
            return self
    
    # Temporarily replace tkinter in sys.modules
    original_modules = {}
    tkinter_modules = ['tkinter', 'tkinter.ttk', 'tkinter.messagebox', 'tkinter.filedialog', 'tkinter.scrolledtext']
    
    for module in tkinter_modules:
        if module in sys.modules:
            original_modules[module] = sys.modules[module]
        sys.modules[module] = MockTkinter()
    
    # Now load the backend
    spec.loader.exec_module(ltfs_backend)
    
    # Get the LTFSManager class
    LTFSManager = ltfs_backend.LTFSManager
    
except Exception as e:
    print(f"Error importing LTFS backend: {e}")
    print("Falling back to basic subprocess tests...")
    LTFSManager = None

def test_ltfs_tools():
    """Test if LTFS tools are available"""
    print("=== Testing LTFS Tools ===")
    
    tools = ['ltfs', 'mkltfs', 'mt']
    for tool in tools:
        try:
            result = subprocess.run(['which', tool], capture_output=True, text=True)
            if result.returncode == 0:
                print(f"✓ {tool}: {result.stdout.strip()}")
            else:
                print(f"✗ {tool}: Not found")
        except Exception as e:
            print(f"✗ {tool}: Error - {e}")

def test_ltfs_manager():
    """Test the LTFSManager class"""
    print("\n=== Testing LTFS Manager ===")
    
    if LTFSManager is None:
        print("✗ LTFSManager not available - LTFS GUI import failed")
        return False
    
    try:
        manager = LTFSManager()
        print("✓ LTFSManager created successfully")
        
        # Test drive detection
        drives = manager.refresh_drives()
        print(f"✓ Found {len(drives)} tape drives:")
        
        actual_drives = [d for d in drives if not any(x in d for x in ['stdin', 'stdout', 'stderr'])]
        for drive in actual_drives:
            print(f"  - {drive}")
        
        # Test version command
        success, stdout, stderr = manager.run_command("ltfs --version")
        if success:
            print(f"✓ LTFS version: {stdout.strip()}")
        else:
            print(f"✗ Failed to get LTFS version: {stderr}")
        
        # Test mounted tapes
        mounted = manager.list_mounted_tapes()
        if mounted.strip():
            print(f"✓ Currently mounted tapes:\n{mounted}")
        else:
            print("✓ No LTFS tapes currently mounted")
        
        return True
    except Exception as e:
        print(f"✗ Error testing LTFSManager: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_permissions():
    """Test tape device permissions"""
    print("\n=== Testing Permissions ===")
    
    import os
    import stat
    
    tape_devices = ['/dev/st0', '/dev/nst0']
    
    for device in tape_devices:
        if os.path.exists(device):
            stat_info = os.stat(device)
            mode = stat_info.st_mode
            
            if stat.S_ISCHR(mode):
                print(f"✓ {device} is a character device")
                
                # Check if readable
                if os.access(device, os.R_OK):
                    print(f"✓ {device} is readable")
                else:
                    print(f"⚠ {device} is not readable (may need to be in 'tape' group)")
                
                # Check if writable
                if os.access(device, os.W_OK):
                    print(f"✓ {device} is writable")
                else:
                    print(f"⚠ {device} is not writable (may need to be in 'tape' group)")
            else:
                print(f"✗ {device} is not a character device")
        else:
            print(f"✗ {device} does not exist")

def main():
    print("LTFS GUI Functionality Test")
    print("===========================")
    
    test_ltfs_tools()
    manager_ok = test_ltfs_manager()
    test_permissions()
    
    print("\n=== Summary ===")
    if manager_ok:
        print("✓ LTFS GUI should work correctly")
        print("\nTo start the GUI, run:")
        print("  ./ltfs_gui.py")
        print("\nOr:")
        print("  /usr/bin/python3 ltfs_gui.py")
    else:
        print("✗ Issues detected - check error messages above")
    
    print("\nNote: You may need to be in the 'tape' group to access tape devices.")
    print("To add yourself to the tape group:")
    print("  sudo usermod -a -G tape $USER")
    print("  (then log out and back in)")

if __name__ == "__main__":
    main()

