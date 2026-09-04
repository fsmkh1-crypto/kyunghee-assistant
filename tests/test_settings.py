import json
from pathlib import Path
import tempfile
import unittest

from settings import (
    UserSettings,
    load_user_settings,
    parse_clock,
    save_user_settings,
    settings_from_dict,
)


class UserSettingsTests(unittest.TestCase):
    def test_parse_clock_accepts_valid_time(self):
        parsed = parse_clock("07:05")
        self.assertEqual((parsed.hour, parsed.minute), (7, 5))

    def test_parse_clock_rejects_invalid_time(self):
        for value in ("7", "24:00", "12:60", "ab:cd"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_clock(value)

    def test_workday_times_must_be_ordered(self):
        settings = UserSettings(wind_down="18:00", leave_mode="17:30")
        with self.assertRaises(ValueError):
            settings.workday_policy()

    def test_settings_round_trip(self):
        expected = UserSettings(
            start_with_windows=True,
            always_on_top=True,
            break_reminders=False,
            wind_down="16:45",
            leave_mode="17:15",
            window_x=-1420,
            window_y=80,
            image_default="default.png",
            personality="warm",
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            save_user_settings(path, expected)
            self.assertEqual(load_user_settings(path), expected)

    def test_bad_file_falls_back_to_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            path.write_text("{bad", encoding="utf-8")
            self.assertEqual(load_user_settings(path), UserSettings())

    def test_wrong_types_do_not_turn_strings_into_true(self):
        parsed = settings_from_dict({"always_on_top": "false", "break_reminders": 0})
        self.assertFalse(parsed.always_on_top)
        self.assertTrue(parsed.break_reminders)

    def test_bad_color_only_falls_back_for_that_color(self):
        parsed = settings_from_dict(
            {
                "always_on_top": True,
                "time_text_color": "not-a-color",
                "message_text_color": "#123456",
                "image_default": "default.png",
            }
        )
        self.assertTrue(parsed.always_on_top)
        self.assertEqual(parsed.time_text_color, UserSettings().time_text_color)
        self.assertEqual(parsed.message_text_color, "#123456")
        self.assertEqual(parsed.image_default, "default.png")

    def test_bad_schedule_only_resets_schedule_group(self):
        parsed = settings_from_dict(
            {
                "always_on_top": True,
                "wind_down": "19:00",
                "leave_mode": "17:30",
                "message_text_size": 14,
            }
        )
        defaults = UserSettings()
        self.assertTrue(parsed.always_on_top)
        self.assertEqual(parsed.message_text_size, 14)
        self.assertEqual(parsed.wind_down, defaults.wind_down)
        self.assertEqual(parsed.leave_mode, defaults.leave_mode)

    def test_saved_json_has_schema_version(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            save_user_settings(path, UserSettings())
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["schema_version"], UserSettings().schema_version)

    def test_widget_display_preferences_round_trip(self):
        parsed = settings_from_dict({
            "widget_scale": 125,
            "show_time": False,
            "show_status": True,
            "show_message": False,
        })
        self.assertEqual(parsed.widget_scale, 125)
        self.assertFalse(parsed.show_time)
        self.assertTrue(parsed.show_status)
        self.assertFalse(parsed.show_message)

    def test_bad_widget_scale_falls_back(self):
        parsed = settings_from_dict({"widget_scale": 500})
        self.assertEqual(parsed.widget_scale, UserSettings().widget_scale)

    def test_personality_loads_and_invalid_value_falls_back(self):
        self.assertEqual(settings_from_dict({"personality": "playful"}).personality, "playful")
        self.assertEqual(settings_from_dict({"personality": "unknown"}).personality, "balanced")


if __name__ == "__main__":
    unittest.main()
