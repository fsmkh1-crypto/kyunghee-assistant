"""Controlled Windows Unicode delivery through Tk's actual native message queue.

These tests do not type through Microsoft Korean IME or manufacture IMM result
strings. WM_UNICHAR exercises Tk's native Unicode KeyPress conversion, including
the modifier state that can make the Text class discard an IME result. Real
Korean IME composition and its timing still require separate Windows validation.
"""
import ctypes
from ctypes import wintypes
import os
from tempfile import TemporaryDirectory
import traceback
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


@unittest.skipUnless(os.name == "nt", "Actual Windows Tk message queue required")
class NativeTextDeliveryTests(unittest.TestCase):
    WM_UNICHAR = 0x0109
    GA_ROOT = 2
    CONTROL_MASK = 0x0004
    # Tk 8.6 generic/tkInt.h: ALT_MASK = AnyModifier << 2, not X11 Mod1Mask.
    ALT_MASK = 0x20000

    def setUp(self):
        profile = self.enterContext(TemporaryDirectory(prefix="seunga-native-text-"))
        self.enterContext(patch.dict(os.environ, {"APPDATA": profile}))
        import tkinter as tk
        from assistant_ai.config import AISettings
        from assistant_ai.ui import AssistantWindows

        self.root = tk.Tk()
        self.addCleanup(self._destroy_root)
        self.root.withdraw()
        self.callback_errors = []
        self.root.report_callback_exception = self._record_callback_error
        settings = AISettings(enabled=True)
        self.service = SimpleNamespace(
            load_settings=lambda: settings,
            save_settings=Mock(),
            ready=lambda: True,
            recent_turns=lambda **_kwargs: [],
            cancel_chat=Mock(),
            chat=Mock(side_effect=AssertionError("Native text tests must not call an API")),
            ledger=SimpleNamespace(summary=lambda *_args: SimpleNamespace(
                estimated_cost_usd=0, reserved_cost_usd=0)),
        )
        self.owner = AssistantWindows(self.root, self.service, context=lambda: {}, dispatch=Mock())
        self.addCleanup(self.owner.close)
        self.owner.open_chat()
        self.chat = self.owner.chat_window

        self.user = ctypes.WinDLL("user32", use_last_error=True)
        self.user.GetFocus.argtypes = []
        self.user.GetFocus.restype = wintypes.HWND
        self.user.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
        self.user.GetAncestor.restype = wintypes.HWND
        self.user.GetKeyboardState.argtypes = [ctypes.POINTER(wintypes.BYTE)]
        self.user.GetKeyboardState.restype = wintypes.BOOL
        self.user.SetKeyboardState.argtypes = [ctypes.POINTER(wintypes.BYTE)]
        self.user.SetKeyboardState.restype = wintypes.BOOL
        self.user.PostMessageW.argtypes = [
            wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
        ]
        self.user.PostMessageW.restype = wintypes.BOOL

        # Focus only this test's window. No global SendInput or keyboard-layout
        # changes are used, and each test has its own Tk interpreter.
        self.root.after(0, self.chat.input.focus_force)
        self._run_until(self._input_has_focus, "The test composer did not receive focus")

    def _destroy_root(self):
        for token in self.root.tk.splitlist(self.root.tk.call("after", "info")):
            self.root.after_cancel(token)
        self.root.destroy()

    def _record_callback_error(self, kind, value, tb):
        self.callback_errors.append("".join(traceback.format_exception(kind, value, tb)))
        self.root.quit()

    def _run_until(self, predicate, failure):
        """Run the normal dispatcher; never nest update in a native callback."""
        complete = False
        pending = None

        def poll():
            nonlocal complete, pending
            pending = None
            if predicate():
                complete = True
                self.root.quit()
            else:
                pending = self.root.after(5, poll)

        pending = self.root.after(1, poll)
        watchdog = self.root.after(2000, self.root.quit)
        try:
            self.root.mainloop()
        finally:
            if pending is not None:
                self.root.after_cancel(pending)
            self.root.after_cancel(watchdog)
        self.assertFalse(self.callback_errors, "\n".join(self.callback_errors))
        self.assertTrue(complete, failure)

    def _input_has_focus(self):
        native_focus = self.user.GetFocus()
        return (
            self.chat.input.focus_get() == self.chat.input
            and bool(native_focus)
            and self.user.GetAncestor(native_focus, self.GA_ROOT)
            == self.user.GetAncestor(self.chat.winfo_id(), self.GA_ROOT)
        )

    def _draft(self, text, cursor="end-1c"):
        self.chat.input.delete("1.0", "end")
        self.chat.input.insert("1.0", text)
        self.chat.input.mark_set("insert", cursor)
        self.chat.input.tag_remove("sel", "1.0", "end")
        self.chat.input.edit_reset()

    def _post_unicode(self, text, *, control=True, alt=False):
        """Post native messages with a temporary keyboard state on this thread."""
        expected = [ord(char) for char in text]
        self.assertTrue(expected)
        self.assertTrue(all(codepoint > 0xFF for codepoint in expected))
        events = []
        original = (wintypes.BYTE * 256)()
        saved = False

        def observe(event):
            if event.keycode in expected:
                events.append((event.keycode, event.char, event.state, event.send_event))

        original_tags = self.chat.input.bindtags()
        observer_tag = f"{self.chat.input._w}_native_test_observer"
        observer = self.root.bind_class(observer_tag, "<KeyPress>", observe)
        # Observe before the production guard: its successful insertion returns
        # break, so a normal widget binding would never see the intercepted key.
        self.chat.input.bindtags((observer_tag, *original_tags))

        def post():
            nonlocal saved
            self.assertTrue(self._input_has_focus(), "Native focus left the test composer")
            self.assertTrue(self.user.GetKeyboardState(original), ctypes.get_last_error())
            saved = True
            keyboard = (wintypes.BYTE * 256).from_buffer_copy(original)
            # SetKeyboardState affects this GUI thread, not the global keyboard.
            # Clear left/right variants too so unrelated state cannot leak in.
            for virtual_key in (0x10, 0xA0, 0xA1, 0x11, 0xA2, 0xA3, 0x12, 0xA4, 0xA5):
                keyboard[virtual_key] &= 0x7F
            if control:
                keyboard[0x11] |= 0x80
                keyboard[0xA2] |= 0x80
            if alt:
                keyboard[0x12] |= 0x80
                keyboard[0xA4] |= 0x80
            self.assertTrue(self.user.SetKeyboardState(keyboard), ctypes.get_last_error())
            native_focus = self.user.GetFocus()
            for codepoint in expected:
                self.assertTrue(
                    self.user.PostMessageW(native_focus, self.WM_UNICHAR, codepoint, 0),
                    ctypes.get_last_error(),
                )

        post_token = self.root.after(0, post)
        try:
            self._run_until(
                lambda: len(events) >= len(expected),
                "Tk did not deliver the posted native Unicode events",
            )
        finally:
            # Restore even if a callback assertion or message-delivery timeout
            # occurs. Never call SendMessage, change the layout, or subclass a
            # native window procedure from this fixture.
            restored = not saved or bool(self.user.SetKeyboardState(original))
            self.root.after_cancel(post_token)
            self.chat.input.bindtags(original_tags)
            self.root.unbind_class(observer_tag, "<KeyPress>")
            self.root.deletecommand(observer)
            self.assertTrue(restored, "Could not restore this thread's keyboard state")

        self.assertEqual([event[0] for event in events], expected)
        self.assertEqual("".join(event[1] for event in events), text)
        for keycode, char, state, send_event in events:
            self.assertEqual(keycode, ord(char))
            # Tk exposes its native -3 Unicode marker through Boolean %E.
            self.assertTrue(send_event)
            self.assertEqual(bool(state & self.CONTROL_MASK), control)
            self.assertEqual(bool(state & self.ALT_MASK), alt)
        self.service.chat.assert_not_called()

    def test_native_focus_is_not_the_logically_focused_text_hwnd(self):
        self.assertEqual(self.chat.input.focus_get(), self.chat.input)
        self.assertNotEqual(self.user.GetFocus(), self.chat.input.winfo_id())
        self.assertEqual(
            self.user.GetAncestor(self.user.GetFocus(), self.GA_ROOT),
            self.user.GetAncestor(self.chat.winfo_id(), self.GA_ROOT),
        )

    def test_control_modified_native_last_jamo_is_preserved(self):
        self._draft("근데 느림...")
        self._post_unicode("ㅋ")
        self.assertEqual(self.chat.input.get("1.0", "end-1c"), "근데 느림...ㅋ")

    def test_native_unicode_preserves_codepoints_with_and_without_control(self):
        for control in (False, True):
            for char in ("ㅋ", "한", "あ", "א", "\u0301", "\U0001f600"):
                with self.subTest(control=control, codepoint=f"U+{ord(char):04X}"):
                    self._draft("앞")
                    self._post_unicode(char, control=control)
                    self.assertEqual(self.chat.input.get("1.0", "end-1c"), "앞" + char)

    def test_alt_modified_native_unicode_is_preserved(self):
        self._draft("앞")
        self._post_unicode("ㅋ", control=False, alt=True)
        self.assertEqual(self.chat.input.get("1.0", "end-1c"), "앞ㅋ")

    def test_native_unicode_inserts_at_cursor_and_undo_restores_draft(self):
        self._draft("앞뒤", "1.1")
        self._post_unicode("ㅋ")
        self.assertEqual(self.chat.input.get("1.0", "end-1c"), "앞ㅋ뒤")
        self.chat.input.edit_undo()
        self.assertEqual(self.chat.input.get("1.0", "end-1c"), "앞뒤")

    def test_native_unicode_replaces_selection_as_one_undo_operation(self):
        self._draft("앞바꿀뒤", "1.1")
        self.chat.input.tag_add("sel", "1.1", "1.3")
        self._post_unicode("ㅋ")
        self.assertEqual(self.chat.input.get("1.0", "end-1c"), "앞ㅋ뒤")
        self.chat.input.edit_undo()
        self.assertEqual(self.chat.input.get("1.0", "end-1c"), "앞바꿀뒤")

    def test_native_identical_commits_are_not_deduplicated(self):
        self._draft("ㅋ")
        self._post_unicode("ㅋㅋ")
        self.assertEqual(self.chat.input.get("1.0", "end-1c"), "ㅋㅋㅋ")


if __name__ == "__main__":
    unittest.main()
