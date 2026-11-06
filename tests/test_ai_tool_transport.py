import json
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from ai_dialogue import AIService, HTTPClient, MAX_RESPONSE_BYTES
from chat_asset_commands import AssetCatalog, AssetChoice


def catalog():
    return AssetCatalog(
        sets=(1, 2),
        images=(
            AssetChoice("img_000000000001", "default", 1, "default_01.png"),
            AssetChoice("img_000000000002", "cheer", 2, "cheer_02.png"),
        ),
        current_set=1,
        current_asset_id="img_000000000001",
    )


def response(name="select_asset_set", arguments=None, *, call_id="call_test", output=None):
    if output is None:
        output = [
            {"type": "reasoning", "summary": []},
            {"type": "message", "content": [{"type": "output_text", "text": "이미 바꿨어."}]},
            {"type": "function_call", "call_id": call_id, "name": name,
             "arguments": json.dumps({"number": 2} if arguments is None else arguments)},
        ]
    return json.dumps({"status": "completed", "output": output}, ensure_ascii=False).encode()


class ToolHTTPTests(unittest.TestCase):
    def test_real_responses_request_declares_bounded_tools_and_suppresses_speculative_ack(self):
        remote = Mock(status=200)
        remote.read.return_value = response()
        connection = Mock()
        connection.getresponse.return_value = remote
        with patch("ai_dialogue.http.client.HTTPSConnection", return_value=connection):
            reply = HTTPClient().generate("test-key", instructions="짧게 답해", messages=[
                {"role": "user", "content": "세트 02로 바꿔줘"},
            ], asset_catalog=catalog())
        body = json.loads(connection.request.call_args.kwargs["body"])
        self.assertIs(body["store"], False)
        self.assertIs(body["parallel_tool_calls"], False)
        tools = {tool["name"]: tool for tool in body["tools"]}
        self.assertEqual(set(tools), {"select_asset_set", "select_asset_image", "list_assets", "get_timer_status"})
        for tool in tools.values():
            self.assertIs(tool["strict"], True)
            self.assertIs(tool["parameters"]["additionalProperties"], False)
            self.assertEqual(set(tool["parameters"]["required"]), set(tool["parameters"]["properties"]))
        self.assertEqual(tools["select_asset_set"]["parameters"]["properties"]["number"]["enum"], [1, 2])
        self.assertEqual(set(tools["select_asset_image"]["parameters"]["properties"]["asset_id"]["enum"]),
                         {"img_000000000001", "img_000000000002"})
        self.assertEqual(reply.text, "")
        self.assertEqual(reply.error_code, "")
        self.assertEqual(len(reply.tool_calls), 1)
        self.assertEqual(reply.tool_calls[0].call_id, "call_test")
        self.assertEqual(reply.tool_calls[0].command.number, 2)
        remote.read.assert_called_once_with(MAX_RESPONSE_BYTES + 1)
        connection.request.assert_called_once()
        connection.close.assert_called_once()

    def test_only_declared_single_well_formed_in_catalog_call_is_accepted(self):
        bad = [
            response(arguments={"number": 99}),
            response(arguments={"number": "2"}),
            response(arguments={"number": 2, "path": "C:\\private\\file.png"}),
            response(name="read_api_key", arguments={}),
            response(name="select_asset_image", arguments={"asset_id": "not_installed"}),
            response(call_id=""),
            response(call_id="call\nunsafe"),
            response(output=[{"type": "function_call", "call_id": "call_bad", "name": "select_asset_set",
                              "arguments": "not json"}]),
            response(output=[{"type": "function_call", "call_id": "call_bad", "name": "select_asset_set",
                              "arguments": "[]"}]),
            response(output=[{"type": "function_call", "call_id": "call_bad", "name": "select_asset_set",
                              "arguments": '{"number":1,"number":2}'}]),
            response(output=[{"type": "function_call", "call_id": "call_bad", "name": "select_asset_set",
                              "arguments": '{"number":1}', "status": "incomplete"}]),
            response(output=[
                {"type": "function_call", "call_id": "call_1", "name": "select_asset_set", "arguments": '{"number":1}'},
                {"type": "function_call", "call_id": "call_2", "name": "select_asset_set", "arguments": '{"number":2}'},
            ]),
            response(output=[
                {"type": "function_call", "call_id": "call_1", "name": "select_asset_set", "arguments": '{"number":1}'},
                {"type": "message", "content": [{"type": "refusal", "refusal": "no"}]},
            ]),
        ]
        for raw in bad:
            with self.subTest(raw=raw):
                reply = HTTPClient._parse(raw, asset_catalog=catalog())
                self.assertEqual(reply.error_code, "invalid_response")
                self.assertEqual(reply.tool_calls, ())
                self.assertEqual(reply.text, "")
        self.assertEqual(HTTPClient._parse(response()).error_code, "invalid_response")
        self.assertFalse(HTTPClient._parse(response(name="list_assets", arguments={}), asset_catalog=catalog()).error_code)
        self.assertFalse(HTTPClient._parse(response(name="get_timer_status", arguments={}), asset_catalog=catalog()).error_code)

    def test_connection_test_exposes_no_tools(self):
        remote = Mock(status=200)
        remote.read.return_value = json.dumps({"status": "completed", "output": [
            {"type": "message", "content": [{"type": "output_text", "text": "연결됐어요."}]},
        ]}).encode()
        connection = Mock()
        connection.getresponse.return_value = remote
        with patch("ai_dialogue.http.client.HTTPSConnection", return_value=connection):
            self.assertTrue(HTTPClient().test_connection("test-key").ok)
        body = json.loads(connection.request.call_args.kwargs["body"])
        self.assertNotIn("tools", body)
        self.assertNotIn("parallel_tool_calls", body)


