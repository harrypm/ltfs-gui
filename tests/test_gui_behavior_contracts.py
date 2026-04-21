import ast
from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
GUI_FILE = REPO_ROOT / "ltfs_gui.py"


class TestGuiBehaviorContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = GUI_FILE.read_text(encoding="utf-8")
        cls.lines = cls.source.splitlines()
        cls.tree = ast.parse(cls.source)

        cls.gui_class = None
        for node in cls.tree.body:
            if isinstance(node, ast.ClassDef) and node.name == "LTFSGui":
                cls.gui_class = node
                break

        if cls.gui_class is None:
            raise AssertionError("LTFSGui class not found in ltfs_gui.py")

    def _method_source(self, method_name: str) -> str:
        for node in self.gui_class.body:
            if isinstance(node, ast.FunctionDef) and node.name == method_name:
                return "\n".join(self.lines[node.lineno - 1 : node.end_lineno])
        raise AssertionError(f"Method not found: {method_name}")

    def test_apply_compression_uses_mt_command(self):
        method = self._method_source("apply_compression_settings")
        self.assertIn("mt -f {device} compression", method)
        self.assertNotIn("simulate", method.lower())

    def test_get_current_compression_uses_mt_status(self):
        method = self._method_source("get_current_compression")
        self.assertIn("mt -f {device} status", method)
        self.assertNotIn("simulate", method.lower())

    def test_get_selected_device_uses_selection_resolver(self):
        method = self._method_source("get_selected_device")
        self.assertIn("self._resolve_device_from_selection(selected_display)", method)
        self.assertIn("drive_hardware_info", method)
        self.assertNotIn("drive_info['primary_device']", method)
    
    def test_diagnostics_actions_use_resolved_device_path(self):
        helper = self._method_source("_get_selected_diagnostics_device")
        self.assertIn("self.diagnostics_device_var.get()", helper)
        self.assertIn("self._resolve_device_from_selection(selected_value)", helper)
        
        method = self._method_source("check_drive_status")
        self.assertIn("self._get_selected_diagnostics_device()", method)
        self.assertNotIn("self.diagnostics_device_var.get()", method)
    
    def test_mam_actions_use_resolved_device_path(self):
        helper = self._method_source("_get_selected_mam_device")
        self.assertIn("self.mam_device_var.get()", helper)
        self.assertIn("self._resolve_device_from_selection(selected_value)", helper)
        
        method = self._method_source("read_mam_attributes")
        self.assertIn("self._get_selected_mam_device()", method)
        self.assertNotIn("self.mam_device_var.get()", method)


if __name__ == "__main__":
    unittest.main()
