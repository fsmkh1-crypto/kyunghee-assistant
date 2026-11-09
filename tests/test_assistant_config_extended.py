from dataclasses import replace
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from assistant_ai.config import AISettings, ConfigStore, KeyVault, PROACTIVE_EVENTS, SettingsError


FAKE_KEY = "sk-test-fake-key-never-used"


def fake_dpapi(data, *, protect):
    return b"cipher:" + data[::-1] if protect else data.removeprefix(b"cipher:")[::-1]


class ConfigMigrationTests(unittest.TestCase):
    def test_new_defaults_and_complete_round_trip(self):
        with TemporaryDirectory() as directory:
            store = ConfigStore(Path(directory))
            defaults = store.load()
            self.assertFalse(defaults.conversation_storage_enabled)
            self.assertFalse(defaults.memory_enabled)
            self.assertEqual(defaults.key_persistence, "session")
            self.assertFalse(defaults.proactive_enabled)
            self.assertEqual(defaults.proactive_interval_minutes, 20)
            settings = replace(defaults, conversation_storage_enabled=True, web_search_enabled=False,
                               proactive_events=("away", "return"), proactive_quiet_until="2026-11-09",
                               reading_text_size=17, proactive_interval_minutes=35)
            store.save(settings)
            self.assertEqual(store.load(), settings)
            self.assertNotIn(FAKE_KEY, store.path.read_text())

    def test_legacy_memory_choice_migrates_without_overriding_new_choice(self):
        with TemporaryDirectory() as directory:
            store = ConfigStore(Path(directory))
            store.path.write_text(json.dumps({"memory_enabled": True}), encoding="utf-8")
            self.assertTrue(store.load().conversation_storage_enabled)
            store.path.write_text(json.dumps({"memory_enabled": True, "conversation_storage_enabled": False}),
                                  encoding="utf-8")
            self.assertFalse(store.load().conversation_storage_enabled)

    def test_existing_windows_key_keeps_protected_choice_during_migration(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "openai_key.dpapi").write_bytes(b"encrypted-fixture")
            store = ConfigStore(root)
            with patch("assistant_ai.config.os", SimpleNamespace(name="nt")):
                self.assertEqual(store.load().key_persistence, "windows")
                store.path.write_text('{"key_persistence":"session"}', encoding="utf-8")
                self.assertEqual(store.load().key_persistence, "session")

    def test_invalid_new_fields_are_rejected_without_reflecting_values(self):
        for values in (
            {"conversation_storage_enabled": 1}, {"web_search_enabled": "yes"},
            {"key_persistence": FAKE_KEY}, {"proactive_events": ("unknown",)},
            {"proactive_events": ("away", "away")}, {"proactive_events": ["away"]},
            {"proactive_quiet_until": "2026-02-30"}, {"proactive_quiet_until": "20261109"},
            {"reading_text_size": True}, {"reading_text_size": 21},
            {"proactive_interval_minutes": True}, {"proactive_interval_minutes": 4},
            {"proactive_interval_minutes": 121}, {"proactive_interval_minutes": "20"},
        ):
            with self.subTest(values=values), self.assertRaises(SettingsError) as caught:
                replace(AISettings(), **values).validate()
            self.assertNotIn(FAKE_KEY, str(caught.exception))
        replace(AISettings(), proactive_events=()).validate()
        self.assertTrue(PROACTIVE_EVENTS)

    def test_existing_proactive_opt_in_and_event_selection_survive_interval_upgrade(self):
        with TemporaryDirectory() as directory:
            store = ConfigStore(Path(directory))
            store.path.write_text(json.dumps({"enabled": True, "proactive_enabled": True,
                                             "proactive_events": ["return"], "model": "gpt-6.1-sol"}))
            settings = store.load()
            self.assertTrue(settings.proactive_enabled)
            self.assertEqual(settings.proactive_events, ("return",))
            self.assertEqual(settings.model, "gpt-6.1-sol")
            self.assertEqual(settings.proactive_interval_minutes, 20)


