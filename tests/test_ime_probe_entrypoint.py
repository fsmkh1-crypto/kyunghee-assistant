"""The offline diagnostic must branch before importing the real app profile."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class OfflineImeEntrypointTests(unittest.TestCase):
    def test_cp1252_console_preserves_unavailable_exit_and_unicode_report_path(self):
        repo = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            untouched_profile = root / "personal-profile-must-not-be-created"
            report_path = root / "한글 진단 ‘가’.json"
            environment = dict(os.environ, APPDATA=str(untouched_profile), PYTHONDONTWRITEBYTECODE="1",
                               PYTHONIOENCODING="cp1252:strict")
            # Exercise main's real report/console/exit path on every OS without
            # opening a Windows GUI or injecting input during the unit suite.
            script = (
                "import sys; from types import SimpleNamespace; "
                "from tools import probe_windows_ime as probe; "
                "probe.os = SimpleNamespace(name='unsupported_test_platform'); "
                "raise SystemExit(probe.main(['--report', sys.argv[1]]))"
            )
            result = subprocess.run(
                [sys.executable, "-c", script, str(report_path)],
                cwd=repo, env=environment, capture_output=True, text=True,
                encoding="cp1252", timeout=15,
            )
            self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
            summary = json.loads(result.stdout)
            self.assertEqual(summary["status"], "unavailable")
            self.assertEqual(summary["report"], str(report_path))
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "unavailable")
            self.assertEqual(report["reason"], summary["reason"])
            self.assertEqual(report["real_api_calls"], 0)
            self.assertEqual(report["network_attempts"], 0)
            self.assertFalse(untouched_profile.exists())

    @unittest.skipIf(os.name == "nt", "Active Windows input is exercised separately by the isolated CI probe")
    def test_unavailable_platform_writes_report_without_opening_user_profile(self):
        repo = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            untouched_profile = root / "personal-profile-must-not-be-created"
            report_path = root / "offline-ime.json"
            environment = dict(os.environ, APPDATA=str(untouched_profile), PYTHONDONTWRITEBYTECODE="1")
            result = subprocess.run(
                [sys.executable, str(repo / "desktop_gallery_final.py"),
                 "--ime-self-test", str(report_path)],
                cwd=repo, env=environment, capture_output=True, text=True,
                encoding="utf-8", timeout=15,
            )
            self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "unavailable")
            self.assertEqual(report["real_api_calls"], 0)
            self.assertEqual(report["network_attempts"], 0)
            self.assertFalse(untouched_profile.exists(), "The real app profile was initialized by the diagnostic")


if __name__ == "__main__":
    unittest.main()
