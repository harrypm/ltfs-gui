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
            "strategy:",
            "matrix:",
            "windows-latest",
            "macos-latest",
            "./autogen.sh",
            "./configure",
            "make -j",
            "libfuse2 libfuse-dev",
            "actions/cache@v4",
            "ccache",
        ]:
            self.assertIn(expected, workflow)

    def test_appimage_workflow_exists_and_builds_artifacts(self):
        self.assertTrue(APPIMAGE_WORKFLOW.exists(), "Missing .github/workflows/appimage.yml")
        workflow = APPIMAGE_WORKFLOW.read_text(encoding="utf-8")

        for expected in [
            "scripts/build-appimage.sh",
            "python3-tk",
            "Resolve pip cache directory",
            "Cache pip downloads",
            "Cache appimagetool binary",
            "--appimage-extract",
            "actions/upload-artifact@v4",
            "dist/*.AppImage",
            "squashfs-root/ltfs-gui.png",
            "squashfs-root/usr/lib/libfuse.so.2",
            "APPIMAGETOOL_BIN",
        ]:
            self.assertIn(expected, workflow)
        self.assertNotIn("actions/setup-python", workflow)
    def test_appimage_build_script_uses_pinned_and_vendored_dependencies(self):
        script = (REPO_ROOT / "scripts/build-appimage.sh").read_text(encoding="utf-8")
        app_run = (REPO_ROOT / "packaging/appimage/AppRun").read_text(encoding="utf-8")
        requirements = (REPO_ROOT / "packaging/appimage/requirements.txt").read_text(encoding="utf-8")
        checksums = (REPO_ROOT / "vendor/appimagetool/SHA256SUMS").read_text(encoding="utf-8")

        for expected in [
            "ICON_BASENAME",
            "packaging/appimage/${ICON_BASENAME}",
            "ln -sf \"${ICON_BASENAME}\" \"${APPDIR}/.DirIcon\"",
            "APPIMAGETOOL_VERSION",
            "vendor/appimagetool",
            "APPIMAGETOOL_CHECKSUMS",
            "packaging/appimage/requirements.txt",
            "releases/download/${APPIMAGETOOL_VERSION}",
            "sha256sum",
            "libfuse.so.2",
            "python_has_tk",
            "/usr/bin/python3",
            "if [[ -n \"${APPIMAGETOOL_BIN}\" ]] && [[ ! -x \"${APPIMAGETOOL_BIN}\" ]]; then",
            "dirname \"${APPIMAGETOOL_BIN}\"",
        ]:
            self.assertIn(expected, script)

        self.assertNotIn("releases/download/continuous", script)
        self.assertIn("LD_LIBRARY_PATH", app_run)
        self.assertIn("pyinstaller==", requirements)
        self.assertIn("appimagetool-x86_64.AppImage", checksums)
        self.assertIn("appimagetool-aarch64.AppImage", checksums)


if __name__ == "__main__":
    unittest.main()
