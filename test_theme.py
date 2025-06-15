#!/usr/bin/python3
"""
Theme Testing Script for LTFS GUI
Helps debug theme application issues
"""

import sys
sys.path.insert(0, '.')

import tkinter as tk
from tkinter import ttk
from ltfs_gui import LTFSGui

def test_theme_application():
    """Test theme application on all components"""
    print("Creating LTFS GUI for theme testing...")
    
    root = tk.Tk()
    root.title("LTFS Theme Test")
    
    # Create the GUI
    app = LTFSGui(root)
    
    print(f"Initial theme: {app.current_theme_name.get()}")
    print(f"Dark mode variable: {app.dark_mode.get()}")
    
    # Test theme dropdown visibility
    if hasattr(app, 'theme_combo'):
        print(f"Theme dropdown is visible with options: {app.theme_combo['values']}")
        print(f"Current selection: {app.theme_combo.get()}")
    else:
        print("ERROR: Theme dropdown not found!")
    
    def test_theme_switch():
        """Test switching between themes"""
        themes_to_test = ['light', 'dark', 'blue_dark', 'high_contrast']
        
        def switch_theme(theme_index):
            if theme_index < len(themes_to_test):
                theme = themes_to_test[theme_index]
                print(f"\nSwitching to theme: {theme}")
                
                # Set theme
                app.current_theme_name.set(theme)
                app.apply_selected_theme()
                
                # Update dropdown to match
                theme_info = app.themes[theme]
                app.theme_combo.set(theme_info['name'])
                
                # Schedule next theme switch
                root.after(3000, lambda: switch_theme(theme_index + 1))
            else:
                print("\nTheme testing complete!")
                root.after(2000, root.destroy)
        
        # Start theme switching
        switch_theme(0)
    
    # Start theme testing after a short delay
    root.after(1000, test_theme_switch)
    
    # Run the GUI
    root.mainloop()
    
    print("Theme testing finished.")

if __name__ == "__main__":
    test_theme_application()

