"""Read-only timer recognition/formatting tests; no real clocks or API calls."""
from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
import unittest
from unittest.mock import patch

from timer_status import (
    TimerSnapshot, classify_timer_query, format_duration, format_timer_status,
    is_timer_status_query, is_timer_status_request,
)


def snapshot(**changes):
    values = dict(current_time=datetime(2026, 11, 6, 14, 5, 9), active_seconds=3661,
                  continuous_seconds=59, away_seconds=125, runtime_seconds=20, is_away=False)
    values.update(changes)
    return TimerSnapshot(**values)


class NaturalTimerQueryTests(unittest.TestCase):
    def test_requested_natural_korean_queries_recognize_actual_counter_scope(self):
        examples = {
            "타이머 얼마나 돌아갔어": "all", "몇 분째야": "all",
            "나 얼마나 썼어": "active", "연속 얼마나 했어": "continuous",
            "오늘 사용시간": "active", "얼마나 일했냐": "active",
            "타이머 시간 왜 안늘어": "all", "시간체크해줘": "all",
        }
        for text, kind in examples.items():
            with self.subTest(text=text):
                self.assertEqual(classify_timer_query(text), kind)
                self.assertTrue(is_timer_status_query(text))
                self.assertTrue(is_timer_status_request(text))

    def test_clock_runtime_active_continuous_and_away_natural_variants(self):
        examples = {
            "지금 몇 시야?": "clock", "현재 시각 좀 알려줘": "clock",
            "현재시간": "clock", "몇 시인지 알려줄래요?": "clock",
            "앱 켠 지 얼마나 됐어?": "runtime", "이번 실행 시간 알려줘": "runtime",
            "프로그램 얼마나 돌아갔냐": "runtime", "앱 실행 경과": "runtime",
            "켜 둔 지 얼마나 됐어": "runtime", "켜둔지얼마나됐어": "runtime",
            "오늘 총 사용시간 알려줘": "active", "오늘 얼마나 썼어?": "active",
            "총 일한 시간": "active", "오늘 총 일한 시간": "active",
            "총 일한 시간이 얼마나 돼?": "active", "나 몇 분 썼어?": "active",
            "연속 사용시간 얼마나 됐어?": "continuous", "연속으로 몇 시간 일했어": "continuous",
            "지금 연속 사용 시간은?": "continuous",
            "자리비움 시간 알려줘": "away", "자리 비운 시간이 얼마야?": "away",
            "휴식시간 얼마야": "away", "얼마나 쉬었어?": "away",
            "쉬는 시간이 얼마나 됐어?": "away", "쉰 시간": "away",
            "타이머 멈춘 거 같아": "all", "시간이 왜 안 늘어?": "all",
            "시간이 얼마나 흘렀어?": "all", "몇 분 지났어?": "all",
            "야 몇 분째야": "all", "혹시 지금 얼마나 했어": "all", "시간 왜 안돌아가": "all",
            "지금 몇 시고 얼마나 일했어?": "all",
        }
        for text, kind in examples.items():
            with self.subTest(text=text):
                self.assertEqual(classify_timer_query(text), kind)

    def test_normal_conversation_schedules_and_time_advice_are_not_counter_queries(self):
        for text in (
            "안녕", "오늘 피곤해", "오늘 기분 어때", "오늘 작업 어때", "휴식 보여줘",
            "3시에 회의있어", "오늘 몇 시에 회의야?", "회의 시간 알려줘", "영화 몇 시야?",
            "시간관리방법알려줘", "쉬는 방법 알려줘", "타이머 만드는 방법 보여줘",
            "시간 여행 영화 추천해줘", "시간표 알려줘", "오늘 시간이 없네",
            "돈 얼마야", "돈 얼마나 썼어", "밥 먹은 지 얼마나 됐어?", "오늘 얼마나 피곤했어?",
            "혹시 밥 먹은 지 얼마나 됐어?", "야 3시에 회의있어", "혹시 시간관리 방법 알려줘",
            "3번 세트로 바꿔", "휴식 이미지로 바꿔", "3분 뒤 알려줘",
        ):
            with self.subTest(text=text):
                self.assertIsNone(classify_timer_query(text))
                self.assertFalse(is_timer_status_query(text))

    def test_refusals_quotes_reminders_and_setting_requests_do_not_trigger_a_query(self):
        for text in (
            "시간 알려주지 마", "시간 안 알려줘도 돼", "'몇 분째야'라고 물어봐",
            "만약 지금 몇 시야", "나중에 사용시간 알려줘", "시간 되면 알려줘",
            "타이머 시간을 3분으로 바꿔", "사용시간 초기화해", "타이머 멈춰",
            "현재 시간 알려줘\0", "시간" * 401, "", None, 3,
        ):
            with self.subTest(text=text):
                self.assertIsNone(classify_timer_query(text))

    def test_spacing_and_fullwidth_digit_normalization_do_not_require_exact_sentences(self):
        for text in ("승아야, 타이머얼마나돌아갔어?", "  몇\t분째야?  ", "시간 좀 체크해 줄래?"):
            with self.subTest(text=text):
                self.assertTrue(is_timer_status_query(text))


