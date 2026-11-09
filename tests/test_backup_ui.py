"""Behavioral panel tests; use a virtual display on Linux, real Tk on Windows."""
from dataclasses import asdict
import json
from pathlib import Path
import tempfile
import tkinter as tk
import unittest
from unittest.mock import Mock, patch

from backup_ui import open_backup_panel
from settings import UserSettings
from user_data_backup import create_backup


class BackupPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.root = tk.Tk()
            cls.root.withdraw()
        except tk.TclError:
            raise unittest.SkipTest("Tk display unavailable")

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.profile = self.base / "profile"
        self.profile.mkdir()
        (self.profile / "settings.json").write_text(json.dumps(asdict(UserSettings(always_on_top=True))))
        self.archive = self.base / "backup.seunga-backup.zip"
        create_backup(self.profile, self.archive, ("settings",))
        self.ready, self.complete, self.failed = Mock(return_value=True), Mock(), Mock()
        self.panel = open_backup_panel(self.root, data_dir=self.profile,
                                       before_restore=self.ready, on_restore_complete=self.complete,
                                       after_restore_failure=self.failed)

    def tearDown(self):
        self.panel.destroy()
        self.root.withdraw()
        self.temp.cleanup()

    def choose(self):
        with patch("backup_ui.filedialog.askopenfilename", return_value=str(self.archive)):
            self.panel._choose_restore()

    def apply(self):
        self.panel._restore()
        def find(widget):
            for child in widget.winfo_children():
                if child.winfo_class() == "TButton" and child.cget("text") == "복원 후 앱 종료":
                    return child
                result = find(child)
                if result:
                    return result
        return find(self.panel)

    def test_restore_preview_and_cancel_do_not_write_profile(self):
        original = (self.profile / "settings.json").read_bytes()
        self.choose()
        self.assertFalse((self.profile / "backups").exists())
        self.assertEqual((self.profile / "settings.json").read_bytes(), original)
        with patch("backup_ui.messagebox.askokcancel", return_value=False):
            self.apply().invoke()
        self.ready.assert_not_called()
        self.complete.assert_not_called()
        self.assertFalse((self.profile / "backups").exists())

    def test_busy_guard_prevents_restore_and_closed_callbacks_enable_success(self):
        self.choose()
        self.ready.return_value = False
        with patch("backup_ui.messagebox.askokcancel", return_value=True), patch("backup_ui.messagebox.showerror"):
            self.apply().invoke()
        self.complete.assert_not_called()
        self.assertFalse((self.profile / "backups").exists())
        self.ready.return_value = True
        (self.profile / "settings.json").write_text(json.dumps(asdict(UserSettings(always_on_top=False))))
        with patch("backup_ui.messagebox.askokcancel", return_value=True):
            self.apply().invoke()
        self.complete.assert_called_once()
        self.failed.assert_not_called()
        self.assertTrue(json.loads((self.profile / "settings.json").read_text())["always_on_top"])
        self.assertTrue(self.complete.call_args.args[0].recovery_backup.is_file())

    def test_restore_requires_full_lifecycle_callbacks(self):
        self.panel.destroy()
        self.panel = open_backup_panel(self.root, data_dir=self.profile)
        self.choose()
        self.assertIn("disabled", self.panel.restore_button.state())

    def test_actions_remain_visible_in_small_window(self):
        self.root.deiconify()
        self.panel.geometry("580x540+0+0")
        self.root.update()
        self.assertTrue(self.panel.status.winfo_ismapped())
        self.assertLessEqual(self.panel.status.winfo_rooty() + self.panel.status.winfo_height(),
                             self.panel.winfo_rooty() + self.panel.winfo_height())
        self.assertTrue(self.panel.restore_button.winfo_ismapped())
        self.assertGreater(float(self.panel.canvas.cget("scrollregion").split()[3]), self.panel.canvas.winfo_height())


if __name__ == "__main__":
    unittest.main()