class KeyStorageChoiceTests(unittest.TestCase):
    def setUp(self):
        self.directory = self.enterContext(TemporaryDirectory())
        self.root = Path(self.directory)
        windows = SimpleNamespace(name="nt", fsync=os.fsync, replace=os.replace)
        self.enterContext(patch("assistant_ai.config.os", windows))
        self.enterContext(patch("assistant_ai.config._dpapi", side_effect=fake_dpapi))

    def test_fresh_windows_session_key_never_reaches_disk(self):
        vault = KeyVault(self.root)
        self.assertTrue(vault.supports_persistence)
        self.assertFalse(vault.persistent)
        vault.set(FAKE_KEY)
        self.assertEqual(vault.get(), FAKE_KEY)
        self.assertFalse(vault.path.exists())
        self.assertIsNone(KeyVault(self.root).get())

    def test_explicit_persist_reopens_and_session_conversion_removes_blob(self):
        vault = KeyVault(self.root)
        vault.set(FAKE_KEY, persist=True)
        self.assertTrue(vault.persistent)
        self.assertNotIn(FAKE_KEY.encode(), vault.path.read_bytes())
        reopened = KeyVault(self.root)
        self.assertTrue(reopened.persistent)
        self.assertEqual(reopened.get(), FAKE_KEY)
        reopened.set_persistence(False)
        self.assertEqual(reopened.get(), FAKE_KEY)
        self.assertFalse(reopened.persistent)
        self.assertFalse(reopened.path.exists())
        self.assertIsNone(KeyVault(self.root).get())
        reopened.set_persistence(True)
        self.assertEqual(KeyVault(self.root).get(), FAKE_KEY)

    def test_failed_protection_keeps_original_session_key_and_choice(self):
        vault = KeyVault(self.root)
        vault.set(FAKE_KEY)
        with patch("assistant_ai.config._dpapi", side_effect=OSError(FAKE_KEY)):
            with self.assertRaises(SettingsError) as caught:
                vault.set_persistence(True)
        self.assertNotIn(FAKE_KEY, str(caught.exception))
        self.assertEqual(vault.get(), FAKE_KEY)
        self.assertFalse(vault.persistent)
        self.assertFalse(vault.path.exists())

    def test_failed_delete_does_not_replace_key_or_mode(self):
        vault = KeyVault(self.root)
        vault.set(FAKE_KEY, persist=True)
        cipher = vault.path.read_bytes()
        with patch.object(Path, "unlink", side_effect=PermissionError(FAKE_KEY)):
            with self.assertRaises(SettingsError) as caught:
                vault.set("sk-new-fake-only", persist=False)
            with self.assertRaises(SettingsError):
                vault.delete()
        self.assertNotIn(FAKE_KEY, str(caught.exception))
        self.assertTrue(vault.persistent)
        self.assertEqual(vault.path.read_bytes(), cipher)
        self.assertEqual(vault.get(), FAKE_KEY)

    def test_delete_always_removes_stale_blob_in_session_mode(self):
        vault = KeyVault(self.root)
        vault.set(FAKE_KEY)
        vault.path.write_bytes(b"stale-encrypted-key")
        vault.delete()
        self.assertIsNone(vault.get())
        self.assertFalse(vault.path.exists())

    def test_reaffirming_session_mode_removes_stale_blob_and_keeps_current_key(self):
        vault = KeyVault(self.root)
        vault.set(FAKE_KEY)
        vault.path.write_bytes(b"stale-encrypted-key")
        vault.set_persistence(False)
        self.assertEqual(vault.get(), FAKE_KEY)
        self.assertFalse(vault.path.exists())

    def test_new_session_key_can_replace_unreadable_protected_key(self):
        (self.root / "openai_key.dpapi").write_bytes(b"bad-blob")
        vault = KeyVault(self.root)
        with patch("assistant_ai.config._dpapi", side_effect=OSError("cannot decrypt")):
            vault.set(FAKE_KEY, persist=False)
        self.assertEqual(vault.get(), FAKE_KEY)
        self.assertFalse(vault.path.exists())

    def test_unsupported_persistence_is_not_silently_downgraded(self):
        with patch("assistant_ai.config.os", SimpleNamespace(name="posix")):
            vault = KeyVault(self.root)
            vault.set(FAKE_KEY)
            with self.assertRaises(SettingsError):
                vault.set_persistence(True)
            self.assertEqual(vault.get(), FAKE_KEY)
            self.assertFalse(vault.path.exists())


if __name__ == "__main__":
    unittest.main()
