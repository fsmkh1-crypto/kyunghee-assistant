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
            self.root.update()
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
            self.root.update()
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

    def test_reply_can_reopen_after_native_window_was_destroyed(self):
        self.owner.open_reply("첫 답변")
        previous = self.owner.reply_window
        previous.destroy()
        self.owner.open_reply("다음 답변")
        self.root.update()
        self.assertIsNot(self.owner.reply_window, previous)
        self.assertEqual(self.owner.reply_window.text.get("1.0", "end-1c"), "다음 답변")

    def test_reply_open_tolerates_shutdown_during_idle_geometry_updates(self):
        self.root.after_idle(self.owner.close)
        self.owner.open_reply("창이 열리는 동안 앱 종료")
        self.assertTrue(self.owner._closed)
        self.assertTrue(self.root.winfo_exists())

    def test_reply_close_reopen_and_repeated_click_preserve_text_at_common_dpi(self):
        import tkinter as tk
        original = float(self.root.tk.call("tk", "scaling"))
        self.addCleanup(lambda: self.root.tk.call("tk", "scaling", original))
        reply = "첫째 줄 🧑🏽‍💻\n둘째 줄\n셋째 줄\n넷째 줄\n다섯째 줄\nhttps://example.com/날씨?city=서울"
        for dpi in (96, 120, 144, 192):
            with self.subTest(dpi=dpi):
                self.root.tk.call("tk", "scaling", dpi / 72)
                self.owner.open_reply(reply)
                reader = self.owner.reply_window
                self.root.update()
                reader.tk.call(reader.protocol("WM_DELETE_WINDOW"))
                self.assertEqual(reader.state(), "withdrawn")
                self.owner.open_reply(reply)
                reader.focus_force()
                reader.event_generate("<Escape>")
                self.root.update()
                self.assertEqual(reader.state(), "withdrawn")
                for _ in range(3):
                    self.owner.open_reply(reply)
                self.root.update()
                self.assertIs(self.owner.reply_window, reader)
                self.assertEqual(reader.text.get("1.0", "end-1c"), reply)
                self.assertTrue(reader._sources.targets)
                close = next(widget for widget in reader.actions.winfo_children()
                             if isinstance(widget, tk.Button) and widget.cget("text") == "닫기")
                close.invoke()
                self.assertEqual(reader.state(), "withdrawn")
                self.owner.open_reply(reply)
                self.assertEqual(reader.text.get("1.0", "end-1c"), reply)
                self.assertLessEqual(reader.winfo_height(), self.root.winfo_vrootheight())
                reader.destroy()

    def test_reply_recreation_does_not_write_conversation_or_memory_data(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from assistant_ai.memory import MemoryStore
        with TemporaryDirectory() as directory:
            store = MemoryStore(Path(directory) / "memory.sqlite3")
            store.set_enabled(True)
            store.set_history_enabled(True)
            turn_id = store.begin_turn("내가 남긴 질문")
            self.assertIsNotNone(turn_id)
            store.finish_turn(turn_id, "보존할 원본 답변")
            store.add_memory("보존할 장기 기억")
            original_turns, original_memories = store.recent_turns(), store.list_memories()
            self.assertEqual(len(original_turns), 1)
            self.assertEqual(original_turns[0].assistant, "보존할 원본 답변")
            self.assertEqual(len(original_memories), 1)
            self.assertEqual(original_memories[0].text, "보존할 장기 기억")
            self.service.recent_turns = store.recent_turns
            for _ in range(3):
                self.owner.open_reply("보존할 원본 답변")
                self.owner.reply_window.destroy()
            self.assertEqual(store.recent_turns(), original_turns)
            self.assertEqual(store.list_memories(), original_memories)

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

    @staticmethod
    def approval_layout_snapshot(window):
        def rect(widget):
            return (widget.winfo_rootx() - window.winfo_rootx(),
                    widget.winfo_rooty() - window.winfo_rooty(),
                    widget.winfo_width(), widget.winfo_height())
        buttons = [getattr(window, name) for name in ("apply_button", "cancel_button", "undo_button")
                   if hasattr(window, name)]
        return {
            "window": (window.winfo_rootx(), window.winfo_rooty(), window.winfo_width(), window.winfo_height()),
            "body": rect(window.body),
            "actions": rect(buttons[0].master),
            "buttons": [(button.cget("text"), rect(button),
                         (button.winfo_reqwidth(), button.winfo_reqheight()), bool(button.winfo_viewable()))
                        for button in buttons],
        }

    def wait_for_approval_layout(self, window):
        """Pump native Configure events before checking the final strict bounds.

        update()/update_idletasks() can return between a Win32 client resize
        and its child-layout notifications. Sample the full footer geometry
        across timer turns; a stable clipped layout must still fail below.
        """
        import tkinter as tk
        import time
        first = self.approval_layout_snapshot(window)
        samples = [first]
        done = tk.BooleanVar(master=self.root, value=False)
        deadline = time.monotonic() + 2
        consecutive = 0
        errors = []

        def sample():
            nonlocal consecutive
            try:
                current = self.approval_layout_snapshot(window)
                consecutive = consecutive + 1 if current == samples[-1] else 0
                samples.append(current)
                if consecutive >= 2 or time.monotonic() >= deadline:
                    done.set(True)
                else:
                    self.root.after(20, sample)
            except Exception as error:
                errors.append(error)
                done.set(True)

        self.root.after(20, sample)
        self.root.wait_variable(done)
        window._test_approval_layout = {"first": first, "final": samples[-1], "samples": len(samples)}
        if errors:
            raise errors[0]
        self.assertGreaterEqual(consecutive, 2, f"Approval geometry did not settle: {window._test_approval_layout!r}")
        if os.name == "nt" and first != samples[-1]:
            print(f"\nApproval geometry settled after native events: {window._test_approval_layout!r}", flush=True)

    def assert_action_visible(self, button, window):
        details = repr({"current": self.approval_layout_snapshot(window),
                        "settling": getattr(window, "_test_approval_layout", None)})
        self.assertTrue(button.winfo_viewable(), details)
        left, top = button.winfo_rootx() - window.winfo_rootx(), button.winfo_rooty() - window.winfo_rooty()
        self.assertGreaterEqual(left, 0, details)
        self.assertGreaterEqual(top, 0, details)
        self.assertGreaterEqual(button.winfo_width(), button.winfo_reqwidth(), details)
        self.assertGreaterEqual(button.winfo_height(), button.winfo_reqheight(), details)
        self.assertLessEqual(left + button.winfo_width(), window.winfo_width(), details)
        self.assertLessEqual(top + button.winfo_height(), window.winfo_height(), details)
        parent_left = button.winfo_rootx() - button.master.winfo_rootx()
        parent_top = button.winfo_rooty() - button.master.winfo_rooty()
        self.assertGreaterEqual(parent_left, 0, details)
        self.assertGreaterEqual(parent_top, 0, details)
        self.assertLessEqual(parent_left + button.winfo_width(), button.master.winfo_width(), details)
        self.assertLessEqual(parent_top + button.winfo_height(), button.master.winfo_height(), details)

    def test_timer_approval_actions_remain_visible_at_small_sizes_and_common_dpi(self):
        from assistant_ai.ui import _ConfirmWindow
        original = float(self.root.tk.call("tk", "scaling"))
        self.addCleanup(lambda: self.root.tk.call("tk", "scaling", original))
        for dpi in (96, 120, 144, 192):
            for width, height in ((640, 360), (320, 240)):
                with self.subTest(dpi=dpi, work_area=(width, height)):
                    self.root.tk.call("tk", "scaling", dpi / 72)
                    self.owner.chat_work_area = lambda *_, w=width, h=height: (0, 0, w, h)
                    window = _ConfirmWindow(self.owner, "휴식을 시작해요.\n" * 100, lambda: False)
                    window.show()
                    self.root.update()
                    self.assert_action_visible(window.apply_button, window)
                    self.assert_action_visible(window.cancel_button, window)
                    self.assertTrue(window.description.winfo_viewable())
                    self.assertGreater(window.description.winfo_height(), 10)
                    window.description.yview_moveto(1)
                    self.assertGreater(window.description.yview()[0], 0)
                    self.assertLessEqual(window.winfo_height(), height)
                    window.destroy()

    def test_real_timer_confirmation_returns_only_explicit_valid_approval(self):
        from assistant_ai.desktop import DesktopAssistantMixin
        app = SimpleNamespace(_assistant_windows=self.owner)
        for action, cancelled, expected in (("apply", False, True), ("cancel", False, False),
                                            ("window_close", False, False), ("apply", True, False)):
            with self.subTest(action=action, cancelled=cancelled):
                cancellation = [False]
                inspected = []
                def operate():
                    window = self.owner._extra_windows[-1]
                    inspected.append(window)
                    cancellation[0] = cancelled
                    if action == "window_close":
                        window.tk.call(window.protocol("WM_DELETE_WINDOW"))
                    else:
                        getattr(window, action + "_button").invoke()
                self.root.after(50, operate)
                result = DesktopAssistantMixin._confirm_assistant_change(app, "휴식을 시작해요.", lambda: cancellation[0])
                self.assertEqual(result, expected)
                self.assertEqual(len(inspected), 1)
                self.assertNotIn(inspected[0], self.owner._extra_windows)
                self.assertIsNone(self.root.grab_current())

    def test_timer_confirmation_cancellation_closes_dialog_without_applying(self):
        from threading import Event
        cancelled = Event()
        self.root.after(40, cancelled.set)
        self.assertFalse(self.owner.confirm_change("휴식을 시작해요.", cancelled.is_set))
        self.assertIsNone(self.root.grab_current())

    def test_timer_approval_follows_visible_chat_and_clamps_to_its_monitor(self):
        from assistant_ai.ui import _ConfirmWindow
        from assistant_ai.ui_helpers import position_window
        chat = self.owner.chat_window
        self.root.update()
        chat.geometry("500x450+1000+100")
        self.root.update()
        self.owner.chat_work_area = Mock(return_value=(960, 0, 1920, 1080))
        window = _ConfirmWindow(self.owner, "휴식을 시작해요.", lambda: False)
        with patch("assistant_ai.ui.position_window", wraps=position_window) as position:
            window.show()
        self.root.update()
        self.assertIs(position.call_args.args[1], chat)
        self.assertEqual(str(window.transient()), str(chat))
        self.assertGreaterEqual(self.owner.chat_work_area.call_args.args[0], 960)
        self.assertGreaterEqual(window.winfo_rootx(), 960)
        self.assertLessEqual(window.winfo_rootx() + window.winfo_width(), 1920)
        self.assert_action_visible(window.apply_button, window)
        window.destroy()

    def test_image_approval_long_details_scroll_without_hiding_actions(self):
        original = float(self.root.tk.call("tk", "scaling"))
        self.addCleanup(lambda: self.root.tk.call("tk", "scaling", original))
        self.owner.image_apply = Mock(return_value={"summary": "적용했어요", "changed": True})
        self.owner.image_cancel = Mock()
        self.owner.image_undo = Mock(return_value={"summary": "되돌렸어요", "changed": True})
        for dpi in (96, 120, 144, 192):
            for width, height in ((640, 360), (320, 240)):
                with self.subTest(dpi=dpi, work_area=(width, height)):
                    self.root.tk.call("tk", "scaling", dpi / 72)
                    self.owner.chat_work_area = lambda *_, w=width, h=height: (0, 0, w, h)
                    self.owner.show_image_proposal({"id": "p1", "status": "pending",
                        "summary": "세트를 변경할까요? " * 25, "scope": "수동 지정은 유지돼요. " * 40})
                    window = self.owner._extra_windows[-1]
                    self.root.update()
                    self.wait_for_approval_layout(window)
                    for button in (window.apply_button, window.cancel_button, window.undo_button):
                        self.assert_action_visible(button, window)
                    window.content_canvas.yview_moveto(1)
                    self.assertGreater(window.content_canvas.yview()[0], 0)
                    window.apply_button.invoke()
                    self.root.update()
                    self.wait_for_approval_layout(window)
                    self.assertEqual(window.undo_button.cget("state"), "normal")
                    for button in (window.apply_button, window.cancel_button, window.undo_button):
                        self.assert_action_visible(button, window)
                    window.undo_button.invoke()
                    window.cancel_button.invoke()
                    window.destroy()
        self.assertEqual(self.owner.image_apply.call_count, 8)
        self.assertEqual(self.owner.image_undo.call_count, 8)
        self.owner.image_cancel.assert_not_called()

    def test_image_approval_fits_unequal_windows_button_sizes(self):
        import tkinter as tk
        from assistant_ai import ui
        original_button = ui._button
        widths = {"되돌리기": 131, "취소": 83, "적용": 83}

        def fixed_pixel_button(parent, text, command, **options):
            button = original_button(parent, text, command, **options)
            # Reproduce the measured Windows requests on any font/DPI host.
            button._test_image = tk.PhotoImage(master=parent, width=1, height=1)
            button.configure(image=button._test_image, width=0, height=0,
                             padx=0, pady=0, highlightthickness=0)
            button._test_image.configure(width=widths[text] - button.winfo_reqwidth() + 1,
                                         height=62 - button.winfo_reqheight() + 1)
            return button

        self.owner.chat_work_area = lambda *_: (0, 0, 640, 360)
        self.owner.image_apply = Mock(return_value={"summary": "적용했어요", "changed": True})
        self.owner.image_undo = Mock(return_value={"summary": "되돌렸어요", "changed": True})
        with patch("assistant_ai.ui._button", side_effect=fixed_pixel_button):
            self.owner.show_image_proposal({"id": "p-sized", "status": "pending",
                "summary": "세트를 변경할까요? " * 25, "scope": "수동 지정은 유지돼요. " * 40})
        window = self.owner._extra_windows[-1]
        # This reproduces the measured button-layout regression in CLIENT
        # pixels. A 320x240 outer work area has a smaller client on Windows.
        # Actual tiny-screen fitting remains covered by the DPI matrix above.
        window.minsize(296, 216)
        window.geometry("296x216")
        self.root.update()
        self.wait_for_approval_layout(window)
        buttons = (window.undo_button, window.cancel_button, window.apply_button)
        self.assertEqual([(button.winfo_reqwidth(), button.winfo_reqheight()) for button in buttons],
                         [(131, 62), (83, 62), (83, 62)])
        self.assertEqual(window.apply_button.master.winfo_width(), 252)
        self.assertEqual([(int(button.grid_info()["row"]), int(button.grid_info()["column"]))
                          for button in buttons], [(0, 0), (0, 1), (1, 0)])
        for button in buttons:
            self.assert_action_visible(button, window)
        self.assertTrue(window.content_canvas.winfo_viewable())
        self.assertGreater(window.content_canvas.winfo_height(), 10)
        window.apply_button.invoke()
        self.root.update()
        self.wait_for_approval_layout(window)
        for button in buttons:
            self.assert_action_visible(button, window)
        window.undo_button.invoke()
        self.owner.image_apply.assert_called_once_with("p-sized")
        self.owner.image_undo.assert_called_once()

    def test_image_wrapping_uses_viewport_width_without_label_feedback(self):
        import tkinter as tk
        summary, scope = "이미지 변경 확인 " * 30, "변경 범위를 확인한 뒤 적용합니다. " * 30
        self.owner.show_image_proposal({"id": "p1", "status": "pending", "summary": summary, "scope": scope})
        window = self.owner._extra_windows[-1]
        self.root.update()
        canvas = window.content_canvas
        def descendants(widget):
            for child in widget.winfo_children():
                yield child
                yield from descendants(child)
        label = next(widget for widget in descendants(window)
                     if isinstance(widget, tk.Label) and widget.cget("text") == scope)
        original = label.cget("wraplength")
        # A child's height/size notification must not change the text width.
        with patch.object(label, "configure", wraps=label.configure) as configure:
            label.event_generate("<Configure>", width=73, height=89)
            canvas.event_generate("<Configure>", width=canvas.winfo_width(), height=canvas.winfo_height() + 1)
            self.root.update_idletasks()
            configure.assert_not_called()
        self.assertEqual(label.cget("wraplength"), original)
        window.geometry("360x240")
        self.root.update()
        self.assertLess(label.winfo_pixels(label.cget("wraplength")), label.winfo_pixels(original))
        self.assertLessEqual(label.winfo_pixels(label.cget("wraplength")), canvas.winfo_width() - 28)
        stable = (window.winfo_geometry(), canvas.winfo_width(), label.cget("wraplength"), label.winfo_reqheight())
        with patch.object(label, "configure", wraps=label.configure) as configure:
            for _ in range(4):
                self.root.update()
            configure.assert_not_called()
        self.assertEqual(stable, (window.winfo_geometry(), canvas.winfo_width(), label.cget("wraplength"), label.winfo_reqheight()))

    def test_chat_activity_covers_visible_pending_and_unsent_hidden_drafts(self):
        # Keep one clock for the entire scenario. Returning to the host clock
        # midway can move time backwards on a freshly booted Windows runner.
        with patch("assistant_ai.ui.time.monotonic", return_value=100) as clock:
            self.root.update()
            self.assertFalse(self.owner.is_chat_active())  # An empty open window is not activity.
            self.owner.chat_window.history.event_generate("<MouseWheel>", delta=-120)
            self.root.update()
            self.assertEqual(self.owner._last_chat_interaction, 100)
            self.assertTrue(self.owner.is_chat_active())
            clock.return_value = 399
            self.assertTrue(self.owner.is_chat_active())
            clock.return_value = 400
            self.assertFalse(self.owner.is_chat_active())
            self.owner.chat_window._hide()
            self.assertFalse(self.owner.is_chat_active())
            self.owner.chat_window.input.insert("1.0", "아직 보내지 않은 초안")
            self.assertTrue(self.owner.is_chat_active())
            clock.return_value = 1000
            self.assertTrue(self.owner.is_chat_active())  # Hidden drafts remain protected beyond five minutes.
            self.owner.chat_window.input.delete("1.0", "end")
            self.send_without_network("응답 기다리는 중")
            self.owner.chat_window.withdraw()
            self.assertTrue(self.owner.is_chat_active())
            self.owner.cancel()
            self.assertTrue(self.owner.is_chat_active())  # Cancellation restores the unsent request.
            self.owner.chat_window.input.delete("1.0", "end")
            self.assertFalse(self.owner.is_chat_active())

    def test_explicit_history_clear_sends_separate_clear_state(self):
        self.service.history_counts = Mock(return_value={})
        self.service.clear_history = Mock()
        with patch("assistant_ai.ui.messagebox.askyesno", return_value=True):
            self.owner.clear_history()
        self.service.clear_history.assert_called_once()
        self.assertEqual(self.states[-1], ("cleared", ""))

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
