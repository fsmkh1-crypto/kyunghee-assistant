"""Regression checks for the read-only, tool-free chat transport."""
import dataclasses
import inspect
import json
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import ai_dialogue
from ai_dialogue import AIResult, AIService, HTTPClient, MAX_RESPONSE_BYTES, sanitize_context


def text_response(text="안녕. 오늘 기분은 어때?"):
    return json.dumps({"status": "completed", "output": [
        {"type": "reasoning", "summary": []},
        {"type": "message", "content": [{"type": "output_text", "text": text}]},
    ]}, ensure_ascii=False).encode()


class PlainChatHTTPTests(unittest.TestCase):
    def test_every_request_is_one_read_only_post_without_tools_or_catalog(self):
        for text in ("안녕", "세트 02로 바꿔줘", "응원 이미지를 보여줘", "설치된 이미지 목록", "지금 몇 시야?"):
            with self.subTest(text=text):
                remote = Mock(status=200)
                remote.read.return_value = text_response()
                connection = Mock()
                connection.getresponse.return_value = remote
                with patch("ai_dialogue.http.client.HTTPSConnection", return_value=connection) as create:
                    reply = HTTPClient().generate("test-key", instructions="짧게 답해", messages=[
                        {"role": "user", "content": text},
                    ])
                body = json.loads(connection.request.call_args.kwargs["body"])
                self.assertEqual(body["tool_choice"], "none")
                self.assertIs(body["store"], False)
                for field in ("tools", "parallel_tool_calls", "assets", "asset_catalog"):
                    self.assertNotIn(field, body)
                self.assertEqual(reply.text, "안녕. 오늘 기분은 어때?")
                self.assertEqual(reply.error_code, "")
                create.assert_called_once()
                connection.request.assert_called_once()
                remote.read.assert_called_once_with(MAX_RESPONSE_BYTES + 1)
                connection.close.assert_called_once()

    def test_unsolicited_functions_and_other_tool_outputs_are_rejected_even_with_text(self):
        for kind in ("function_call", "function_call_output", "computer_call", "code_interpreter_call"):
            for name in ("select_asset_set", "get_timer_status", "read_api_key"):
                with self.subTest(kind=kind, name=name):
                    data = json.loads(text_response("설정을 바꿨어."))
                    data["output"].append({"type": kind, "name": name, "call_id": "call_unasked",
                                           "arguments": '{"number":2}'})
                    reply = HTTPClient._parse(json.dumps(data).encode())
                    self.assertEqual(reply.error_code, "invalid_response")
                    self.assertEqual(reply.text, "")

    def test_action_transport_contract_has_been_removed(self):
        self.assertNotIn("asset_catalog", inspect.signature(HTTPClient.generate).parameters)
        self.assertNotIn("asset_catalog", inspect.signature(AIService.request).parameters)
        self.assertFalse(hasattr(AIService, "record_tool_result"))
        self.assertFalse(hasattr(ai_dialogue, "AssetToolCall"))
        self.assertEqual({field.name for field in dataclasses.fields(AIResult)},
                         {"text", "event", "token", "generation", "error_code"})


