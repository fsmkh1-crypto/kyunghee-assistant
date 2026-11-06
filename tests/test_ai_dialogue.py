import json
import socket
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from ai_dialogue import (
    AIService, API_HOST, API_PATH, HTTPClient, HTTP_TIMEOUT_SECONDS,
    MAX_RESPONSE_BYTES, MODEL, error_message, sanitize_context,
)


def response_body(text="잠깐 어깨를 펴고 쉬어가자.", **changes):
    result = {
        "status": "completed",
        "output": [
            {"type": "reasoning", "summary": []},
            {"type": "message", "content": [{"type": "output_text", "text": text}]},
        ],
    }
    result.update(changes)
    return json.dumps(result, ensure_ascii=False).encode("utf-8")


class HTTPClientTests(unittest.TestCase):
    def make_connection(self, status=200, body=None):
        response = Mock(status=status)
        response.read.return_value = response_body() if body is None else body
        connection = Mock()
        connection.getresponse.return_value = response
        return connection, response

    def test_fixed_https_request_is_private_bounded_and_parses_message_after_reasoning(self):
        connection, response = self.make_connection()
        with patch("ai_dialogue.http.client.HTTPSConnection", return_value=connection) as create:
            result = HTTPClient().test_connection("sk-test-PRIVATE-value")
        self.assertTrue(result.ok)
        self.assertEqual(result.error_code, "")
        create.assert_called_once_with(API_HOST, timeout=HTTP_TIMEOUT_SECONDS)
        args, kwargs = connection.request.call_args
        self.assertEqual(args, ("POST", API_PATH))
        request = json.loads(kwargs["body"])
        self.assertEqual(request["model"], MODEL)
        self.assertIs(request["store"], False)
        self.assertEqual(request["reasoning"], {"effort": "none"})
        self.assertEqual(request["max_output_tokens"], 180)
        self.assertNotIn("sk-test-PRIVATE-value", kwargs["body"].decode())
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer sk-test-PRIVATE-value")
        response.read.assert_called_once_with(MAX_RESPONSE_BYTES + 1)
        connection.close.assert_called_once()

    def test_http_failures_use_fixed_codes_without_reading_remote_error_body_or_retrying(self):
        for status, expected in [(400, "request_error"), (401, "invalid_key"),
                                 (403, "permission_denied"), (429, "rate_limited"),
                                 (500, "service_error"), (302, "request_error")]:
            with self.subTest(status=status):
                connection, response = self.make_connection(status, b"sk-secret error body")
                with patch("ai_dialogue.http.client.HTTPSConnection", return_value=connection) as create:
                    result = HTTPClient().test_connection("key")
                self.assertFalse(result.ok)
                self.assertEqual(result.error_code, expected)
                self.assertNotIn("secret", repr(result))
                self.assertNotIn("secret", error_message(result.error_code))
                response.read.assert_not_called()
                create.assert_called_once()
                connection.request.assert_called_once()
                connection.close.assert_called_once()

    def test_transport_errors_never_surface_exception_text(self):
        for exception, expected in [(socket.timeout("sk-secret timeout"), "timeout"),
                                    (OSError("sk-secret endpoint"), "connection_error"),
                                    (ValueError("sk-secret header"), "request_error")]:
            with self.subTest(error=type(exception).__name__):
                connection, _ = self.make_connection()
                connection.request.side_effect = exception
                with patch("ai_dialogue.http.client.HTTPSConnection", return_value=connection):
                    result = HTTPClient().test_connection("key")
                self.assertEqual(result.error_code, expected)
                self.assertNotIn("secret", repr(result))
                self.assertNotIn("secret", error_message(result.error_code))
                connection.close.assert_called_once()

    def test_missing_or_invalid_key_never_connects(self):
        with patch("ai_dialogue.http.client.HTTPSConnection") as create:
            for key in ("", "  ", "key\r\nInjected: header", "비밀키", "k" * 513):
                self.assertEqual(HTTPClient().test_connection(key).error_code, "invalid_key")
        create.assert_not_called()

    def test_unusable_responses_fall_back(self):
        invalid = [b"not JSON", b"[]", response_body(status="incomplete"),
                   response_body(error={"message": "sk-secret"}),
                   response_body(output=[]), response_body(text=""),
                   response_body(output=[{"type": "message", "content": [{"type": "refusal", "refusal": "no"}]}]),
                   response_body(output=[{"type": "message", "content": "wrong"}]),
                   response_body(text="긴" * 281), b"x" * (MAX_RESPONSE_BYTES + 1)]
        for body in invalid:
            with self.subTest(body_length=len(body)):
                connection, _ = self.make_connection(body=body)
                with patch("ai_dialogue.http.client.HTTPSConnection", return_value=connection):
                    result = HTTPClient().test_connection("key")
                self.assertFalse(result.ok)
                self.assertEqual(result.error_code, "invalid_response")

    def test_parser_collects_all_text_parts_and_caps_sentences(self):
        body = response_body(output=[
            {"type": "reasoning"},
            {"type": "message", "content": [{"type": "output_text", "text": "잘 왔어."}]},
            {"type": "message", "content": [{"type": "output_text", "text": "이제 쉬자. 다음은 나중에."}]},
        ])
        self.assertEqual(HTTPClient._parse(body).text, "잘 왔어. 이제 쉬자.")
        self.assertEqual(HTTPClient._parse(response_body(text="잘 왔어.이제 쉬자.다음은 나중에.")).text,
                         "잘 왔어. 이제 쉬자.")


