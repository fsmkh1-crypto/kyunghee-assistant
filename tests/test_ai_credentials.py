import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from ai_credentials import (
    AICredentials,
    KEY_FILENAME,
    SecureStorageError,
    WindowsDPAPI,
    normalize_api_key,
)


KEY = "unit-test-credential-123456789"


class MemoryProtector:
    """Opaque test ciphertext without pretending to implement cryptography."""
    available = True

    def __init__(self):
        self.secrets = {}

    def protect(self, plaintext):
        encrypted = b"test-envelope:" + hashlib.sha256(plaintext).digest()
        self.secrets[encrypted] = plaintext
        return encrypted

    def unprotect(self, ciphertext):
        if ciphertext not in self.secrets:
            raise SecureStorageError("invalid_data")
        return self.secrets[ciphertext]


class UnsupportedProtector(MemoryProtector):
    available = False

    def protect(self, plaintext):
        raise AssertionError("An unsupported protector must never be used")


class AICredentialsTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.data_dir = Path(self.directory.name)
        self.protector = MemoryProtector()
        self.credentials = AICredentials(self.data_dir, protector=self.protector)

    def test_default_keeps_key_in_memory_and_creates_no_files(self):
        status = self.credentials.configure_key(KEY, remember=False)
        self.assertTrue(status.ok)
        self.assertFalse(status.remembered)
        self.assertEqual(self.credentials.api_key, KEY)
        self.assertEqual(list(self.data_dir.iterdir()), [])
        self.assertNotIn(KEY, repr(self.credentials))
        self.assertNotIn(KEY, repr(status))

    def test_opt_in_round_trip_has_only_opaque_file_bytes(self):
        status = self.credentials.configure_key(KEY, remember=True)
        self.assertTrue(status.ok)
        self.assertTrue(status.remembered)
        self.assertEqual([item.name for item in self.data_dir.iterdir()], [KEY_FILENAME])
        self.assertNotIn(KEY.encode(), self.credentials.path.read_bytes())
        restored = AICredentials(self.data_dir, protector=self.protector)
        self.assertFalse(restored.has_key)
        loaded = restored.load_saved_key(remember=True)
        self.assertTrue(loaded.ok)
        self.assertTrue(loaded.remembered)
        self.assertEqual(restored.api_key, KEY)

    def test_not_remembering_deletes_previous_file_but_keeps_session_key(self):
        self.credentials.configure_key(KEY, remember=True)
        status = self.credentials.configure_key("", remember=False)
        self.assertTrue(status.ok)
        self.assertFalse(self.credentials.path.exists())
        self.assertEqual(self.credentials.api_key, KEY)

    def test_startup_without_remembering_never_loads_old_file(self):
        self.credentials.configure_key(KEY, remember=True)
        restored = AICredentials(self.data_dir, protector=self.protector)
        self.assertTrue(restored.load_saved_key(remember=False).ok)
        self.assertEqual(restored.api_key, "")
        self.assertFalse(restored.path.exists())

    def test_blank_input_preserves_loaded_session_key(self):
        self.credentials.configure_key(KEY, remember=True)
        restored = AICredentials(self.data_dir, protector=self.protector)
        restored.load_saved_key(remember=True)
        self.assertTrue(restored.configure_key("  ", remember=True).ok)
        self.assertEqual(restored.api_key, KEY)

    def test_unsupported_platform_has_no_plaintext_fallback(self):
        credentials = AICredentials(self.data_dir, protector=UnsupportedProtector())
        status = credentials.configure_key(KEY, remember=True)
        self.assertFalse(status.ok)
        self.assertEqual(status.code, "unsupported_platform")
        self.assertFalse(status.remembered)
        self.assertEqual(credentials.api_key, KEY)
        self.assertEqual(list(self.data_dir.iterdir()), [])

    def test_failed_encryption_keeps_session_key_and_removes_stale_key(self):
        self.credentials.configure_key("old-unit-test-key", remember=True)
        with mock.patch.object(self.protector, "protect", side_effect=RuntimeError(KEY)):
            status = self.credentials.configure_key(KEY, remember=True)
        self.assertFalse(status.ok)
        self.assertEqual(status.code, "save_failed")
        self.assertEqual(self.credentials.api_key, KEY)
        self.assertNotIn(KEY, repr(status))
        self.assertEqual(list(self.data_dir.iterdir()), [])

    def test_failed_atomic_replace_cleans_encrypted_temp_and_keeps_session(self):
        with mock.patch("ai_credentials.os.replace", side_effect=PermissionError(KEY)):
            status = self.credentials.configure_key(KEY, remember=True)
        self.assertFalse(status.ok)
        self.assertEqual(self.credentials.api_key, KEY)
        self.assertNotIn(KEY, status.message)
        self.assertEqual(list(self.data_dir.iterdir()), [])

    def test_every_write_is_encrypted_even_before_atomic_replace(self):
        observed = []
        replace = os.replace

        def inspect_replace(source, destination):
            observed.append(Path(source).read_bytes())
            self.assertEqual(Path(destination), self.credentials.path)
            self.assertNotIn(KEY.encode(), observed[-1])
            return replace(source, destination)

        with mock.patch("ai_credentials.os.replace", side_effect=inspect_replace):
            self.assertTrue(self.credentials.configure_key(KEY, remember=True).ok)
        self.assertEqual(len(observed), 1)
        self.assertEqual(observed[0], self.credentials.path.read_bytes())

    def test_corrupt_oversized_or_unreadable_file_never_becomes_session_key(self):
        for content in (KEY.encode(), b"KYUNGHEE_DPAPI_V1\x00bad", b"x" * (64 * 1024 + 1)):
            with self.subTest(size=len(content)):
                self.credentials.path.write_bytes(content)
                status = self.credentials.load_saved_key(remember=True)
                self.assertFalse(status.ok)
                self.assertFalse(self.credentials.has_key)
                self.assertNotIn(KEY, status.message)

    def test_missing_saved_key_is_safe_and_does_not_create_a_file(self):
        status = self.credentials.load_saved_key(remember=True)
        self.assertTrue(status.ok)
        self.assertFalse(status.remembered)
        self.assertFalse(self.credentials.has_key)
        self.assertEqual(list(self.data_dir.iterdir()), [])

    def test_clear_removes_both_session_and_saved_key(self):
        self.credentials.configure_key(KEY, remember=True)
        self.assertTrue(self.credentials.clear().ok)
        self.assertFalse(self.credentials.has_key)
        self.assertFalse(self.credentials.path.exists())

    def test_failed_delete_reports_safe_status_and_still_clears_memory(self):
        self.credentials.configure_key(KEY, remember=True)
        with mock.patch.object(Path, "unlink", side_effect=PermissionError(KEY)):
            status = self.credentials.clear()
        self.assertFalse(status.ok)
        self.assertEqual(status.code, "delete_failed")
        self.assertFalse(self.credentials.has_key)
        self.assertTrue(self.credentials.path.exists())
        self.assertNotIn(KEY, repr(status))

    def test_bad_key_format_preserves_existing_key(self):
        self.credentials.configure_key(KEY, remember=False)
        for bad in ("header\r\ninjection", "embedded space", "not-ascii-가", "x" * 4097):
            with self.subTest(bad=bad[:30]):
                status = self.credentials.configure_key(bad, remember=True)
                self.assertFalse(status.ok)
                self.assertEqual(status.code, "invalid_key_format")
                self.assertEqual(self.credentials.api_key, KEY)
                self.assertFalse(self.credentials.path.exists())
        self.assertEqual(normalize_api_key("  " + KEY + "\n"), KEY)

    @unittest.skipIf(os.name == "nt", "Checks the intentionally unsupported non-Windows path")
    def test_production_store_is_fail_closed_outside_windows(self):
        credentials = AICredentials(self.data_dir)
        self.assertFalse(credentials.supports_persistence)
        self.assertFalse(credentials.configure_key(KEY, remember=True).ok)
        self.assertEqual(credentials.api_key, KEY)
        self.assertEqual(list(self.data_dir.iterdir()), [])
        with self.assertRaises(SecureStorageError):
            WindowsDPAPI().protect(KEY.encode())

    @unittest.skipUnless(os.name == "nt", "Requires the real Windows current-user DPAPI")
    def test_real_windows_dpapi_round_trip_and_tampering(self):
        protector = WindowsDPAPI()
        encrypted = protector.protect(KEY.encode())
        self.assertNotIn(KEY.encode(), encrypted)
        self.assertEqual(protector.unprotect(encrypted), KEY.encode())
        with self.assertRaises(SecureStorageError):
            protector.unprotect(encrypted[:-8] + b"tampered")


if __name__ == "__main__":
    unittest.main()
