"""Real editor geometry in isolated interpreters; no timer, tray, or network."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


def _probe(dpi, framed_client=False):
    import tkinter as tk
    from tkinter import font as tkfont
    import traceback

    from PIL import Image
    from desktop_gallery import GalleryDesktopApp
    from named_image_sets import NamedImageSetStore
    from named_set_editor import NamedSetEditor
    from windows_display import enable_per_monitor_dpi_awareness

    enable_per_monitor_dpi_awareness()
    root = tk.Tk()
    root.withdraw()
    root.tk.call("tk", "scaling", dpi / 72)
    callback_errors = []
    root.report_callback_exception = lambda *error: callback_errors.append("".join(traceback.format_exception(*error)))
    # Use the production gallery's styles and thumbnail loader without
    # starting a timer whose idle-input events could replace test content.
    app = GalleryDesktopApp.__new__(GalleryDesktopApp)
    app.root = root
    families = {name.casefold(): name for name in tkfont.families(root)}
    preferred = (app.FONT_FAMILY, "Malgun Gothic", "맑은 고딕", "Noto Sans CJK KR", "Segoe UI", "DejaVu Sans", "Arial")
    app.FONT_FAMILY = next((families[name.casefold()] for name in preferred if name.casefold() in families), "Arial")
    app._gallery_thumb_cache = {}
    app._best_work_area = lambda *_args: (0, 0, 640, 480)
    if framed_client:
        # Windows' font metrics can wrap the three actions onto two rows,
        # unlike the fonts installed on a Linux runner. Wider padding keeps
        # real text/buttons while exercising that layout on either platform.
        original_button = app._button

        def wider_button(*args, **kwargs):
            button = original_button(*args, **kwargs)
            button.configure(padx=35)
            return button

        app._button = wider_button
    editor = None

    def settle(stage):
        # Flush before pumping Tk: the parent timeout then identifies the
        # stage of any Configure/scroll feedback loop.
        print(f"dpi={dpi} stage={stage}", flush=True)
        root.update()
        assert not callback_errors, callback_errors

    def inside(widget, parent):
        label = str(widget)
        assert widget.winfo_viewable(), (label, "not viewable")
        x = widget.winfo_rootx() - parent.winfo_rootx()
        y = widget.winfo_rooty() - parent.winfo_rooty()
        assert 0 <= x and x + widget.winfo_width() <= parent.winfo_width(), (
            label, "horizontal clipping", x, widget.winfo_width(), parent.winfo_width())
        assert 0 <= y and y + widget.winfo_height() <= parent.winfo_height(), (
            label, "vertical clipping", y, widget.winfo_height(), parent.winfo_height())

    def footer(buttons):
        assert editor.winfo_width() <= 616, editor.geometry()
        assert editor.winfo_height() <= 456, editor.geometry()
        inside(editor.canvas, editor)
        minimum = editor.selectors["profile"].winfo_reqheight() + 16
        assert editor.canvas.winfo_height() >= minimum, (
            "No usable assignment viewport", editor.canvas.winfo_height(), minimum, editor.status.get())
        for button in buttons:
            inside(button, editor)
            assert button.winfo_width() >= button.winfo_reqwidth(), (
                button.cget("text"), "width", button.winfo_width(), button.winfo_reqwidth())
            assert button.winfo_height() >= button.winfo_reqheight(), (
                button.cget("text"), "height", button.winfo_height(), button.winfo_reqheight())
            x = button.winfo_rootx() + button.winfo_width() // 2
            y = button.winfo_rooty() + button.winfo_height() // 2
            assert root.winfo_containing(x, y) is button, (button.cget("text"), "covered")
        heartbeat = []
        root.after(1, lambda: heartbeat.append(True))
        root.after(25, root.quit)
        root.mainloop()
        assert heartbeat, "layout blocked the event loop"
        assert not callback_errors, callback_errors

    try:
        with tempfile.TemporaryDirectory(prefix="seunga-editor-layout-") as directory:
            base = Path(directory)
            paths = []
            for index, (role, _caption) in enumerate(app.IMAGE_ROWS):
                path = base / (role + ".png")
                Image.new("RGBA", (30, 40), (index * 20, 80, 140, 255)).save(path)
                paths.append(path)
            saved, applied = [], []
            store = NamedImageSetStore(base / "profile" / "image_sets")
            editor = NamedSetEditor(
                app, store, paths, on_saved=saved.append,
                on_apply=lambda set_id: (applied.append(set_id), {"status": "applied"})[1],
            )
            if framed_client:
                # Linux's Xvfb has no native window decorations. Exercise a
                # smaller client too, reserving room for a high-DPI Windows
                # caption and borders within the same 640x480 work area.
                editor.geometry("584x376")
            settle("initial")
            footer((editor.review_button, editor.save_button, editor.cancel_button))
            assert len(editor._photos) == 10
            assert editor.progress.get().startswith("상황 10/10 배정")

            editor.focus_force()
            editor.name_entry.focus_set()
            settle("keyboard start")
            inside(editor.name_entry, editor.canvas)
            profile = editor.selectors["profile"]
            reached = set()
            for _step in range(40):
                focused = root.focus_get()
                if focused in editor.selectors.values():
                    inside(focused, editor.canvas)
                    reached.add(focused)
                if focused is editor.add_button:
                    inside(focused, editor.canvas)
                if focused is profile:
                    break
                assert focused is not None, "keyboard focus left the editor"
                focused.event_generate("<Tab>")
                root.update()
            assert root.focus_get() is profile, "Tab could not reach the last role"
            assert reached == set(editor.selectors.values()), "Tab skipped an assignment"
            assert editor.canvas.yview()[0] > 0, "last role focus did not scroll"
            inside(profile, editor.canvas)
            footer((editor.review_button, editor.save_button, editor.cancel_button))

            # The header now shares the scrollable body. Returning by keyboard
            # must reveal both file addition and the name field, not focus
            # controls above the visible canvas.
            returned_to_add = False
            for _step in range(40):
                focused = root.focus_get()
                assert focused is not None, "reverse navigation lost focus"
                if focused is editor.add_button:
                    returned_to_add = True
                    inside(focused, editor.canvas)
                if focused is editor.name_entry:
                    inside(focused, editor.canvas)
                    break
                focused.event_generate("<Shift-Tab>" if os.name == "nt" else "<ISO_Left_Tab>")
                root.update()
            assert returned_to_add, "reverse Tab skipped image addition"
            assert root.focus_get() is editor.name_entry, "reverse Tab could not return to the name"
            footer((editor.review_button, editor.save_button, editor.cancel_button))

            # A closed selector's default Tk wheel binding must not silently
            # change an assignment while the user scrolls the role list.
            selector = editor.selectors["default"]
            selector.focus_set()
            editor.canvas.yview_moveto(0)
            settle("selector wheel")
            assignments = {role: variable.get() for role, variable in editor.assignments.items()}
            before = editor.canvas.yview()[0]
            selector.event_generate("<MouseWheel>", delta=-120)
            root.update()
            assert editor.canvas.yview()[0] > before, "selector wheel did not scroll the roles"
            assert {role: variable.get() for role, variable in editor.assignments.items()} == assignments, (
                "scrolling a closed selector changed its assignment")

            long_name = "승아와함께하는새로운하루" * 6 + "승아와함께하는새로운하루"[:8]
            assert len(long_name) == 80
            editor.name.set(long_name)
            settle("long name")
            footer((editor.review_button, editor.save_button, editor.cancel_button))
            editor.status_text.focus_set()
            root.update()
            for _step in range(6):
                focused = root.focus_get()
                assert focused is not None, "status navigation lost focus"
                focused.event_generate("<Tab>")
                root.update()
                assert root.focus_get() is not editor.status_text, "read-only status trapped Tab navigation"
                if root.focus_get() is editor.review_button:
                    break
            assert root.focus_get() is editor.review_button, "Tab could not reach the review action"
            editor.review_button.focus_set()
            editor.review_button.event_generate("<Return>")
            settle("long preview")
            assert editor.plan is not None, editor.status.get()
            assert editor.plan.name == long_name
            assert editor.save_button.cget("state") == "normal"
            assert editor.status_text.cget("state") == "disabled"
            assert editor.status_text.get("1.0", "end-1c") == editor.status.get()
            assert long_name in editor.status_text.get("1.0", "end-1c")
            role_view = editor.canvas.yview()
            editor.status_text.event_generate("<MouseWheel>", delta=-120)
            root.update()
            assert editor.canvas.yview() == role_view, "status scrolling moved the role assignments"
            editor.status_text.yview_moveto(1)
            root.update()
            assert editor.status_text.dlineinfo("end-2c") is not None, "status ending is inaccessible"
            footer((editor.review_button, editor.save_button, editor.cancel_button))

            editor.save_button.focus_set()
            editor.save_button.event_generate("<Return>")
            settle("long saved status")
            assert editor.saved_set is not None, editor.status.get()
            assert saved == [editor.saved_set]
            assert store.list_sets() == (editor.saved_set,)
            assert not applied, "saving unexpectedly applied the set"
            footer((editor.apply_button, editor.cancel_button))
            editor.apply_button.focus_set()
            editor.apply_button.event_generate("<Return>")
            settle("long applied status")
            assert applied == [editor.saved_set.id]
            footer((editor.apply_button, editor.cancel_button))
    finally:
        if editor is not None and editor.winfo_exists():
            editor.destroy()
        for token in root.tk.splitlist(root.tk.call("after", "info")):
            root.after_cancel(token)
        root.destroy()


@unittest.skipUnless(os.name == "nt" or os.environ.get("DISPLAY"), "Tk display required")
class NamedSetEditorLayoutTests(unittest.TestCase):
    def test_small_work_area_keeps_actions_and_keyboard_assignments_accessible(self):
        for dpi in (96, 120, 144, 192):
            with self.subTest(dpi=dpi):
                self.run_probe(dpi)

    def test_high_dpi_with_native_frame_space_keeps_the_assignment_viewport(self):
        self.run_probe(192, framed_client=True)

    def run_probe(self, dpi, *, framed_client=False):
        with tempfile.TemporaryDirectory() as profile:
            env = dict(os.environ, APPDATA=profile, PYSTRAY_BACKEND="dummy")
            result = subprocess.run(
                [sys.executable, "-c",
                 "import runpy, sys; runpy.run_path(sys.argv[1])['_probe'](int(sys.argv[2]), sys.argv[3] == '1')",
                 str(Path(__file__).resolve()), str(dpi), "1" if framed_client else "0"],
                cwd=Path(__file__).resolve().parents[1], env=env,
                capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--probe":
        _probe(int(sys.argv[2]))
    else:
        unittest.main()