class TimerFormattingTests(unittest.TestCase):
    def test_zero_subminute_minute_and_hour_values_always_retain_seconds(self):
        for value, expected in (
            (0, "0초"), (0.9, "0초"), (6, "6초"), (59.99, "59초"),
            (60, "1분 0초"), (61, "1분 1초"), (3600, "1시간 0분 0초"),
            (3661, "1시간 1분 1초"), (86401, "24시간 0분 1초"),
        ):
            with self.subTest(value=value):
                self.assertEqual(format_duration(value), expected)

    def test_app_runtime_and_persisted_daily_active_are_not_conflated(self):
        # A fresh run can be shorter than today's persisted actual-use counter.
        result = format_timer_status(snapshot(), "runtime")
        self.assertIn("이번 앱 실행 경과는 20초", result)
        self.assertIn("오늘 실제 사용은 1시간 1분 1초", result)
        self.assertIn("현재 연속 사용은 59초", result)
        self.assertIn("오늘 누적 자리비움은 2분 5초", result)
        self.assertIn("지금은 사용 중", result)

    def test_general_timer_reply_includes_all_distinct_counters_and_current_clock(self):
        result = format_timer_status(snapshot(), classify_timer_query("타이머 얼마나 돌아갔어"))
        for expected in ("14:05:09", "이번 앱 실행 경과", "오늘 실제 사용", "현재 연속 사용", "오늘 누적 자리비움"):
            self.assertIn(expected, result)

    def test_specific_queries_use_the_requested_counter_and_truthful_state(self):
        self.assertEqual(format_timer_status(snapshot(), "clock"), "지금 시각은 14:05:09이야.")
        self.assertIn("오늘 실제 사용은 1시간 1분 1초", format_timer_status(snapshot(), "active"))
        self.assertIn("현재 연속 사용은 59초", format_timer_status(snapshot(), "continuous"))
        away = format_timer_status(snapshot(is_away=True, continuous_seconds=0), "away")
        self.assertIn("오늘 누적 자리비움은 2분 5초", away)
        self.assertIn("지금은 자리비움 상태", away)

    def test_fresh_snapshots_show_progress_every_second_even_after_an_hour(self):
        first = format_timer_status(snapshot(active_seconds=3661, runtime_seconds=3661), "all")
        second = format_timer_status(snapshot(active_seconds=3667, runtime_seconds=3667), "all")
        self.assertNotEqual(first, second)
        self.assertIn("1시간 1분 1초", first)
        self.assertIn("1시간 1분 7초", second)

    def test_all_zero_counters_still_report_seconds_instead_of_only_zero_minutes(self):
        result = format_timer_status(snapshot(active_seconds=0, continuous_seconds=0,
                                              away_seconds=0, runtime_seconds=0), "all")
        self.assertEqual(result.count("0초"), 4)
        self.assertNotIn("0분", result)

    def test_snapshot_is_immutable_and_formatter_does_not_mutate_or_read_state(self):
        value = snapshot()
        with self.assertRaises(FrozenInstanceError):
            value.active_seconds = 99
        before = value
        with patch("builtins.open", side_effect=AssertionError("unexpected file access")):
            with patch("time.monotonic", side_effect=AssertionError("unexpected clock read")):
                self.assertIn("1시간 1분 1초", format_timer_status(value))
                self.assertEqual(classify_timer_query("오늘 사용시간"), "active")
        self.assertEqual(value, before)

    def test_invalid_counts_are_rejected_instead_of_fabricating_zero(self):
        for value in (True, "3", None, -1, float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                snapshot(active_seconds=value)
            with self.subTest(value=value), self.assertRaises(ValueError):
                format_duration(value)
        with self.assertRaises(ValueError):
            snapshot(current_time="14:05:09")
        with self.assertRaises(ValueError):
            snapshot(is_away=1)
        for kind in ("reset", None, []):
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                format_timer_status(snapshot(), kind)

    def test_formatter_uses_the_supplied_timezone_clock_without_sampling_or_conversion(self):
        value = snapshot(current_time=datetime(2026, 11, 6, 23, 59, 59, tzinfo=timezone.utc))
        self.assertEqual(format_timer_status(value, "clock"), "지금 시각은 23:59:59이야.")


if __name__ == "__main__":
    unittest.main()
