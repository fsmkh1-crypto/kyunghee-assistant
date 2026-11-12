"""Chat UI regressions; mocked native composition is not a live Korean IME test."""
from dataclasses import replace
from io import BytesIO
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


class NativeCompositionTests(unittest.TestCase):
    def setUp(self):
        from assistant_ai import windows_ime
        self.ime = windows_ime
        self.imm, self.user = Mock(), Mock()
        self.imm.ImmGetContext.return_value = 0x123456789
        self.imm.ImmGetCompositionStringW.return_value = 2
        self.imm.ImmNotifyIME.return_value = True
        self.user.GetAsyncKeyState.return_value = 0
        self.user.GetKeyState.return_value = 0
        self.user.GetFocus.return_value = 42
        self.user.GetAncestor.return_value = 43
        self.user.GetQueueStatus.return_value = 0
        self.enterContext(patch.object(windows_ime.os, "name", "nt"))
        self.enterContext(patch.object(windows_ime, "_libraries", return_value=(self.imm, self.user)))

    def test_composition_waits_for_control_release_then_commits_once(self):
        self.user.GetAsyncKeyState.return_value = -32768
        self.assertEqual(self.ime.prepare_input(0x123456788), "modifiers")
        self.imm.ImmNotifyIME.assert_not_called()
        self.user.GetAsyncKeyState.return_value = 0
        self.assertEqual(self.ime.prepare_input(0x123456788), "committed")
        self.imm.ImmNotifyIME.assert_called_once_with(0x123456789, 0x15, 1, 0)
        self.assertEqual(self.ime.prepare_input(0x123456788, request_commit=False), "pending")
        self.imm.ImmNotifyIME.assert_called_once()
        self.imm.ImmGetCompositionStringW.return_value = 0
        self.assertEqual(self.ime.prepare_input(0x123456788, request_commit=False), "ready")
        self.assertEqual(self.imm.ImmReleaseContext.call_count, 3)

    def test_failure_releases_context_and_does_not_invent_characters(self):
        self.imm.ImmGetCompositionStringW.return_value = -2
        self.assertEqual(self.ime.prepare_input(42), "failed")
        self.imm.ImmNotifyIME.assert_not_called()
        self.imm.ImmReleaseContext.assert_called_once_with(42, 0x123456789)
        self.imm.ImmGetCompositionStringW.return_value = 2
        self.imm.ImmNotifyIME.return_value = False
        self.assertEqual(self.ime.prepare_input(42), "failed")
        self.assertEqual(self.imm.ImmReleaseContext.call_count, 2)

    def test_physical_release_waits_until_tk_queue_has_processed_key_up(self):
        self.user.GetKeyState.return_value = -32768
        self.assertEqual(self.ime.prepare_input(42), "modifiers")
        self.imm.ImmNotifyIME.assert_not_called()
        self.user.GetKeyState.return_value = 0
        self.assertEqual(self.ime.prepare_input(42), "committed")

    def test_not_ready_native_data_waits_without_guessing_composition_text(self):
        self.imm.ImmGetCompositionStringW.return_value = -1
        self.assertEqual(self.ime.prepare_input(42), "pending")
        self.imm.ImmNotifyIME.assert_not_called()
        self.imm.ImmGetCompositionStringW.return_value = 2
        self.assertEqual(self.ime.prepare_input(42), "committed")

    def test_native_focus_context_is_used_instead_of_logical_text_context(self):
        self.user.GetFocus.return_value = 100
        self.imm.ImmGetContext.side_effect = lambda hwnd: 999 if hwnd == 100 else None
        self.assertEqual(self.ime.prepare_input(42, toplevel_hwnd=100), "committed")
        self.imm.ImmGetContext.assert_called_once_with(100)
        self.imm.ImmReleaseContext.assert_called_once_with(100, 999)

    def test_foreign_focus_is_never_committed_and_no_context_is_distinct(self):
        self.user.GetAncestor.side_effect = lambda hwnd, _flags: 43 if hwnd == 42 else 44
        self.user.GetFocus.return_value = 100
        self.assertEqual(self.ime.prepare_input(42), "unfocused")
        self.imm.ImmGetContext.assert_not_called()
        self.user.GetAncestor.side_effect = None
        self.user.GetFocus.return_value = 42
        self.imm.ImmGetContext.return_value = None
        self.assertEqual(self.ime.prepare_input(42), "no_ime")
        self.imm.ImmNotifyIME.assert_not_called()

    def test_zero_composition_waits_for_modifiers_and_pending_native_messages(self):
        self.imm.ImmGetCompositionStringW.return_value = 0
        self.user.GetKeyState.return_value = -32768
        self.assertEqual(self.ime.prepare_input(42), "modifiers")
        self.user.GetKeyState.return_value = 0
        self.user.GetQueueStatus.return_value = 0x0008 << 16
        self.assertEqual(self.ime.prepare_input(42), "pending")
        self.user.GetQueueStatus.return_value = 0
        self.assertEqual(self.ime.prepare_input(42), "ready")


