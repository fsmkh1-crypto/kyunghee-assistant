from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

from PIL import Image

from assistant_ai.config import AISettings
from settings import UserSettings
from state import fresh_state, save_state
import user_data_backup as backup


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.profile = self.base / "profile"
        self.profile.mkdir()
        self.archive = self.base / "data.seunga-backup.zip"

    def tearDown(self):
        self.temp.cleanup()

    def write_json(self, name, value, profile=None):
        path = (profile or self.profile) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def seed(self):
        save_state(self.profile / "state.json", fresh_state(), 100)
        self.write_json("settings.json", asdict(UserSettings()))
        self.write_json("ai_settings.json", asdict(AISettings()))
        image = self.profile / "images" / "face.png"
        image.parent.mkdir()
        Image.new("RGBA", (8, 8), "red").save(image)
        settings = asdict(UserSettings(image_profile=str(image)))
        self.write_json("settings.json", settings)
        self.write_json("image_sets/image_sets.json", {"schema_version": 1, "roles": {"default": {"images": ["roles/default/a.png"]}}})
        path = self.profile / "image_sets/roles/default/a.png"
        path.parent.mkdir(parents=True)
        Image.new("RGB", (8, 8), "blue").save(path)

    def memory(self, *, legacy=False):
        db = sqlite3.connect(self.profile / "memory.sqlite3")
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA wal_autocheckpoint=0")
        for table, (columns, definition) in backup._DB_SCHEMAS["memory.sqlite3"].items():
            if legacy and table in {"storage_state", "memories", "conversation_turns"}:
                definition = definition.rsplit(",", 1)[0]
            db.execute(f"CREATE TABLE {table} ({definition})")
        db.execute("INSERT INTO storage_state VALUES (1, 1, 3" + (")" if legacy else ", 1)"))
        db.execute("INSERT INTO conversation_turns (id,user_text,assistant_text,created_at,generation) VALUES (1,'hello','answer','2026-01-01',3)")
        db.execute("INSERT INTO memories VALUES (1,'remember','remember','2026-01-01'" + (")" if legacy else ", 1)"))
        db.commit()
        return db

    def rewrite_archive(self, mutate):
        with zipfile.ZipFile(self.archive) as source:
            files = {info.filename: source.read(info) for info in source.infolist()}
        manifest = json.loads(files["manifest.json"])
        mutate(files, manifest)
        files["manifest.json"] = json.dumps(manifest).encode()
        with zipfile.ZipFile(self.archive, "w") as target:
            for name, data in files.items():
                target.writestr(name, data)

    def test_selective_backup_excludes_keys_logs_unknown_fields_and_rebases_images(self):
        self.seed()
        secret = "sk-proj-" + "Q" * 40
        settings = json.loads((self.profile / "settings.json").read_text())
        settings.update(api_key=secret, credentials={"token": secret}, custom_dialogue="api_key=" + secret)
        self.write_json("settings.json", settings)
        (self.profile / "openai_key.dpapi").write_bytes(b"private vault content")
        (self.profile / "kyunghee.log").write_text(secret)
        (self.profile / "images" / "credentials.json").write_text(secret)
        backup.create_backup(self.profile, self.archive, ("settings", "images"))
        with zipfile.ZipFile(self.archive) as bundle:
            self.assertNotIn("data/state.json", bundle.namelist())
            self.assertNotIn("data/openai_key.dpapi", bundle.namelist())
            contents = b"".join(bundle.read(n) for n in bundle.namelist())
            self.assertNotIn(secret.encode(), contents)
            self.assertNotIn(b"private vault content", contents)
            raw = json.loads(bundle.read("data/settings.json"))
            self.assertEqual(raw["image_profile"], "$DATA/images/face.png")
            self.assertNotIn("api_key", raw)

    def test_live_sqlite_backup_captures_committed_wal_but_not_uncommitted_rows(self):
        with self.memory() as connection:
            connection.execute("INSERT INTO conversation_turns (id,user_text,assistant_text,created_at,generation) VALUES (2,'committed WAL',NULL,'2026-01-02',3)")
            connection.commit()
            connection.execute("INSERT INTO conversation_turns (id,user_text,assistant_text,created_at,generation) VALUES (3,'uncommitted',NULL,'2026-01-03',3)")
            backup.create_backup(self.profile, self.archive, ("chat",))
            with zipfile.ZipFile(self.archive) as bundle:
                target = self.base / "saved.sqlite3"
                target.write_bytes(bundle.read("data/memory.sqlite3"))
            with sqlite3.connect(target) as restored:
                self.assertEqual(restored.execute("SELECT user_text FROM conversation_turns ORDER BY id").fetchall(), [("hello",), ("committed WAL",)])
            connection.rollback()
        connection.close()

    def test_database_rebuild_removes_deleted_pages_and_redacts_credentials(self):
        connection = self.memory()
        secret = "sk-proj-" + "A" * 40
        connection.execute("PRAGMA secure_delete=OFF")
        connection.execute("INSERT INTO conversation_turns (id,user_text,assistant_text,created_at,generation) VALUES (2,?,NULL,'2026-01-02',3)", ("deleted secret " + secret,))
        connection.execute("INSERT INTO conversation_turns (id,user_text,assistant_text,created_at,generation) VALUES (3,?,NULL,'2026-01-03',3)", ("key " + secret,))
        connection.commit()
        connection.execute("DELETE FROM conversation_turns WHERE id=2")
        connection.commit()
        backup.create_backup(self.profile, self.archive, ("chat",))
        connection.close()
        with zipfile.ZipFile(self.archive) as bundle:
            content = bundle.read("data/memory.sqlite3")
        self.assertNotIn(secret.encode(), content)
        self.assertNotIn(b"deleted secret", content)

    def test_legacy_database_upgrade_retains_history_consent(self):
        connection = self.memory(legacy=True)
        connection.close()
        backup.create_backup(self.profile, self.archive, ("chat",))
        destination = self.base / "new"
        backup.restore_backup(self.archive, destination, ("chat",), app_is_quiescent=True)
        with sqlite3.connect(destination / "memory.sqlite3") as db:
            self.assertEqual(db.execute("SELECT history_enabled FROM storage_state").fetchone(), (1,))
            self.assertEqual(db.execute("SELECT pinned FROM memories").fetchone(), (0,))
            self.assertEqual(db.execute("SELECT status FROM conversation_turns").fetchone(), ("completed",))

    def test_current_memory_and_usage_schema_round_trip_preserves_status_pin_and_purpose(self):
        from assistant_ai.api import UsageLedger
        from assistant_ai.memory import MemoryStore
        memory = MemoryStore(self.profile / "memory.sqlite3")
        memory.set_enabled(True)
        memory.set_history_enabled(True)
        completed = memory.begin_turn("hello")
        memory.finish_turn(completed, "answer")
        failed = memory.begin_turn("retry later")
        memory.update_turn_status(failed, "failed")
        item = memory.add_memory("remember this")
        memory.set_memory_pinned(item.id, True)
        ledger = UsageLedger(self.profile)
        with ledger._connection() as db:
            db.execute("INSERT INTO calls VALUES (1,'2026-01-01','2026-01-01','gpt-5.4-mini','complete',10,5,15,100,'chat')")
        backup.create_backup(self.profile, self.archive, ("chat",))
        destination = self.base / "destination"
        backup.restore_backup(self.archive, destination, ("chat",), app_is_quiescent=True)
        with sqlite3.connect(destination / "memory.sqlite3") as db:
            self.assertEqual(db.execute("SELECT status FROM conversation_turns ORDER BY id").fetchall(), [("completed",), ("failed",)])
            self.assertEqual(db.execute("SELECT pinned FROM memories").fetchone(), (1,))
        with sqlite3.connect(destination / "ai_usage.sqlite3") as db:
            self.assertEqual(db.execute("SELECT purpose,total_tokens FROM calls").fetchone(), ("chat", 15))

    def test_settings_restore_preserves_protected_key_across_two_service_starts(self):
        from assistant_ai.config import ConfigStore, KeyVault
        from assistant_ai.service import AssistantService
        windows = SimpleNamespace(name="nt", fsync=os.fsync, replace=os.replace)
        def crypto(data, *, protect):
            return b"encrypted:" + data[::-1] if protect else data.removeprefix(b"encrypted:")[::-1]
        with patch("assistant_ai.config.os", windows), patch("assistant_ai.config._dpapi", side_effect=crypto):
            ConfigStore(self.profile).save(AISettings(key_persistence="session"))
            backup.create_backup(self.profile, self.archive, ("settings",))
            for policy in ("windows", "session", None):
                with self.subTest(destination_policy=policy):
                    destination = self.base / ("destination-" + str(policy))
                    destination.mkdir()
                    key = "sk-fake-backup-regression-only"
                    KeyVault(destination).set(key, persist=True)
                    blob = destination / "openai_key.dpapi"
                    original = blob.read_bytes()
                    if policy is not None:
                        ConfigStore(destination).save(AISettings(key_persistence=policy))
                    backup.restore_backup(self.archive, destination, ("settings",), app_is_quiescent=True)
                    self.assertEqual(ConfigStore(destination).load().key_persistence, "windows")
                    for _ in range(2):
                        service = AssistantService(destination)
                        self.assertTrue(service.has_key)
                        self.assertEqual(service._vault.get(), key)
                        self.assertEqual(blob.read_bytes(), original)

    def test_restore_does_not_import_source_key_storage_policy(self):
        from assistant_ai.config import ConfigStore
        ConfigStore(self.profile).save(AISettings(key_persistence="windows"))
        backup.create_backup(self.profile, self.archive, ("settings",))
        destination = self.base / "destination"
        destination.mkdir()
        ConfigStore(destination).save(AISettings(key_persistence="session"))
        backup.restore_backup(self.archive, destination, ("settings",), app_is_quiescent=True)
        self.assertEqual(ConfigStore(destination).load().key_persistence, "session")
        self.assertFalse((destination / "openai_key.dpapi").exists())
        # An old archive without ai_settings must retain destination policy too.
        (self.profile / "ai_settings.json").unlink()
        backup.create_backup(self.profile, self.archive, ("settings",))
        ConfigStore(destination).save(AISettings(key_persistence="windows"))
        backup.restore_backup(self.archive, destination, ("settings",), app_is_quiescent=True)
        self.assertEqual(ConfigStore(destination).load().key_persistence, "windows")

    def test_destination_key_policy_falls_back_without_reading_key_content(self):
        self.write_json("ai_settings.json", {"key_persistence": "windows"})
        self.assertEqual(backup._destination_key_persistence(self.profile), "windows")
        (self.profile / "ai_settings.json").write_text("broken JSON")
        self.assertEqual(backup._destination_key_persistence(self.profile), "session")
        (self.profile / "openai_key.dpapi").write_bytes(b"protected bytes never read")
        with patch.object(backup, "_read_limited", side_effect=AssertionError("must not read protected content")):
            self.assertEqual(backup._destination_key_persistence(self.profile), "windows")
        (self.profile / "openai_key.dpapi").unlink()
        with patch.object(backup, "_read_limited", side_effect=PermissionError("unreadable settings")):
            self.assertEqual(backup._destination_key_persistence(self.profile), "session")

    def test_restore_is_selective_creates_current_backup_and_rebases_paths(self):
        self.seed()
        backup.create_backup(self.profile, self.archive, ("timer", "settings", "images"))
        destination = self.base / "destination"
        destination.mkdir()
        self.write_json("settings.json", asdict(UserSettings(always_on_top=True)), destination)
        (destination / "state.json").write_text("leave timer unchanged")
        (destination / "openai_key.dpapi").write_bytes(b"keep key")
        result = backup.restore_backup(self.archive, destination, ("settings", "images"), app_is_quiescent=True)
        self.assertTrue(result.recovery_backup.is_file())
        self.assertFalse(json.loads((destination / "settings.json").read_text())["always_on_top"])
        self.assertEqual(json.loads((destination / "settings.json").read_text())["image_profile"], str(destination / "images/face.png"))
        self.assertTrue((destination / "images/face.png").is_file())
        self.assertEqual((destination / "state.json").read_text(), "leave timer unchanged")
        self.assertEqual((destination / "openai_key.dpapi").read_bytes(), b"keep key")
        with zipfile.ZipFile(result.recovery_backup) as bundle:
            self.assertTrue(json.loads(bundle.read("data/settings.json"))["always_on_top"])

    def test_restore_requires_quiescence_and_unchanged_preview(self):
        self.seed()
        preview = backup.create_backup(self.profile, self.archive, ("timer",))
        with self.assertRaises(backup.BackupError):
            backup.restore_backup(self.archive, self.profile, ("timer",))
        with self.assertRaises(backup.BackupError):
            backup.restore_backup(self.archive, self.profile, ("timer",), app_is_quiescent=True, expected_fingerprint="other")
        self.assertNotEqual(preview.fingerprint, "other")
        self.assertFalse((self.profile / "backups").exists())

    def test_startup_guard_detects_unfinished_journal_but_ignores_committed(self):
        self.assertEqual(backup.unfinished_restore_journals(self.profile), ())
        self.assertEqual(backup.unfinished_restore_journals(self.base / "missing"), ())
        committed = self.profile / ".restore-journal-done"
        committed.mkdir()
        (committed / "committed").touch()
        self.assertEqual(backup.unfinished_restore_journals(self.profile), ())
        unfinished = self.profile / ".restore-journal-incomplete"
        unfinished.mkdir()
        self.assertEqual(backup.unfinished_restore_journals(self.profile), (unfinished,))
        self.assertTrue(unfinished.is_dir())  # Guard never removes recovery data.

    def test_startup_guard_does_not_trust_linked_commit_marker(self):
        unfinished = self.profile / ".restore-journal-incomplete"
        unfinished.mkdir()
        marker = self.base / "outside-marker"
        marker.touch()
        try:
            (unfinished / "committed").symlink_to(marker)
        except OSError:
            self.skipTest("symlinks unavailable")
        self.assertEqual(backup.unfinished_restore_journals(self.profile), (unfinished,))

    def test_legacy_single_image_basename_survives_backup_and_restore(self):
        self.seed()
        self.write_json("settings.json", asdict(UserSettings(image_profile="face.png")))
        backup.create_backup(self.profile, self.archive, ("settings", "images"))
        destination = self.base / "destination"
        backup.restore_backup(self.archive, destination, ("settings", "images"), app_is_quiescent=True)
        path = Path(json.loads((destination / "settings.json").read_text())["image_profile"])
        self.assertEqual(path, destination / "images/face.png")
        self.assertTrue(path.is_file())

    def test_manual_image_follow_groups_and_imported_assets_survive(self):
        self.seed()
        values = {"__base_set__": "pack:11", "rest": "__follow_selected_set__",
                  "default": "userset-group:" + json.dumps(["user:face.png", "userset:roles/default/a.png"]),
                  "away": "imported:away/away_11.png"}
        self.write_json("manual_asset_overrides.json", values)
        image = self.profile / "imported_assets/away/away_11.png"
        image.parent.mkdir(parents=True)
        Image.new("RGB", (8, 8), "blue").save(image)
        self.write_json("imported_assets/asset_pack_adoption.json", {"copied": ["11"]})
        backup.create_backup(self.profile, self.archive, ("images",))
        destination = self.base / "destination"
        backup.restore_backup(self.archive, destination, ("images",), app_is_quiescent=True)
        self.assertEqual(json.loads((destination / "manual_asset_overrides.json").read_text()), values)
        self.assertTrue((destination / "imported_assets/away/away_11.png").is_file())
        self.assertFalse((destination / "imported_assets/asset_pack_adoption.json").exists())

    def test_failure_after_replacement_rolls_back_all_original_data(self):
        self.seed()
        backup.create_backup(self.profile, self.archive, ("settings", "images"))
        old_settings = self.write_json("settings.json", asdict(UserSettings(always_on_top=True))).read_bytes()
        (self.profile / "images/face.png").write_bytes(b"original current bytes")
        # Recovery backup requires valid current image data, just as a real restore.
        Image.new("RGB", (10, 10), "green").save(self.profile / "images/face.png")
        old_image = (self.profile / "images/face.png").read_bytes()
        real_replace = backup.os.replace
        def failing_replace(src, dst):
            if Path(src).name == "images" and Path(src).parent.name == "staged":
                raise OSError("injected write failure")
            return real_replace(src, dst)
        with patch.object(backup.os, "replace", side_effect=failing_replace):
            with self.assertRaisesRegex(backup.BackupError, "되돌렸"):
                backup.restore_backup(self.archive, self.profile, ("settings", "images"), app_is_quiescent=True)
        self.assertEqual((self.profile / "settings.json").read_bytes(), old_settings)
        self.assertEqual((self.profile / "images/face.png").read_bytes(), old_image)
        self.assertFalse(list(self.profile.glob(".restore-journal-*")))
        self.assertEqual(len(list((self.profile / "backups").glob("*.zip"))), 1)

    def test_failed_rollback_keeps_originals_and_requires_exit(self):
        self.seed()
        backup.create_backup(self.profile, self.archive, ("settings",))
        original = self.write_json("settings.json", asdict(UserSettings(always_on_top=True))).read_bytes()
        real_replace = backup.os.replace
        def failure(src, dst):
            if Path(src).name == "ai_settings.json" and Path(src).parent.name == "staged":
                raise OSError("apply failed")
            if Path(src).name == "settings.json" and Path(src).parent.name == "originals":
                raise OSError("rollback failed")
            return real_replace(src, dst)
        with patch.object(backup.os, "replace", side_effect=failure):
            with self.assertRaises(backup.RestoreRecoveryError) as error:
                backup.restore_backup(self.archive, self.profile, ("settings",), app_is_quiescent=True)
        self.assertTrue(error.exception.recovery_backup.is_file())
        journal = next(self.profile.glob(".restore-journal-*"))
        self.assertEqual((journal / "originals/settings.json").read_bytes(), original)

    def test_bad_json_or_sqlite_is_rejected_without_overwrite(self):
        self.seed()
        backup.create_backup(self.profile, self.archive, ("timer",))
        def corrupt(files, manifest):
            data = b"{ broken json"
            files["data/state.json"] = data
            manifest["files"][0].update(size=len(data), sha256=hashlib.sha256(data).hexdigest())
        self.rewrite_archive(corrupt)
        original = (self.profile / "state.json").read_bytes()
        with self.assertRaises(backup.BackupError):
            backup.restore_backup(self.archive, self.profile, ("timer",), app_is_quiescent=True)
        self.assertEqual((self.profile / "state.json").read_bytes(), original)
        (self.profile / "memory.sqlite3").write_bytes(b"not SQLite")
        with self.assertRaises(backup.BackupError):
            backup.create_backup(self.profile, self.base / "bad.zip", ("chat",))

    def test_invalid_timer_numbers_and_dates_are_safe_validation_errors(self):
        for daily in ({"day": "2026-99-99"}, {"day": None}, {"active_seconds": 10 ** 400}, {"away_count": -1}, {"away_count": 0.5}):
            with self.subTest(daily=daily):
                self.write_json("state.json", {"daily": daily})
                with self.assertRaises(backup.BackupError):
                    backup.create_backup(self.profile, self.archive, ("timer",))
        self.write_json("settings.json", {"widget_scale": 10 ** 400})
        self.assertNotIn("widget_scale", backup.diagnostic_report(self.profile)["safe_configuration"]["settings.json"])

    def test_tampered_hash_and_traversal_rejected(self):
        self.seed()
        backup.create_backup(self.profile, self.archive, ("timer",))
        self.rewrite_archive(lambda files, manifest: files.update({"data/state.json": b"{}"}))
        with self.assertRaises(backup.BackupError):
            backup.inspect_backup(self.archive)
        for name in ("../escape", "data/../../escape", "C:/secret", "data/images/a\\b.png", "data/images/CON.png", "data/images/a.png:secret"):
            with self.subTest(name=name):
                with zipfile.ZipFile(self.archive, "w") as bundle:
                    bundle.writestr(name, "no")
                with self.assertRaises(backup.BackupError):
                    backup.inspect_backup(self.archive)
        self.assertFalse((self.base / "escape").exists())

    def test_archive_links_duplicates_bombs_and_image_packs_rejected(self):
        info = zipfile.ZipInfo("data/images/shortcut.png")
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        with zipfile.ZipFile(self.archive, "w") as bundle:
            bundle.writestr(info, "/etc/passwd")
        with self.assertRaises(backup.BackupError):
            backup.inspect_backup(self.archive)
        with zipfile.ZipFile(self.archive, "w") as bundle:
            bundle.writestr("data/images/A.png", "one")
            bundle.writestr("data/images/a.png", "two")
        with self.assertRaises(backup.BackupError):
            backup.inspect_backup(self.archive)
        with zipfile.ZipFile(self.archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
            bundle.writestr("data/images/bomb.png", b"0" * 2_000_000)
        with self.assertRaises(backup.BackupError):
            backup.inspect_backup(self.archive)
        with zipfile.ZipFile(self.archive, "w") as bundle:
            bundle.writestr("default/default_01.png", b"image pack")
        with self.assertRaisesRegex(backup.BackupError, "이미지 ZIP"):
            backup.inspect_backup(self.archive)

    def test_symlink_source_and_target_are_rejected(self):
        self.seed()
        backup.create_backup(self.profile, self.archive, ("images",))
        outside = self.base / "outside.png"
        Image.new("RGB", (8, 8), "green").save(outside)
        link = self.profile / "images" / "link.png"
        try:
            link.symlink_to(outside)
        except OSError:
            self.skipTest("symlinks unavailable")
        with self.assertRaises(backup.BackupError):
            backup.create_backup(self.profile, self.base / "linked.zip", ("images",))
        with self.assertRaises(backup.BackupError):
            backup.restore_backup(self.archive, self.profile, ("images",), app_is_quiescent=True)

    def test_diagnostics_are_allowlisted_and_cannot_overwrite_profile(self):
        self.write_json("settings.json", {"always_on_top": True, "custom_dialogue": "private conversation", "image_profile": "C:/Users/SensitivePerson/file.png", "api_key": "private key", "widget_scale": "SensitivePerson"})
        self.write_json("ai_settings.json", {"weather_location": "my address", "model": "sk-private", "memory_enabled": True})
        report = backup.diagnostic_report(self.profile, error_categories=("timeout", "C:/Users/SensitivePerson", "private conversation"))
        value = json.dumps(report)
        for secret in ("SensitivePerson", "private conversation", "private key", "my address", "sk-private", "C:/Users/"):
            self.assertNotIn(secret, value)
        self.assertEqual(report["error_categories"], ["timeout"])
        self.assertTrue(report["safe_configuration"]["settings.json"]["always_on_top"])
        for output in ("settings.json", "openai_key.dpapi", "images/diagnostic.json", "backups/../settings.json"):
            with self.subTest(output=output), self.assertRaises(backup.BackupError):
                backup.export_diagnostics(self.profile, self.profile / output)
        with self.assertRaises(backup.BackupError):
            backup.create_backup(self.profile, self.profile / "openai_key.dpapi", ("settings",))
        with self.assertRaises(backup.BackupError):
            backup.create_backup(self.profile, self.profile / "backups/../settings.json", ("settings",))

    def test_diagnostic_error_categories_never_include_log_text(self):
        (self.profile / "kyunghee.log").write_text("2026-01-01 ERROR image failed C:/Users/SecretName/photos/private.png\n2026-01-01 WARNING network timeout token=privatepassword\n", encoding="utf-8")
        report = backup.diagnostic_report(self.profile)
        self.assertEqual(report["error_categories"], ["image", "network", "timeout"])
        encoded = json.dumps(report)
        for secret in ("SecretName", "private.png", "privatepassword", "C:/Users"):
            self.assertNotIn(secret, encoded)


if __name__ == "__main__":
    unittest.main()
