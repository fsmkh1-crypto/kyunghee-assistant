from __future__ import annotations

from dataclasses import replace
import os
from queue import SimpleQueue
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from assistant_ai.ui_helpers import clamp_geometry


class WindowGeometryTests(unittest.TestCase):
    def test_left_monitor_and_small_work_area(self):
        self.assertEqual(clamp_geometry(-2200, -80, 700, 600, (-1920, 0, 0, 1080)), (-1908, 12, 700, 600))
        self.assertEqual(clamp_geometry(5000, 5000, 900, 820, (0, 0, 640, 480)), (12, 12, 616, 456))


@unittest.skipUnless(os.name == "nt" or os.environ.get("DISPLAY"), "Tk display required")
class AssistantInteractionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import tkinter as tk
        cls.root = tk.Tk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        for event_id in cls.root.tk.splitlist(cls.root.tk.call("after", "info")):
            cls.root.tk.call("after", "cancel", event_id)
        cls.root.destroy()

    def setUp(self):
        from assistant_ai.config import AISettings
        from assistant_ai.ui import AssistantWindows
        self.settings = AISettings(enabled=True)
        self.turns = []
        self.states = []
        self.service = SimpleNamespace(
            load_settings=lambda: self.settings, ready=lambda: True,
            recent_turns=lambda **_: self.turns,
            cancel_chat=Mock(), action_receipts=Mock(return_value=[]),
            local_status=Mock(return_value="집중 10분"), weather_report=Mock(return_value="서울시 날씨"),
            ledger=SimpleNamespace(summary=lambda *_: SimpleNamespace(estimated_cost_usd=0.0, reserved_cost_usd=0.0)),
        )
        self.service.save_settings = lambda settings, **_: setattr(self, "settings", settings)
        self.owner = AssistantWindows(self.root, self.service, context=lambda: {}, dispatch=Mock(),
                                      on_chat_state=lambda *state: self.states.append(state))
        self.owner.open_chat()
        self.addCleanup(self.owner.close)

    def send_without_network(self, text):
        self.owner.chat_window.input.delete("1.0", "end")
        self.owner.chat_window.input.insert("1.0", text)
        with patch("assistant_ai.ui.Thread"):
            self.owner.send()
        return self.owner._request_id

    def test_cancel_allows_new_request_and_discards_old_result(self):
        first = self.send_without_network("첫 메시지")
        first_cancel = self.owner._cancel
        self.owner.cancel()
        self.assertIsNone(self.owner._cancel)
        self.assertTrue(first_cancel.is_set())
        self.service.cancel_chat.assert_called_once_with(first_cancel)
        second = self.send_without_network("다음 메시지")
        self.owner._results.put((first, "늦은 답", ""))
        self.owner._results.put((second, "최신 답", ""))
        self.owner._poll()
        self.assertEqual(self.states[-1], ("reply", "최신 답"))
        self.assertNotIn(("reply", "늦은 답"), self.states)

    def test_failure_restores_message_even_after_history_user_turn_was_saved(self):
        request_id = self.send_without_network("길게 작성한 메시지")
        self.turns = [SimpleNamespace(created_at="", user="길게 작성한 메시지", assistant=None)]
        self.owner._results.put((request_id, None, "연결 실패"))
        self.owner._poll()
        self.assertEqual(self.owner.chat_window.input.get("1.0", "end-1c"), "길게 작성한 메시지")
        self.assertEqual(self.owner._failed_request, (request_id, "길게 작성한 메시지"))

    def test_failure_preserves_new_draft_and_retry_preserves_receipt_identity(self):
        request_id = self.send_without_network("원래 요청")
        self.owner.chat_window.input.insert("1.0", "새 초안")
        self.owner._results.put((request_id, None, "실패"))
        self.owner._poll()
        self.owner.retry()
        self.assertIsNone(self.owner._request_id)
        self.assertEqual(self.owner.chat_window.input.get("1.0", "end-1c"), "새 초안")
        self.owner.chat_window.input.delete("1.0", "end")
        with patch.object(self.owner, "send") as send:
            self.owner.retry()
        send.assert_called_once_with("원래 요청", retry_of=request_id)

    def test_hiding_chat_keeps_request_active(self):
        request_id = self.send_without_network("계속 받아줘")
        self.owner.chat_window._hide()
        self.assertEqual(self.owner._request_id, request_id)
        self.assertFalse(self.owner._cancel.is_set())
        self.service.cancel_chat.assert_not_called()

    def test_external_settings_cancellation_releases_composer(self):
        self.send_without_network("진행 중")
        self.owner._cancel.set()
        self.owner._poll()
        self.assertIsNone(self.owner._request_id)
        self.assertIsNone(self.owner._cancel)
        self.assertEqual(self.owner.chat_window.send_button.cget("state"), "normal")

    def test_sending_restored_draft_reuses_failed_action_receipts(self):
        request_id = self.send_without_network("앱 설정 변경")
        self.owner._results.put((request_id, None, "통신 실패"))
        self.owner._poll()
        with patch("assistant_ai.ui.Thread") as worker:
            self.owner.send()
        self.assertEqual(worker.call_args.kwargs["args"][-1], request_id)

    def test_weather_one_time_region_does_not_change_default(self):
        from assistant_ai.ui import _WeatherWindow
        self.owner.run_background = lambda operation, done: done(operation(), None)
        window = _WeatherWindow(self.owner)
        original = self.settings.weather_location
        window.region.set("서울시")
        window.lookup()
        self.service.weather_report.assert_called_once_with("서울시")
        self.assertEqual(self.settings.weather_location, original)
        window.save_region()
        self.assertEqual(self.settings.weather_location, "서울시")

    def test_offline_today_does_not_start_chat_worker(self):
        with patch("assistant_ai.ui.Thread") as worker:
            self.owner.send("/오늘")
        worker.assert_not_called()
        self.assertEqual(self.owner.reply_window.text.get("1.0", "end-1c"), "집중 10분")

    def test_source_picker_exposes_return_keyboard_action(self):
        self.owner.open_reply("확인 https://example.com/weather")
        self.owner.reply_window._sources.open_picker()
        picker = self.owner._extra_windows[-1]
        import tkinter as tk
        listing = next(widget for widget in picker.body.winfo_children() if isinstance(widget, tk.Listbox))
        self.assertTrue(listing.bind("<Return>"))
        self.assertEqual(listing.get(0), "https://example.com/weather")

    def test_history_shows_turn_status_separately_from_message_body(self):
        turns = [SimpleNamespace(created_at="", user="질문 " + state, assistant=None, status=state)
                 for state in ("pending", "failed", "cancelled", "interrupted")]
        self.owner.chat_window.render(turns)
        rendered = self.owner.chat_window.history.get("1.0", "end-1c")
        for label in ("응답 준비 중", "응답 실패", "취소됨", "중단됨"):
            self.assertIn("[" + label + "]", rendered)
        self.assertTrue(all(turn.assistant is None for turn in turns))

    def test_image_proposal_requires_apply_and_offers_undo(self):
        self.owner.image_apply = Mock(return_value={"summary": "적용했어요", "changed": True})
        self.owner.image_cancel = Mock()
        self.owner.image_undo = Mock(return_value={"summary": "되돌렸어요", "changed": True})
        self.owner.show_image_proposal({"id": "p1", "status": "pending", "summary": "세트 변경", "scope": "수동 지정 유지"})
        self.owner.image_apply.assert_not_called()
        window = self.owner._extra_windows[-1]
        def buttons(widget):
            import tkinter as tk
            for child in widget.winfo_children():
                if isinstance(child, tk.Button):
                    yield child
                yield from buttons(child)
        actions = {button.cget("text"): button for button in buttons(window)}
        actions["적용"].invoke()
        actions["적용"].invoke()
        self.owner.image_apply.assert_called_once_with("p1")
        self.assertEqual(actions["되돌리기"].cget("state"), "normal")
        actions["되돌리기"].invoke()
        self.owner.image_undo.assert_called_once()

    def test_chat_layout_keeps_history_and_send_visible_at_high_dpi(self):
        from assistant_ai.ui import _ChatWindow
        original = float(self.root.tk.call("tk", "scaling"))
        self.addCleanup(lambda: self.root.tk.call("tk", "scaling", original))
        self.root.tk.call("tk", "scaling", 192 / 72)
        window = _ChatWindow(self.owner)
        window.show()
        self.root.update()
        self.assertGreater(window.history.winfo_height(), 100)
        self.assertTrue(window.send_button.winfo_viewable())
        self.assertGreaterEqual(window.send_button.winfo_width(), window.send_button.winfo_reqwidth())
        self.assertLessEqual(window.winfo_height(), self.root.winfo_vrootheight())


if __name__ == "__main__":
    unittest.main()
