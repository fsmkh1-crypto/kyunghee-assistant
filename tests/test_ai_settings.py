from dataclasses import asdict
import json
from pathlib import Path
import queue
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest import mock

from ai_credentials import AICredentials
from ai_settings_ui import AISettingsPanel, DATA_NOTICE, KEY_NOTICE
from settings import UserSettings, load_user_settings, save_user_settings, settings_from_dict


KEY = "unit-test-credential-987654321"


class MainThreadVar:
    def __init__(self, value):
        self.value = value
        self.owner = threading.get_ident()

    def get(self):
        assert threading.get_ident() == self.owner, "Tk read in worker"
        return self.value

    def set(self, value):
        assert threading.get_ident() == self.owner, "Tk write in worker"
        self.value = value


class AISettingsTests(unittest.TestCase):
    def test_existing_settings_keep_all_preferences_and_default_ai_off(self):
        previous = asdict(UserSettings(
            always_on_top=True, custom_dialogue="저장된 대사", personality="playful",
            message_text_size=11, image_warning="custom.png", window_x=-900,
        ))
        previous.pop("ai_enabled")
        previous.pop("ai_remember_key")
        loaded = settings_from_dict(previous)
        self.assertFalse(loaded.ai_enabled)
        self.assertFalse(loaded.ai_remember_key)
        self.assertEqual({name: getattr(loaded, name) for name in previous}, previous)

    def test_only_real_booleans_enable_ai_or_key_remembering(self):
        for value in ("true", "false", 1, 0, None, [], {}):
            with self.subTest(value=value):
                loaded = settings_from_dict({"ai_enabled": value, "ai_remember_key": value})
                self.assertFalse(loaded.ai_enabled)
                self.assertFalse(loaded.ai_remember_key)
        loaded = settings_from_dict({"ai_enabled": True, "ai_remember_key": True})
        self.assertTrue(loaded.ai_enabled)
        self.assertTrue(loaded.ai_remember_key)

    def test_key_in_untrusted_ordinary_settings_is_ignored_and_never_saved(self):
        loaded = settings_from_dict({
            "ai_enabled": True, "ai_remember_key": True,
            "api_key": KEY, "ai_api_key": KEY, "openai_api_key": KEY,
        })
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            save_user_settings(path, loaded)
            content = path.read_text(encoding="utf-8")
            self.assertNotIn(KEY, content)
            raw = json.loads(content)
            self.assertEqual({name for name in raw if name.startswith("ai_")}, {"ai_enabled", "ai_remember_key"})
            self.assertEqual(load_user_settings(path), loaded)

    def test_larger_new_install_message_font_preserves_saved_size(self):
        self.assertEqual(UserSettings().message_text_size, 13)
        self.assertEqual(settings_from_dict({"message_text_size": 11}).message_text_size, 11)
        self.assertEqual(settings_from_dict({"message_text_size": 9}).message_text_size, 9)

    def test_notices_explain_transmission_and_separate_api_billing(self):
        for item in ("TLS", "HTTPS", "프로젝트", "ChatGPT", "별도"):
            self.assertIn(item, KEY_NOTICE)
        for item in ("이벤트 시각", "실제 사용", "연속 사용", "자리비움", "휴식", "오늘 주요 이벤트", "프리셋", "최근 대사", "대화"):
            self.assertIn(item, DATA_NOTICE)


