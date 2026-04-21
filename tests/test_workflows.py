from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
CI_WORKFLOW = REPO_ROOT / ".github/workflows/ci.yml"
APPIMAGE_WORKFLOW = REPO_ROOT / ".github/workflows/appimage.yml"


class TestWorkflowExpectations(unittest.TestCase):
    def test_ci_workflow_exists_and_has_core_steps(self):
        self.assertTrue(CI_WORKFLOW.exists(), "Missing .github/workflows/ci.yml")
        workflow = CI_WORKFLOW.read_text(encoding="utf-8")

        for expected in [
            "python -m py_compile ltfs_gui.py",
            "python -m unittest discover -s tests -v",
            "./autogen.sh",
            "./configure",
            "make -j",
        ]:
            self.assertIn(expected, workflow)

    def test_appimage_workflow_exists_and_builds_artifacts(self):
        self.assertTrue(APPIMAGE_WORKFLOW.exists(), "Missing .github/workflows/appimage.yml")
        workflow = APPIMAGE_WORKFLOW.read_text(encoding="utf-8")

        for expected in [
            "scripts/build-appimage.sh",
            "python3-tk",
            "--appimage-extract",
            "actions/upload-artifact@v4",
            "dist/*.AppImage",
        ]:
            self.assertIn(expected, workflow)
        self.assertNotIn("actions/setup-python", workflow)


if __name__ == "__main__":
    unittest.main()