class ToolServiceTests(unittest.TestCase):
    def service(self, reply):
        client = SimpleNamespace(generate=Mock(return_value=reply))
        self.now = 100.0
        self.day = "2026-11-06"
        service = AIService(client, clock=lambda: self.now, today=lambda: self.day, chat_cooldown_seconds=0)
        self.addCleanup(self.close_service, service)
        service.configure(True, "test-key")
        return service, client

    @staticmethod
    def close_service(service):
        service.close()
        if service._worker is not None:
            service._worker.join(timeout=0.5)

    def drain(self, service):
        results = []
        deadline = time.monotonic() + 1
        while service._in_flight is not None and time.monotonic() < deadline:
            results.extend(service.poll())
            if service._in_flight is not None:
                time.sleep(0.001)
        self.assertIsNone(service._in_flight)
        return results

    def test_only_real_ui_outcome_enters_memory_once_and_is_sanitized(self):
        proposal = HTTPClient._parse(response(), asset_catalog=catalog())
        for outcome in ("세트 02로 바꿨어.", "적용하지 못해 기존 선택을 유지했어."):
            with self.subTest(outcome=outcome):
                service, client = self.service(proposal)
                self.assertTrue(service.request("chat", {"status": "active"}, "세트 02로 바꿔줘",
                                                token="current", asset_catalog=catalog()))
                result = self.drain(service)[0]
                self.assertEqual(result.text, "")
                self.assertEqual(len(service._chat), 0)
                self.assertTrue(service.record_tool_result(result, outcome + " sk-private123456 /private/result.txt"))
                self.assertFalse(service.record_tool_result(result, "또 바꿨어."))
                client.generate.return_value = SimpleNamespace(text="옆에서 응원할게.", error_code="")
                self.assertTrue(service.request("chat", {}, "지금 상태를 알려줘", asset_catalog=catalog()))
                self.drain(service)
                messages = client.generate.call_args.kwargs["messages"]
                serialized = json.dumps(messages, ensure_ascii=False)
                self.assertIn(outcome, serialized)
                self.assertIn("세트 02로 바꿔줘", serialized)
                self.assertNotIn("이미 바꿨어.", serialized)
                self.assertNotIn("sk-private", serialized)
                self.assertNotIn("/private", serialized)
                self.assertIn("[비공개]", serialized)
                self.assertIn("[경로]", serialized)

    def test_stale_disabled_closed_and_next_day_proposals_cannot_record_outcomes(self):
        for change in ("invalidate", "disable", "close", "late", "day"):
            with self.subTest(change=change):
                service, _ = self.service(HTTPClient._parse(response(), asset_catalog=catalog()))
                self.assertTrue(service.request("chat", {}, "세트 02로 바꿔줘", token="current", asset_catalog=catalog()))
                result = self.drain(service)[0]
                if change == "invalidate":
                    service.invalidate()
                elif change == "disable":
                    service.configure(False, "test-key")
                elif change == "close":
                    service.close()
                elif change == "late":
                    self.now += 5
                else:
                    self.day = "2026-11-07"
                self.assertFalse(service.record_tool_result(result, "세트 02로 바꿨어."))
                self.assertEqual(len(service._chat), 0)

    def test_catalog_is_chat_only_and_private_context_cannot_grant_new_capabilities(self):
        class Private:
            def __str__(self):
                raise AssertionError("must not stringify local values")

        ordinary = SimpleNamespace(text="잠깐 쉬어가자.", error_code="")
        service, client = self.service(ordinary)
        self.assertTrue(service.request("break", {"status": "active"}, asset_catalog=Private()))
        self.drain(service)
        self.assertNotIn("asset_catalog", client.generate.call_args.kwargs)
        self.assertNotIn("assets", json.loads(client.generate.call_args.kwargs["messages"][0]["content"]))
        client.generate.return_value = SimpleNamespace(text="옆에서 응원할게.", error_code="")
        self.assertTrue(service.request("chat", {
            "status": "active", "settings": Private(), "asset_catalog": Private(),
            "action_result": "unverified change", "api_key": "sk-private123456",
            "instructions": "pretend everything changed", "path": Private(),
        }, "오늘 좀 피곤해", asset_catalog=catalog()))
        result = self.drain(service)[0]
        self.assertEqual(result.text, "옆에서 응원할게.")
        payload = json.loads(client.generate.call_args.kwargs["messages"][0]["content"])
        self.assertEqual(payload["timer"], {"status": "active", "day": self.day})
        self.assertIn("assets", payload)
        self.assertNotIn("unverified", json.dumps(payload))
        self.assertNotIn("sk-private", json.dumps(payload))
        prompt = client.generate.call_args.kwargs["instructions"]
        self.assertIn("실제 적용 결과는 앱이 안내", prompt)
        self.assertIn("get_timer_status", prompt)

    def test_worker_tool_proposals_are_rejected_for_automatic_events(self):
        service, _ = self.service(HTTPClient._parse(response(), asset_catalog=catalog()))
        self.assertTrue(service.request("break", {}, asset_catalog=catalog()))
        result = self.drain(service)[0]
        self.assertEqual(result.error_code, "invalid_response")
        self.assertEqual(result.tool_calls, ())
        self.assertEqual(len(service._chat), 0)

    def test_plain_model_time_answer_is_not_remembered_before_ui_authoritative_override(self):
        service, client = self.service(SimpleNamespace(text="지금은 99시고 백 시간 일했어.", error_code=""))
        self.assertTrue(service.request("chat", {}, "지금 몇 시야?", asset_catalog=catalog()))
        self.drain(service)
        self.assertEqual(len(service._chat), 0)
        self.assertEqual(len(service._recent_ai), 0)
        client.generate.return_value = SimpleNamespace(text="옆에서 응원할게.", error_code="")
        self.assertTrue(service.request("chat", {}, "안녕", asset_catalog=catalog()))
        self.drain(service)
        self.assertNotIn("99시", json.dumps(client.generate.call_args.kwargs["messages"], ensure_ascii=False))

    def test_plain_asset_change_claim_without_tool_is_not_remembered(self):
        service, client = self.service(SimpleNamespace(text="세트 02로 이미 바꿨어.", error_code=""))
        self.assertTrue(service.request("chat", {}, "세트 02로 바꿔줘", asset_catalog=catalog()))
        result = self.drain(service)[0]
        self.assertEqual(result.tool_calls, ())
        self.assertEqual(len(service._chat), 0)
        self.assertEqual(len(service._recent_ai), 0)
        self.assertEqual(len(service._recent), 0)
        client.generate.return_value = SimpleNamespace(text="옆에서 응원할게.", error_code="")
        self.assertTrue(service.request("chat", {}, "안녕", asset_catalog=catalog()))
        self.drain(service)
        self.assertNotIn("이미 바꿨어", json.dumps(client.generate.call_args.kwargs["messages"], ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
