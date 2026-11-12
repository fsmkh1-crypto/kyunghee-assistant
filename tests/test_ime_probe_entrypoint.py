"""The offline diagnostic must branch before importing the real app profile."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class OfflineImeEntrypointTests(unittest.TestCase):
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