@unittest.skipUnless(os.name == "nt" or os.environ.get("DISPLAY"), "Tk display required")
class ChatWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import tkinter as tk
        cls.root = tk.Tk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        for event in cls.root.tk.splitlist(cls.root.tk.call("after", "info")):
            cls.root.after_cancel(event)
        cls.root.destroy()

    def setUp(self):
        from assistant_ai.config import AISettings
        from assistant_ai.ui import AssistantWindows
        self.settings = AISettings(enabled=True)
        self.turns = []
        self.service = SimpleNamespace(
            load_settings=lambda: self.settings, ready=lambda: True,
            recent_turns=lambda **kw: self.turns[-kw["limit"]:], cancel_chat=Mock(),
            ledger=SimpleNamespace(summary=lambda *_: SimpleNamespace(estimated_cost_usd=0, reserved_cost_usd=0)),
        )
        self.service.save_settings = lambda settings: setattr(self, "settings", settings)
        self.owner = AssistantWindows(self.root, self.service, context=lambda: {}, dispatch=Mock())
        self.owner.open_chat()
        self.chat = self.owner.chat_window
        self.chat.input.focus_force()
        self.root.update()
        self.fitted_client_size = self.chat.winfo_width(), self.chat.winfo_height()
        self.addCleanup(self.owner.close)

    @staticmethod
    def turn(number, *, origin="chat", event=""):
        return SimpleNamespace(id=number, user=f"질문 {number}" if origin == "chat" else "",
                               assistant=f"대화 {number} · " + "읽고 있는 문장입니다. " * 12,
                               created_at="2026-11-11T10:00:00+00:00", status="completed", origin=origin, event=event)

    def populate(self):
        self.turns = [self.turn(i) for i in range(1, 91)]
        self.owner._render_history()
        self.root.update()

    def anchor(self):
        return self.chat._capture_history_view()[:3]

    def read_old(self):
        self.chat.history.yview_moveto(.32)
        self.root.update()
        self.assertEqual(self.anchor()[0], "anchor")
        return self.anchor()

    def resize_within_display(self, width, height):
        # The real host may be 1366x768 even when a test invents a larger
        # work area. Start with a client size already fitted on this display,
        # then resize within that budget. Large-screen exact sizes are tested
        # separately by the native window model.
        target = min(width, self.fitted_client_size[0]), min(height, self.fitted_client_size[1])
        self.chat.geometry(f"{target[0]}x{target[1]}")
        self.root.update()
        actual = self.chat.winfo_width(), self.chat.winfo_height()
        self.assertEqual(actual, target)  # Do not silently accept a resize cap.
        return actual

    def finish_submission(self):
        check_id = None
        def check():
            nonlocal check_id
            if not self.chat._submit_pending:
                self.root.quit()
            else:
                check_id = self.root.after(5, check)
        timeout = self.root.after(1000, self.root.quit)
        check_id = self.root.after(5, check)
        self.root.mainloop()
        self.root.after_cancel(timeout)
        self.root.after_cancel(check_id)
        self.assertFalse(self.chat._submit_pending, "Submission did not complete in the normal event loop")

    def test_new_messages_paging_font_change_and_reopen_keep_reading_anchor(self):
        self.populate()
        anchor = self.read_old()
        self.turns.append(self.turn(91, origin="local_event", event="return"))
        self.owner.refresh_chat_history()
        self.root.update()
        self.assertEqual(self.anchor(), anchor)
        self.owner.show_older()
        self.root.update()
        self.assertEqual(self.anchor(), anchor)
        self.chat.change_reading_size(1)
        self.root.update()
        # Wrapping may move the visible start within the same paragraph, but
        # must keep the same conversation rather than jumping to the bottom.
        self.assertEqual(self.anchor()[:2], anchor[:2])
        anchor = self.anchor()
        resized_client = self.resize_within_display(780, 620)
        resized = self.anchor()
        self.assertEqual(resized[:2], anchor[:2])
        self.chat._hide()
        self.turns.append(self.turn(92, origin="proactive", event="periodic"))
        self.owner.refresh_chat_history()
        self.root.update()
        self.assertEqual(self.chat.state(), "withdrawn")
        self.owner.open_chat()
        self.root.update()
        self.assertEqual(self.anchor(), resized)
        self.assertEqual((self.chat.winfo_width(), self.chat.winfo_height()), resized_client)
        self.chat.latest_button.invoke()
        self.root.update()
        self.assertGreaterEqual(self.chat.history.yview()[1], .999)

    def test_following_latest_stays_at_bottom_and_notifications_have_source(self):
        self.populate()
        self.turns.append(self.turn(91, origin="local_event", event="return"))
        self.owner.refresh_chat_history()
        self.root.update()
        self.assertGreaterEqual(self.chat.history.yview()[1], .999)
        rendered = self.chat.history.get("1.0", "end-1c")
        self.assertIn("타이머 안내 · 복귀", rendered)
        self.assertNotIn("나 · 19:00\n\n", rendered)

    def test_notification_refresh_keeps_pending_request_without_duplicate_user(self):
        self.chat.input.insert("1.0", "근데 느림...ㅋ")
        with patch("assistant_ai.ui.Thread"):
            self.chat.send_button.invoke()
            self.root.update()
            self.finish_submission()
        self.turns.append(self.turn(1, origin="local_event", event="rest"))
        self.owner.refresh_chat_history()
        self.root.update()
        self.assertEqual(self.chat.history.get("1.0", "end").count("근데 느림...ㅋ"), 1)
        self.turns.append(SimpleNamespace(id=2, user="근데 느림...ㅋ", assistant=None, status="pending", created_at=""))
        self.owner.refresh_chat_history()
        self.root.update()
        self.assertEqual(self.chat.history.get("1.0", "end").count("근데 느림...ㅋ"), 1)

    def test_repeated_text_still_shows_a_new_pending_request(self):
        self.turns.append(SimpleNamespace(id=1, user="다시ㅋ", assistant="지난 답변", status="completed", created_at=""))
        self.owner._render_history()
        self.root.update()
        self.chat.input.insert("1.0", "다시ㅋ")
        with patch("assistant_ai.ui.Thread"):
            self.chat.send_button.invoke()
            self.root.update()
            self.finish_submission()
        self.assertEqual(self.chat.history.get("1.0", "end").count("다시ㅋ"), 2)
        self.owner.refresh_chat_history()
        self.owner.refresh_chat_history()
        self.root.update()
        self.assertEqual(self.chat.history.get("1.0", "end").count("다시ㅋ"), 2)

    def _activate_send(self, path):
        if path == "button":
            self.chat.send_button.invoke()
        else:
            self.chat.input.focus_force()
            self.root.update()
            self.chat.input.event_generate("<Control-Return>")

    def test_button_and_ctrl_enter_wait_for_queued_last_jamo_and_send_once(self):
        for path in ("button", "keyboard"):
            with self.subTest(path=path):
                self.chat.input.delete("1.0", "end")
                self.chat.input.insert("1.0", "근데 느림...")
                def commit(_hwnd, *, toplevel_hwnd, request_commit):
                    if request_commit:
                        self.chat.after_idle(lambda: self.chat.input.insert("end-1c", "ㅋ"))
                        return "committed"
                    return "ready"
                with patch("assistant_ai.ui.prepare_input", side_effect=commit) as native, patch.object(self.owner, "send") as send:
                    self._activate_send(path)
                    self.chat.request_send()  # Rapid repeated activation is one send.
                    send.assert_not_called()
                    self.finish_submission()
                    send.assert_called_once_with("근데 느림...ㅋ")
                    self.assertTrue(native.call_args_list[0].kwargs["request_commit"])
                    self.assertTrue(all(not call.kwargs["request_commit"] for call in native.call_args_list[1:]))

    def test_idle_only_geometry_updates_cannot_send_before_queued_result(self):
        self.chat.input.insert("1.0", "근데 느림...")
        self.root.update()
        self.chat.input.bind("<<TestImeResult>>", lambda _event: self.chat.input.insert("end-1c", "ㅋ"))
        def commit(_hwnd, **options):
            if options["request_commit"]:
                self.chat.input.event_generate("<<TestImeResult>>", when="tail")
                return "committed"
            return "ready"
        with patch("assistant_ai.ui.prepare_input", side_effect=commit), patch.object(self.owner, "send") as send:
            self.chat.request_send()
            self.root.update_idletasks()
            send.assert_not_called()
            self.finish_submission()
            send.assert_called_once_with("근데 느림...ㅋ")

    def test_known_composition_waits_for_late_edit_acknowledgement(self):
        self.chat.input.insert("1.0", "근데 느림...")
        self.root.update()
        early = []
        def commit(_hwnd, **options):
            if options["request_commit"]:
                self.chat.after(120, lambda: self.chat.input.insert("end-1c", "ㅋ"))
                return "committed"
            return "ready"
        with patch("assistant_ai.ui.prepare_input", side_effect=commit), patch.object(self.owner, "send") as send:
            self.chat.request_send()
            self.root.after(70, lambda: early.append(send.called))
            self.finish_submission()
            send.assert_called_once_with("근데 느림...ㅋ")
            self.assertEqual(early, [False])

    def test_missing_commit_acknowledgement_times_out_without_consuming_draft(self):
        self.chat.input.insert("1.0", "근데 느림...")
        self.root.update()
        with patch("assistant_ai.ui.prepare_input", side_effect=lambda _hwnd, **kw: "committed" if kw["request_commit"] else "ready"), patch("assistant_ai.ui.time.monotonic", return_value=100) as clock, patch.object(self.owner, "send") as send:
            self.chat.request_send()
            self.root.after(70, lambda: setattr(clock, "return_value", 106))
            self.finish_submission()
            send.assert_not_called()
        self.assertEqual(self.chat.input.get("1.0", "end-1c"), "근데 느림...")

    def test_same_character_selection_commit_is_an_edit_acknowledgement(self):
        self.chat.input.insert("1.0", "ㅋ")
        self.chat.input.tag_add("sel", "1.0", "end-1c")
        self.chat.input.mark_set("insert", "1.0")
        self.root.update()
        def commit(_hwnd, **options):
            if options["request_commit"]:
                self.chat.after(25, lambda: self.chat.input.tk.call("tk::TextInsert", self.chat.input._w, "ㅋ"))
                return "committed"
            return "ready"
        with patch("assistant_ai.ui.prepare_input", side_effect=commit), patch.object(self.owner, "send") as send:
            self.chat.request_send()
            self.finish_submission()
            send.assert_called_once_with("ㅋ")

    def test_focus_loss_before_final_snapshot_preserves_draft(self):
        self.chat.input.insert("1.0", "전송 전 초안ㅋ")
        with patch("assistant_ai.ui.prepare_input", side_effect=["ready", "unfocused"]), patch.object(self.owner, "send") as send:
            self.chat.request_send()
            self.finish_submission()
            send.assert_not_called()
        self.assertEqual(self.chat.input.get("1.0", "end-1c"), "전송 전 초안ㅋ")

    def test_unrelated_user_edit_cancels_pending_send_instead_of_acknowledging_ime(self):
        self.chat.input.insert("1.0", "근데 느림...")
        self.root.update()
        def commit(_hwnd, **options):
            if options["request_commit"]:
                self.chat.after(120, lambda: self.chat.input.insert("end-1c", "ㅋ"))
                return "committed"
            return "ready"
        with patch("assistant_ai.ui.prepare_input", side_effect=commit), patch.object(self.owner, "send") as send:
            self.chat.request_send()
            self.root.after(40, lambda: self.chat.input.event_generate("<KeyPress-x>"))
            self.finish_submission()
            self.root.after(160, self.root.quit)
            self.root.mainloop()
            send.assert_not_called()
        self.assertEqual(self.chat.input.get("1.0", "end-1c"), "근데 느림...xㅋ")

    def test_hide_inside_native_completion_invalidates_its_continuation(self):
        self.chat.input.insert("1.0", "보존할 초안ㅋ")
        for state in ("ready", "committed"):
            with self.subTest(state=state):
                self.owner.open_chat()
                self.chat.input.focus_force()
                self.root.update()
                def hide(_hwnd, **_options):
                    self.chat._hide()
                    return state
                with patch("assistant_ai.ui.prepare_input", side_effect=hide), patch.object(self.owner, "send") as send:
                    self.chat.request_send()
                    self.finish_submission()
                    send.assert_not_called()
                self.assertIsNone(self.chat._send_after_id)
                self.assertEqual(self.chat.input.get("1.0", "end-1c"), "보존할 초안ㅋ")

    def test_escape_while_composition_pending_cancels_submission(self):
        self.chat.input.insert("1.0", "보존할 초안ㅋ")
        with patch("assistant_ai.ui.prepare_input", return_value="pending"), patch.object(self.owner, "send") as send:
            self.chat.request_send()
            self.root.after(40, lambda: self.chat.input.event_generate("<Escape>"))
            self.finish_submission()
            send.assert_not_called()
        self.assertEqual(self.chat.state(), "withdrawn")
        self.assertEqual(self.chat.input.get("1.0", "end-1c"), "보존할 초안ㅋ")

    def test_destroy_inside_native_completion_does_not_rearm_or_touch_tk(self):
        def destroy(_hwnd, **_options):
            self.chat.destroy()
            return "committed"
        with patch("assistant_ai.ui.prepare_input", side_effect=destroy), patch.object(self.owner, "send") as send, patch.object(self.root, "report_callback_exception") as error:
            self.chat.request_send()
            self.finish_submission()
            send.assert_not_called()
            error.assert_not_called()
        self.owner.chat_window = None

    def test_unicode_guard_preserves_selection_undo_and_ordinary_shortcuts(self):
        self.chat.input.insert("1.0", "앞뒤")
        self.chat.input.mark_set("insert", "1.1")
        self.chat.input.edit_reset()
        event = SimpleNamespace(char="ㅋ", keycode=ord("ㅋ"), state=4, send_event=True)
        self.assertEqual(self.chat._preserve_native_text(event), "break")
        self.assertEqual(self.chat.input.get("1.0", "end-1c"), "앞ㅋ뒤")
        self.chat.input.edit_undo()
        self.assertEqual(self.chat.input.get("1.0", "end-1c"), "앞뒤")
        for char, keycode in (("\x03", 67), ("\x16", 86), ("\r", 13), ("", 229)):
            self.assertIsNone(self.chat._preserve_native_text(SimpleNamespace(char=char, keycode=keycode, state=4, send_event=True)))
        self.assertEqual(self.chat.input.get("1.0", "end-1c"), "앞뒤")

    def test_native_text_bindtag_registers_dispatches_and_cleans_up_in_real_tk(self):
        # Exercise registration on X11 too: calling the handler directly cannot
        # catch Tk interpreting a dot-prefixed class tag as a nonexistent widget.
        self.chat._install_native_text_binding()
        tag, command = self.chat._native_text_tag, self.chat._native_text_command
        self.assertEqual(self.chat.input.bindtags()[0], tag)
        self.assertIn(command, self.root.bind_class(tag, "<KeyPress>"))
        self.assertTrue(self.root.tk.call("info", "commands", command))
        self.chat._install_native_text_binding()
        self.assertEqual(self.chat.input.bindtags().count(tag), 1)
        self.assertEqual(self.chat._native_text_command, command)
        with patch.object(self.root, "report_callback_exception") as error:
            self.chat.input.event_generate("<KeyPress-a>", when="tail")
            self.root.update()
            self.assertEqual(self.chat.input.get("1.0", "end-1c"), "a")
            error.assert_not_called()
            self.chat.destroy()
            self.root.update()
            error.assert_not_called()
        self.owner.chat_window = None
        self.assertFalse(self.root.bind_class(tag, "<KeyPress>"))
        self.assertFalse(self.root.tk.call("info", "commands", command))
        self.assertIsNone(self.chat._native_text_tag)
        self.assertIsNone(self.chat._native_text_command)

    def test_button_keyboard_activation_restores_composer_before_completion(self):
        self.chat.input.insert("1.0", "근데 느림...")
        self.chat.send_button.focus_force()
        self.root.update()
        def commit(_hwnd, **options):
            self.assertIs(self.chat.focus_get(), self.chat.input)
            if options["request_commit"]:
                self.chat.after(25, lambda: self.chat.input.insert("end-1c", "ㅋ"))
                return "committed"
            return "ready"
        with patch("assistant_ai.ui.prepare_input", side_effect=commit), patch.object(self.owner, "send") as send:
            self.chat.send_button.invoke()
            self.finish_submission()
            send.assert_called_once_with("근데 느림...ㅋ")

    def test_failed_or_hidden_pending_submission_preserves_draft(self):
        self.chat.input.insert("1.0", "아직 조합 중ㅋ")
        with patch("assistant_ai.ui.prepare_input", return_value="failed"), patch.object(self.owner, "send") as send:
            self.chat.send_button.invoke()
            self.finish_submission()
            send.assert_not_called()
        self.assertEqual(self.chat.input.get("1.0", "end-1c"), "아직 조합 중ㅋ")
        self.assertIn("초안은 유지", self.chat.status.get())
        with patch.object(self.owner, "send") as send:
            self.chat.request_send()
            self.chat._hide()
            self.root.update()
            send.assert_not_called()
        self.assertEqual(self.chat.input.get("1.0", "end-1c"), "아직 조합 중ㅋ")

    def test_composition_timeout_keeps_text_and_does_not_send(self):
        self.chat.input.insert("1.0", "확정 대기ㅋ")
        with patch("assistant_ai.ui.prepare_input", return_value="pending"), patch("assistant_ai.ui.time.monotonic", return_value=100) as clock, patch.object(self.owner, "send") as send:
            self.chat.request_send()
            self.root.update()
            self.assertTrue(self.chat._submit_pending)
            clock.return_value = 106
            self.root.after(25, self.root.quit)
            self.root.mainloop()
            send.assert_not_called()
        self.assertFalse(self.chat._submit_pending)
        self.assertEqual(self.chat.input.get("1.0", "end-1c"), "확정 대기ㅋ")

    def test_plain_return_inserts_newline_without_sending(self):
        self.chat.input.focus_force()
        self.root.update()
        self.chat.input.insert("1.0", "줄바꿈ㅋ")
        with patch.object(self.owner, "send") as send:
            self.chat.input.event_generate("<Return>")
            self.root.update()
            send.assert_not_called()
        self.assertEqual(self.chat.input.get("1.0", "end-1c"), "줄바꿈ㅋ\n")

    @unittest.skipUnless(os.name == "nt", "Real Windows IMM context required")
    def test_windows_native_context_accepts_committed_latin_and_korean(self):
        # Calls the real IMM adapter against a focused HWND. Text.insert is
        # already committed input: this does NOT test physical Korean IME.
        from assistant_ai.windows_ime import prepare_input
        self.chat.input.focus_force()
        self.root.update()
        for path, text in (("button", "Latin text 123"), ("keyboard", "이미 확정된 한글ㅋ")):
            with self.subTest(path=path, text=text):
                self.chat.input.delete("1.0", "end")
                self.chat.input.insert("1.0", text)
                self.root.update()
                self.assertEqual(self.chat.input.get("1.0", "end-1c"), text)
                with patch.object(self.owner, "send") as send:
                    self._activate_send(path)
                    self.finish_submission()
                    send.assert_called_once_with(text)
                self.assertIn(prepare_input(self.chat.input.winfo_id(), toplevel_hwnd=self.chat.winfo_id(),
                                            request_commit=False), {"ready", "no_ime"})

    def test_exact_unicode_snapshot_reaches_api_storage_and_reopened_history(self):
        from assistant_ai.service import AssistantService
        from assistant_ai.ui import AssistantWindows
        payloads = []
        def fake_http(request, *, timeout):
            payloads.append(json.loads(request.data.decode("utf-8")))
            return BytesIO(json.dumps({"id": "fake_chat_test", "status": "completed",
                                      "output": [{"type": "message", "content": [{"type": "output_text", "text": "확인했어요"}]}],
                                      "usage": {"input_tokens": 100, "output_tokens": 10, "total_tokens": 110}}).encode())
        with TemporaryDirectory() as directory, patch("assistant_ai.service.KeyVault") as vault, patch("assistant_ai.api._open_responses", side_effect=fake_http):
            vault.return_value.get.return_value = "fake-test-key"
            service = AssistantService(Path(directory))
            service.save_settings(replace(service.load_settings(), enabled=True, conversation_storage_enabled=True))
            self.owner.service = self.chat.service = service
            values = ("근데 느림...ㅋ", "  분해 자모 카 · 이모지 👩🏽‍💻 · 결합 e\u0301\n끝ㅋ \t")
            for path in ("button", "keyboard"):
                for text in values:
                    self.chat.input.insert("1.0", text[:-1])
                    def commit(_hwnd, *, toplevel_hwnd, request_commit):
                        if request_commit:
                            self.chat.after_idle(lambda: self.chat.input.insert("end-1c", text[-1:]))
                            return "committed"
                        return "ready"
                    with patch("assistant_ai.ui.prepare_input", side_effect=commit), patch("assistant_ai.ui.Thread", side_effect=lambda **kw: SimpleNamespace(start=lambda: kw["target"](*kw["args"]))):
                        self._activate_send(path)
                        self.finish_submission()
                        self.owner._poll()
                    self.assertEqual(payloads[-1]["input"][-1], {"role": "user", "content": text})
                    self.assertEqual(service.recent_turns()[-1].user, text)
            self.owner.close()
            restarted = AssistantService(Path(directory))
            self.assertEqual([turn.user for turn in restarted.recent_turns()], list(values) * 2)
            reopened = AssistantWindows(self.root, restarted, context=lambda: {}, dispatch=Mock())
            self.addCleanup(reopened.close)
            reopened.open_chat()
            self.root.update()
            for text in values:
                self.assertIn(text, reopened.chat_window.history.get("1.0", "end-1c"))

    def test_initial_size_uses_screen_and_dpi_without_squeezing_beside_widget(self):
        from assistant_ai.ui import _ChatWindow
        original = float(self.root.tk.call("tk", "scaling"))
        self.addCleanup(lambda: self.root.tk.call("tk", "scaling", original))
        for dpi, area in ((96, (0, 0, 1366, 768)), (144, (0, 0, 1920, 1080)), (192, (0, 0, 1920, 1080))):
            with self.subTest(dpi=dpi):
                self.root.tk.call("tk", "scaling", dpi / 72)
                self.owner.chat_work_area = lambda *_, box=area: box
                window = _ChatWindow(self.owner)
                old_chat = self.owner.chat_window
                self.owner.chat_window = window
                self.owner._place_chat_window()
                window.show()
                self.root.update()
                self.assertGreaterEqual(window.winfo_width(), 900)
                self.assertGreater(window.history.winfo_height(), 200)
                self.assertLessEqual(window.winfo_height(), area[3] - 24)
                self.assertTrue(window.send_button.winfo_viewable())
                self.assertLessEqual(window.send_button.winfo_rooty() + window.send_button.winfo_height(), window.winfo_rooty() + window.winfo_height())
                self.assertEqual(window.resizable(), (1, 1))
                window.destroy()
                self.owner.chat_window = old_chat

    def test_user_resized_client_dimensions_survive_repeated_hide_and_reopen(self):
        for width, height in ((780, 620), (940, 660)):
            expected_client = self.resize_within_display(width, height)
            for repeat in range(4):
                with self.subTest(size=expected_client, repeat=repeat):
                    self.chat._hide()
                    self.owner.open_chat()
                    self.root.update()
                    self.assertEqual((self.chat.winfo_width(), self.chat.winfo_height()), expected_client)


if __name__ == "__main__":
    unittest.main()