class PlainChatServiceTests(unittest.TestCase):
    @staticmethod
    def close_service(service):
        service.close()
        if service._worker is not None:
            service._worker.join(timeout=0.5)

    def service(self, client):
        self.now = 100.0
        service = AIService(client, clock=lambda: self.now, today=lambda: "2026-11-06", chat_cooldown_seconds=0)
        self.addCleanup(self.close_service, service)
        service.configure(True, "test-key")
        return service

    def drain(self, service):
        results = []
        deadline = time.monotonic() + 1
        while service._in_flight is not None and time.monotonic() < deadline:
            results.extend(service.poll())
            if service._in_flight is not None:
                time.sleep(0.001)
        self.assertIsNone(service._in_flight)
        return results

    def test_read_only_seconds_context_preserves_short_sessions_and_rejects_invalid_values(self):
        context = {"active_seconds": 13.9, "continuous_seconds": 13, "away_seconds": 2,
                   "app_elapsed_seconds": 90, "active_minutes": 0}
        self.assertEqual(sanitize_context(context), {
            "active_seconds": 13, "continuous_seconds": 13, "away_seconds": 2,
            "app_elapsed_seconds": 90, "active_minutes": 0,
        })
        for field, maximum in (("active_seconds", 86400), ("continuous_seconds", 86400),
                               ("away_seconds", 86400), ("app_elapsed_seconds", 366 * 86400)):
            for value in (True, -1, float("nan"), float("inf"), maximum + 1, "13", 10 ** 1000):
                with self.subTest(field=field, value_type=type(value).__name__):
                    self.assertEqual(sanitize_context({field: value}), {})

    def test_catalog_actions_and_private_objects_never_enter_api_context(self):
        class Private:
            def __str__(self):
                raise AssertionError("must not stringify private context")

        client = SimpleNamespace(generate=Mock(return_value=SimpleNamespace(text="설정 화면에서 직접 골라줘.", error_code="")))
        service = self.service(client)
        self.assertTrue(service.request("chat", {
            "active_seconds": 13, "continuous_seconds": 13, "away_seconds": 0,
            "asset_catalog": Private(), "assets": Private(), "action_result": Private(),
            "settings": Private(), "path": Private(), "api_key": "sk-private123456",
        }, "세트 02로 바꿔줘"))
        self.assertEqual(self.drain(service)[0].text, "설정 화면에서 직접 골라줘.")
        kwargs = client.generate.call_args.kwargs
        self.assertEqual(set(kwargs), {"instructions", "messages"})
        payload = json.loads(kwargs["messages"][0]["content"])
        self.assertEqual(payload["timer"], {"active_seconds": 13, "continuous_seconds": 13,
                                             "away_seconds": 0, "day": "2026-11-06"})
        serialized = json.dumps(payload)
        for private in ("asset_catalog", "action_result", "settings", "api_key", "sk-private", "path"):
            self.assertNotIn(private, serialized)
        self.assertIn("읽기 전용", kwargs["instructions"])
        self.assertIn("설정 화면에서 직접 선택", kwargs["instructions"])
        self.assertNotIn("get_timer_status", kwargs["instructions"])

    def test_actual_api_text_keeps_multiturn_memory_without_capability_metadata(self):
        texts = ["안녕. 오늘 기분은 어때?", "피곤했구나. 잠깐 쉬어도 괜찮아."]
        connections = []
        for text in texts:
            remote = Mock(status=200)
            remote.read.return_value = text_response(text)
            connection = Mock()
            connection.getresponse.return_value = remote
            connections.append(connection)
        service = self.service(HTTPClient())
        with patch("ai_dialogue.http.client.HTTPSConnection", side_effect=connections) as create:
            for utterance, answer in zip(("안녕", "오늘 좀 피곤해"), texts):
                self.assertTrue(service.request("chat", {"active_seconds": 13}, utterance))
                self.assertEqual(self.drain(service)[0].text, answer)
            self.assertEqual(create.call_count, 2)
        bodies = [json.loads(connection.request.call_args.kwargs["body"]) for connection in connections]
        for body in bodies:
            self.assertEqual(body["tool_choice"], "none")
            self.assertNotIn("tools", body)
            payload = json.loads(body["input"][0]["content"])
            self.assertEqual(payload["timer"]["active_seconds"], 13)
            self.assertNotIn("assets", payload)
        self.assertIn(texts[0], json.dumps(bodies[1]["input"], ensure_ascii=False))
        self.assertEqual(len(service._chat), 2)

    def test_stale_read_only_reply_never_enters_memory(self):
        started = threading.Event()
        release = threading.Event()

        def generate(_key, **_kwargs):
            started.set()
            if not release.wait(1):
                raise AssertionError("worker not released")
            return SimpleNamespace(text="잠깐 쉬어가자.", error_code="")

        service = self.service(SimpleNamespace(generate=generate))
        self.assertTrue(service.request("chat", {"active_seconds": 13}, "오늘 좀 피곤해", token="current"))
        self.assertTrue(started.wait(0.5))
        self.now += 5
        release.set()
        self.assertEqual(self.drain(service), [])
        self.assertEqual(len(service._chat), 0)
        self.assertEqual(len(service._recent_ai), 0)


if __name__ == "__main__":
    unittest.main()
