"""Exercise the real mixin without opening Tk windows or contacting an API."""
from collections import deque
import importlib.util
import os
from pathlib import Path
import queue
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


@unittest.skipUnless(importlib.util.find_spec("pystray"), "Desktop dependencies not installed")
class DesktopAssistantFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        with patch.dict(os.environ, {"APPDATA": cls.directory.name, "PYSTRAY_BACKEND": "dummy"}):
            from assistant_ai.desktop import DesktopAssistantMixin
        class LocalTimer:
            def _update_dialogue(self):
                self.local_calls.append("periodic")
                self.last_dialogue_at = 100
            def _cycle_message(self, event=None):
                self.local_calls.append("manual")
        class Desktop(DesktopAssistantMixin, LocalTimer):
            pass
        cls.desktop_type = Desktop

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def setUp(self):
        self.app = app = self.desktop_type.__new__(self.desktop_type)
        app.local_calls = []
        app.last_dialogue_at = 0
        app.last_work_mode = "normal"
        app._assistant_periodic_due = False
        app._assistant_pending = None
        app._assistant_shutdown = threading.Event()
        app._assistant_events = deque(maxlen=40)
        app._assistant_recent_dialogue = deque(maxlen=12)
        app._assistant_last_attempt = app._assistant_last_periodic = float("-inf")
        app._chat_phase = "idle"
        app.current_page = "timer"
        app.preferences = SimpleNamespace(show_message=True)
        app.root, app.speech = Mock(), Mock()
        app._apply_widget_appearance = Mock()
        app._open_assistant_chat = Mock()
        app._break_notifications_suppressed = lambda: False
        app.ui_commands = queue.Queue()
        app._assistant_tools = SimpleNamespace(context=lambda: {
            "date": "2026-11-09", "is_away": False, "workday_mode": "normal", "break_reminders_enabled_today": True,
        })
        app._assistant_service = Mock()
        app._assistant_service.revision = 0
        app._assistant_service.can_proactively_speak.return_value = True

    def test_local_dialogue_is_displayed_before_network_and_survives_failure(self):
        app = self.app
        entered, release = threading.Event(), threading.Event()
        def pending(*args, **kwargs):
            entered.set()
            if not release.wait(3):
                raise RuntimeError("test did not release worker")
            raise OSError("fake network timeout")
        app._assistant_service.proactive.side_effect = pending
        app._update_dialogue()
        self.assertEqual(app.local_calls, ["periodic"])
        self.assertTrue(app._assistant_periodic_due)
        app._request_proactive("periodic")
        try:
            self.assertTrue(entered.wait(2))
            self.assertEqual(app.local_calls, ["periodic"])
        finally:
            release.set()
        app.ui_commands.get(timeout=3)()
        self.assertEqual(app.local_calls, ["periodic"])
        app.speech.configure.assert_not_called()

    def test_new_conversation_discards_late_proactive_reply(self):
        app = self.app
        app._assistant_service.proactive.return_value = "늦은 응원"
        app._request_proactive("return")
        finish = app.ui_commands.get(timeout=3)
        app._cancel_proactive()
        finish()
        app.speech.configure.assert_not_called()
        self.assertEqual(app._assistant_events[-1]["event"], "return")

    def test_speech_click_always_opens_chat_instead_of_rotating_lines(self):
        for enabled in (False, True):
            self.app._assistant_service.can_proactively_speak.return_value = enabled
            self.app._cycle_message()
        self.assertEqual(self.app._open_assistant_chat.call_count, 2)
        self.assertEqual(self.app.local_calls, [])


if __name__ == "__main__":
    unittest.main()