class FakeClock:
    def __init__(self):
        self.value = 100.0

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


class FakeClient:
    def __init__(self, block=False, replies=None):
        self.calls = []
        self.started = threading.Event()
        self.release = threading.Event()
        if not block:
            self.release.set()
        self.replies = replies

    def generate(self, api_key, *, instructions, messages):
        self.calls.append({"key": api_key, "instructions": instructions, "messages": messages})
        self.started.set()
        if not self.release.wait(2):
            raise RuntimeError("test did not release worker")
        if self.replies is not None:
            reply = self.replies.pop(0)
            if isinstance(reply, Exception):
                raise reply
            return reply
        return SimpleNamespace(text=f"오늘 응원 {len(self.calls)}번째야.", error_code="")


class AIServiceTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.day = "2026-11-06"
        self.services = []

    def tearDown(self):
        for service in self.services:
            service.close()
            if isinstance(service._client, FakeClient):
                service._client.release.set()
            if service._worker is not None:
                service._worker.join(timeout=0.2)

    def service(self, client=None, **kwargs):
        service = AIService(client or FakeClient(), clock=self.clock, today=lambda: self.day, **kwargs)
        self.services.append(service)
        return service

    def drain(self, service, **kwargs):
        results = []
        deadline = time.monotonic() + 1
        while service._in_flight is not None and time.monotonic() < deadline:
            results.extend(service.poll(**kwargs))
            if service._in_flight is not None:
                time.sleep(0.001)
        self.assertIsNone(service._in_flight, "worker did not finish in test")
        return results

    def test_disabled_invalid_events_and_empty_chat_never_start_network_or_worker(self):
        service = self.service()
        self.assertFalse(service.request("break", {}))
        service.configure(True, "")
        self.assertFalse(service.request("break", {}))
        service.configure(True, "key")
        for event in ("tick", "click", "heartbeat", "", "settings"):
            self.assertFalse(service.request(event, {}))
        for text in ("", "  ", "...", "!!!"):
            self.assertFalse(service.request("chat", {}, text))
        self.assertEqual(service._client.calls, [])
        self.assertIsNone(service._worker)

    def test_context_is_strictly_allowlisted_typed_and_bounded(self):
        class PrivateObject:
            def __str__(self):
                raise AssertionError("must not stringify private context")
        context = {
            "day": self.day, "local_time": "18:04", "personality": "warm", "status": "active",
            "active_minutes": 74.8, "away_count": 3, "recent_break_minutes": 5,
            "recent_away_minutes": 12, "seconds_since_return": 60,
            "continuous_minutes": float("nan"), "away_minutes": -1,
            "settings": {"api_key": "sk-secret", "path": "C:\\private\\state.json"},
            "api_key": "sk-secret", "window_title": "private document", "path": PrivateObject(),
        }
        service = self.service()
        service.configure(True, "actual-key")
        self.assertTrue(service.request("break", context))
        self.drain(service)
        outgoing = json.loads(service._client.calls[0]["messages"][0]["content"])["timer"]
        self.assertEqual(outgoing["active_minutes"], 74)
        self.assertEqual(outgoing["recent_away_minutes"], 12)
        self.assertEqual(outgoing["local_time"], "18:04")
        self.assertNotIn("continuous_minutes", outgoing)
        self.assertNotIn("away_minutes", outgoing)
        serialized = json.dumps(service._client.calls[0]["messages"])
        for secret in ("sk-secret", "private", "window_title", "api_key", "settings"):
            self.assertNotIn(secret, serialized)
        self.assertEqual(sanitize_context({"status": PrivateObject(), "local_time": "99:99",
                                           "day": "2026-02-30", "away_count": True,
                                           "active_minutes": 10 ** 1000}), {})

    def test_chat_redacts_secrets_and_local_or_custom_lines_are_never_transmitted(self):
        service = self.service()
        service.configure(True, "key")
        service.note_local("내 개인 병원 예약은 내일이야")
        self.assertTrue(service.request("chat", {}, "sk-abcdefghijklmnop /Users/user/file.txt a@example.com 알려줘"))
        self.drain(service)
        outgoing = json.dumps(service._client.calls[0]["messages"], ensure_ascii=False)
        for secret in ("sk-abcdefghijklmnop", "private", "/Users", "example.com"):
            self.assertNotIn(secret, outgoing)
        self.assertNotIn("개인 병원", outgoing)
        self.assertIn("[비공개]", outgoing)
        self.assertIn("[경로]", outgoing)

    def test_request_is_nonblocking_and_only_one_daemon_worker_can_be_in_flight(self):
        client = FakeClient(block=True)
        service = self.service(client)
        service.configure(True, "key")
        self.assertTrue(service.request("break", {}, token="screen1"))
        self.assertTrue(client.started.wait(0.5))
        self.assertTrue(service._worker.daemon)
        self.assertEqual(service.poll(), [])
        self.assertFalse(service.request("chat", {}, "안녕", token="screen2"))
        self.assertEqual(len(client.calls), 1)
        client.release.set()
        result = self.drain(service)[0]
        self.assertTrue(result.text)
        self.assertEqual(result.token, "screen1")

    def test_invalidated_disabled_or_context_changed_reply_is_never_shown(self):
        for change in ("invalidate", "disable", "token", "day", "close"):
            with self.subTest(change=change):
                client = FakeClient(block=True)
                service = self.service(client)
                service.configure(True, "key")
                self.assertTrue(service.request("chat", {}, "오늘 좀 피곤해", token="old"))
                self.assertTrue(client.started.wait(0.5))
                if change == "invalidate":
                    service.invalidate()
                elif change == "disable":
                    service.configure(False, "key")
                elif change == "day":
                    self.day = "2026-11-07"
                elif change == "close":
                    service.close()
                client.release.set()
                kwargs = {"token": "new"} if change == "token" else {}
                self.assertEqual(self.drain(service, **kwargs), [])
                self.assertEqual(len(service._chat), 0)
                self.day = "2026-11-06"

    def test_late_reply_is_ignored_and_does_not_enter_memory(self):
        client = FakeClient(block=True)
        service = self.service(client)
        service.configure(True, "key")
        self.assertTrue(service.request("chat", {}, "잠깐 쉬어도 될까"))
        self.assertTrue(client.started.wait(0.5))
        self.clock.advance(5.01)
        client.release.set()
        self.assertEqual(self.drain(service), [])
        self.assertEqual(len(service._chat), 0)
        self.assertEqual(len(service._recent), 0)

    def test_recent_local_or_ai_line_is_suppressed_even_with_punctuation_changes(self):
        for line in ("잠깐 어깨를 펴고 쉬어가자.", "잠깐 어깨를 펴고 쉬어가자!"):
            with self.subTest(line=line):
                client = FakeClient(replies=[SimpleNamespace(text=line, error_code="")])
                service = self.service(client)
                service.configure(True, "key")
                service.note_local("잠깐 어깨를 펴고 쉬어가자.")
                self.assertTrue(service.request("break", {}))
                result = self.drain(service)[0]
                self.assertEqual(result.text, "")
                self.assertEqual(result.error_code, "repeated_response")

    def test_event_and_chat_cooldowns_are_separate_and_no_automatic_requests_happen(self):
        service = self.service()
        service.configure(True, "key")
        self.assertTrue(service.request("break", {}))
        self.drain(service)
        self.assertFalse(service.request("return", {}))
        self.assertTrue(service.request("chat", {}, "안녕"))
        self.drain(service)
        self.assertFalse(service.request("chat", {}, "다시 안녕"))
        self.clock.advance(3)
        self.assertTrue(service.request("chat", {}, "다음 대화"))
        self.drain(service)
        self.clock.advance(57)
        self.assertTrue(service.request("leave", {}))
        self.drain(service)
        count = len(service._client.calls)
        self.clock.advance(1000)
        self.assertEqual(service.poll(), [])
        self.assertEqual(len(service._client.calls), count)

    def test_memory_keeps_six_chat_turns_bounded_recent_lines_and_only_current_day(self):
        service = self.service()
        service.configure(True, "key")
        for index in range(9):
            self.assertTrue(service.request("chat", {}, f"발화 {index}"))
            self.drain(service)
            self.clock.advance(4)
        self.assertEqual(len(service._chat), 6)
        self.assertEqual(len(service._recent), 8)
        last_messages = service._client.calls[-1]["messages"]
        self.assertLessEqual(len(last_messages), 14)
        self.assertNotIn("발화 0", json.dumps(last_messages, ensure_ascii=False))
        for _ in range(14):
            self.clock.advance(61)
            self.assertTrue(service.request("return", {}))
            self.drain(service)
        self.assertLessEqual(len(service._events), 12)
        self.day = "2026-11-07"
        self.assertTrue(service.request("chat", {}, "새 날"))
        self.drain(service)
        messages = service._client.calls[-1]["messages"]
        self.assertEqual(len(messages), 2)
        today = json.loads(messages[0]["content"])
        self.assertEqual(today["today_events"], [])
        self.assertEqual(today["recent_ai_lines"], [])
        self.assertFalse(service.request("break", {"day": "2026-11-06"}))

    def test_each_personality_has_distinct_instructions_and_leave_safety(self):
        instructions = []
        for personality in ("balanced", "warm", "playful", "strict"):
            service = self.service()
            service.configure(True, "key")
            self.assertTrue(service.request("leave", {"personality": personality, "workday_stage": "leave"}))
            self.drain(service)
            prompt = service._client.calls[0]["instructions"]
            self.assertIn("한국어 비서 승아입니다.", prompt)
            self.assertNotIn("경희", prompt)
            self.assertIn("퇴근", prompt)
            self.assertIn("1~2문장", prompt)
            instructions.append(prompt)
        self.assertEqual(len(set(instructions)), 4)

    def test_worker_errors_are_safe_and_next_request_still_works(self):
        client = FakeClient(replies=[RuntimeError("sk-secret path"),
                                     SimpleNamespace(text="다음 대화는 괜찮아.", error_code="")])
        service = self.service(client)
        service.configure(True, "key")
        self.assertTrue(service.request("chat", {}, "안녕"))
        result = self.drain(service)[0]
        self.assertEqual(result.error_code, "request_error")
        self.assertEqual(result.text, "")
        self.assertNotIn("secret", repr(result))
        self.clock.advance(4)
        self.assertTrue(service.request("chat", {}, "괜찮아"))
        self.assertEqual(self.drain(service)[0].text, "다음 대화는 괜찮아.")

    def test_closed_service_clears_job_key_exits_worker_and_cannot_keep_new_key(self):
        client = FakeClient(block=True)
        service = self.service(client)
        service.configure(True, "old-key")
        self.assertTrue(service.request("break", {}))
        self.assertTrue(client.started.wait(0.5))
        job = service._in_flight
        service.close()
        self.assertEqual(job.api_key, "")
        client.release.set()
        service._worker.join(timeout=0.5)
        self.assertFalse(service._worker.is_alive())
        service.configure(True, "new-key")
        self.assertEqual(service._api_key, "")
        self.assertFalse(service.request("break", {}))

    def test_completed_job_releases_key_and_cooldown_events_stay_in_day_memory(self):
        service = self.service()
        service.configure(True, "key")
        self.assertTrue(service.request("break", {}))
        job = service._in_flight
        self.drain(service)
        self.assertEqual(job.api_key, "")
        self.assertFalse(service.request("return", {}))
        self.assertIn("return", service._events)


if __name__ == "__main__":
    unittest.main()
