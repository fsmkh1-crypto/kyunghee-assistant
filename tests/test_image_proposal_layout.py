"""Run the packaged approval fixture in fresh interpreters at each Tk DPI."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


def _probe(dpi):
    import tkinter as tk
    from types import SimpleNamespace
    from assistant_ai.config import AISettings
    from assistant_ai.ui import AssistantWindows

    root = tk.Tk()
    root.withdraw()
    root.tk.call("tk", "scaling", dpi / 72)
    errors = []
    root.report_callback_exception = lambda *error: errors.append(str(error))
    service = SimpleNamespace(load_settings=lambda: AISettings())
    image_path = Path(__file__).resolve().parents[1] / "assets" / "rest" / "rest_01.png"
    owner = AssistantWindows(root, service, context=lambda: {}, dispatch=lambda *_: None,
                             chat_work_area=lambda *_: (0, 0, 640, 360),
                             image_preview=lambda _ref: image_path)
    try:
        owner.show_image_proposal({
            "id": "layout-probe", "status": "pending",
            "summary": "이미지 변경 확인 " * 30,
            "scope": "변경 범위를 확인한 뒤 적용합니다. " * 30,
            "before_preview_ref": "before", "after_preview_ref": "after",
        })
        window = owner._extra_windows[-1]
        for geometry in (None, "360x240", "616x336", "360x240"):
            if geometry:
                window.geometry(geometry)
            root.update()
            canvas = window.content_canvas
            assert canvas.winfo_viewable()
            assert canvas.winfo_height() > 1
            for button in (window.apply_button, window.cancel_button, window.undo_button):
                x = button.winfo_rootx() - window.winfo_rootx()
                y = button.winfo_rooty() - window.winfo_rooty()
                assert button.winfo_viewable(), button.cget("text")
                assert 0 <= x and x + button.winfo_width() <= window.winfo_width()
                assert 0 <= y and y + button.winfo_height() <= window.winfo_height()
            heartbeat = []
            root.after(1, lambda: heartbeat.append(True))
            root.after(25, root.quit)
            root.mainloop()
            assert heartbeat, "layout blocked the event loop"
        assert not errors, errors
    finally:
        owner.close()
        root.destroy()


@unittest.skipUnless(os.name == "nt" or os.environ.get("DISPLAY"), "Tk display required")
class ImageProposalLayoutTests(unittest.TestCase):
    def test_long_packaged_fixture_finishes_at_each_fresh_root_dpi(self):
        # A geometry feedback regression must fail with a bounded timeout,
        # rather than hang the rest of the Windows test/build job.
        for dpi in (96, 120, 144, 192):
            with self.subTest(dpi=dpi), tempfile.TemporaryDirectory() as profile:
                env = dict(os.environ, APPDATA=profile, PYSTRAY_BACKEND="dummy")
                result = subprocess.run(
                    [sys.executable, "-c",
                     "from tests.test_image_proposal_layout import _probe; _probe(int(__import__('sys').argv[1]))",
                     str(dpi)],
                    cwd=Path(__file__).resolve().parents[1], env=env,
                    capture_output=True, text=True, timeout=20,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