class AISettingsPanelTests(unittest.TestCase):
    """Test the panel's side effects headlessly with thread-checked Tk stand-ins."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        panel = object.__new__(AISettingsPanel)
        self.panel = panel
        panel.credentials = AICredentials(Path(self.directory.name))
        panel.enabled_var = MainThreadVar(True)
        panel.remember_var = MainThreadVar(False)
        panel.key_var = MainThreadVar("")
        panel.status_var = MainThreadVar("")
        panel.theme = {"good": "green", "warning": "orange"}
        panel._on_apply = mock.Mock()
        panel._closed = False
        panel._testing = False
        panel._generation = 0
        panel._poll_job = None
        panel._test_results = queue.Queue(maxsize=1)
        panel.test_button = SimpleNamespace(configure=lambda **kw: self.assert_main_thread())
        panel.status_label = SimpleNamespace(configure=lambda **kw: self.assert_main_thread())
        panel.after = mock.Mock(side_effect=lambda *_args: self.after_main_thread())
        panel.after_cancel = mock.Mock()
        self.owner = threading.get_ident()

    def assert_main_thread(self):
        self.assertEqual(threading.get_ident(), self.owner)

    def after_main_thread(self):
        self.assert_main_thread()
        return "poll-id"

    def wait_and_poll(self):
        result = self.panel._test_results.get(timeout=2)
        self.panel._test_results.put_nowait(result)
        self.panel._poll_test_result()

    def test_apply_holds_key_in_controller_and_only_passes_booleans_plus_session_key(self):
        self.panel.key_var.set(KEY)
        self.panel.apply()
        self.panel._on_apply.assert_called_once_with(True, False, KEY)
        self.assertEqual(self.panel.credentials.api_key, KEY)
        self.assertEqual(self.panel.key_var.get(), "")
        self.assertNotIn(KEY, self.panel.status_var.get())

    def test_failed_key_storage_still_applies_session_key_with_remember_off(self):
        self.panel.key_var.set(KEY)
        self.panel.remember_var.set(True)
        with mock.patch.object(AICredentials, "supports_persistence", new_callable=mock.PropertyMock, return_value=False):
            self.panel.apply()
        self.panel._on_apply.assert_called_once_with(True, False, KEY)
        self.assertFalse(self.panel.remember_var.get())
        self.assertIn("실행 중", self.panel.status_var.get())
        self.assertNotIn(KEY, self.panel.status_var.get())

    def test_callback_exception_text_never_reaches_status(self):
        self.panel.key_var.set(KEY)
        self.panel._on_apply.side_effect = RuntimeError(KEY)
        self.panel.apply()
        self.assertNotIn(KEY, self.panel.status_var.get())
        self.assertIn("저장하지 못", self.panel.status_var.get())

    def test_clear_removes_session_key_and_reconfigures_runtime(self):
        self.panel.credentials.configure_key(KEY, False)
        self.panel.key_var.set(KEY)
        self.panel.clear_key()
        self.assertFalse(self.panel.credentials.has_key)
        self.assertEqual(self.panel.key_var.get(), "")
        self.panel._on_apply.assert_called_once_with(True, False, "")

    def test_connection_runs_in_worker_and_returns_to_main_thread(self):
        self.panel.key_var.set(KEY)
        network_thread = []

        def connect(key):
            self.assertEqual(key, KEY)
            network_thread.append(threading.get_ident())
            return SimpleNamespace(ok=True, error_code="")

        self.panel._test_connection = connect
        self.panel.test_connection()
        self.wait_and_poll()
        self.assertEqual(len(network_thread), 1)
        self.assertNotEqual(network_thread[0], self.owner)
        self.assertIn("연결을 확인", self.panel.status_var.get())
        self.assertFalse(self.panel._testing)
        self.assertEqual(self.panel.credentials.api_key, "")
        self.assertNotIn(KEY, self.panel.status_var.get())

    def test_off_or_missing_key_makes_no_network_request(self):
        self.panel._test_connection = mock.Mock()
        self.panel.enabled_var.set(False)
        self.panel.key_var.set(KEY)
        self.panel.test_connection()
        self.panel.enabled_var.set(True)
        self.panel.key_var.set("")
        self.panel.test_connection()
        self.panel._test_connection.assert_not_called()

    def test_worker_exception_and_untrusted_error_code_are_sanitized(self):
        for result in (RuntimeError(KEY), SimpleNamespace(ok=False, error_code=KEY)):
            with self.subTest(result_type=type(result).__name__):
                self.panel.key_var.set(KEY)
                if isinstance(result, Exception):
                    self.panel._test_connection = mock.Mock(side_effect=result)
                else:
                    self.panel._test_connection = mock.Mock(return_value=result)
                self.panel.test_connection()
                self.wait_and_poll()
                self.assertNotIn(KEY, self.panel.status_var.get())
                self.assertFalse(self.panel._testing)

    def test_refresh_never_fills_key_entry_and_ignores_old_connection_result(self):
        self.panel.key_var.set(KEY)
        self.panel._test_connection = lambda _key: SimpleNamespace(ok=True, error_code="")
        self.panel.test_connection()
        self.panel.refresh(UserSettings(ai_enabled=False))
        self.panel.status_var.set("new-status")
        self.wait_and_poll()
        self.assertEqual(self.panel.status_var.get(), "new-status")
        self.assertEqual(self.panel.key_var.get(), "")
        self.assertFalse(self.panel.enabled_var.get())

    def test_unchecking_remember_deletes_saved_file_without_clearing_session(self):
        self.panel.credentials.configure_key(KEY, False)
        self.panel.credentials.path.write_bytes(b"opaque-test-encrypted-file")
        self.panel._remember_toggled()
        self.assertFalse(self.panel.credentials.path.exists())
        self.assertEqual(self.panel.credentials.api_key, KEY)


if __name__ == "__main__":
    unittest.main()
