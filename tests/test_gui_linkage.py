import ast
from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
GUI_FILE = REPO_ROOT / "ltfs_gui.py"


class TestGuiLinkage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = GUI_FILE.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source)

    def test_no_debug_markers_remain(self):
        self.assertNotIn("DEBUG:", self.source)

    def test_buttons_have_command_or_disabled_state(self):
        missing = []

        for node in ast.walk(self.tree):
            if not isinstance(node, ast.Call):
                continue

            func = node.func
            if not isinstance(func, ast.Attribute):
                continue
            if func.attr != "Button":
                continue
            if not isinstance(func.value, ast.Name):
                continue
            if func.value.id not in {"ttk", "tk"}:
                continue

            keyword_map = {kw.arg: kw.value for kw in node.keywords if kw.arg}

            has_command = "command" in keyword_map and not (
                isinstance(keyword_map["command"], ast.Constant)
                and keyword_map["command"].value is None
            )
            is_disabled = (
                isinstance(keyword_map.get("state"), ast.Constant)
                and keyword_map["state"].value == "disabled"
            )

            if not has_command and not is_disabled:
                missing.append(node.lineno)

        self.assertEqual(
            [],
            missing,
            f"Buttons without callback linkage (or disabled state): {missing}",
        )


if __name__ == "__main__":
    unittest.main()
