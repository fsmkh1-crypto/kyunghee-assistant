from dataclasses import replace
from pathlib import Path
import json
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from assistant_ai.api import AIError
from assistant_ai.config import SettingsError
from assistant_ai.service import AssistantService, MEMORY_TOOL_NAME


def reply(text="", calls=(), *, status="completed"):
    return SimpleNamespace(text=text, output=list(calls), status=status)


def tool_call(call_id="call_1", arguments='{"action":"resume"}'):
    return {
        "type": "function_call", "call_id": call_id,
        "name": "set_timer_action", "arguments": arguments,
    }


class AssistantServiceTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name)
        vault = patch("assistant_ai.service.KeyVault")
        self.vault = vault.start().return_value
        self.addCleanup(vault.stop)
        self.vault.get.return_value = "test-key"
        client = patch("assistant_ai.service.ResponsesClient")
        self.api = client.start().return_value
        self.addCleanup(client.stop)
        self.service = AssistantService(self.path)
        self.settings = replace(self.service.load_settings(), enabled=True)
        self.service.save_settings(self.settings)
        self.dispatch = Mock(return_value={"ok": True, "changed": True, "message": "복귀했어요."})

    def ask(self, text, cancel=None):
        return self.service.chat(
            text, context={"work_mode": "normal"}, dispatch=self.dispatch,
            cancel=cancel or threading.Event(),
        )

    def test_chat_has_session_context_without_writing_history(self):
        self.api.respond.side_effect = [reply("알겠어요."), reply("네, 세종이에요.")]
        self.ask("회의 장소는 세종이에요.")
        self.assertEqual(self.ask("어디라고 했지?"), "네, 세종이에요.")
        args, kwargs = self.api.respond.call_args
        self.assertEqual([item["role"] for item in args[1]], ["user", "assistant", "user"])
        self.assertIn("세종", args[1][0]["content"])
        self.assertIn("승아", kwargs["instructions"])
        self.assertIn('"work_mode": "normal"', kwargs["instructions"])
        self.assertEqual(len(self.service.recent_turns()), 2)
        self.assertEqual(self.service.memory.recent_turns(), [])
        self.assertEqual(AssistantService(self.path).recent_turns(), [])

    def test_opt_in_history_and_explicit_memory_survive_restart(self):
        self.service.save_settings(replace(self.settings, memory_enabled=True))
        self.service.memory.add_memory("휴식할 때 물부터 마시기")
        self.api.respond.return_value = reply("물을 마셔요.")
        self.ask("휴식 때 뭘 먼저 할까요?")
        self.assertIn("물부터", self.api.respond.call_args.kwargs["instructions"])
        restarted = AssistantService(self.path)
        self.assertEqual(restarted.recent_turns()[0].assistant, "물을 마셔요.")
        restarted.clear_memories()
        restarted.clear_history()
        self.assertEqual(self.service.recent_turns(), [])
        self.assertEqual(self.service.memory.list_memories(), [])

    def test_tool_round_trip_replays_required_provider_items_and_runs_once(self):
        reasoning = {"type": "reasoning", "encrypted_content": "provider-token", "id": "rs_1"}
        self.api.respond.side_effect = [
            reply(calls=[reasoning, tool_call()]), reply(calls=[tool_call()]), reply("이제 복귀했어요."),
        ]
        self.assertEqual(self.ask("다시 시작해 줘"), "이제 복귀했어요.")
        self.dispatch.assert_called_once()
        self.assertEqual(self.dispatch.call_args.args[:2], ("set_timer_action", {"action": "resume"}))
        continuation = self.api.respond.call_args.args[1]
        self.assertIn(reasoning, continuation)
        outputs = [item for item in continuation if item.get("type") == "function_call_output"]
        self.assertEqual(outputs[0]["call_id"], "call_1")
        self.assertTrue(json.loads(outputs[0]["output"])["changed"])

    def test_invalid_tool_arguments_are_never_executed(self):
        self.api.respond.side_effect = [reply(calls=[tool_call(arguments="[]")]), reply("확인해 주세요.")]
        self.ask("복귀할래")
        self.dispatch.assert_not_called()
        self.assertFalse(json.loads(self.api.respond.call_args.args[1][-1]["output"])["ok"])

    def test_memory_write_tool_is_only_available_with_durable_memory_enabled(self):
        call = tool_call(arguments='{"text":"물 마시기"}')
        call["name"] = MEMORY_TOOL_NAME
        self.api.respond.side_effect = [reply(calls=[call]), reply("확인해 주세요.")]
        self.ask("물 마시기를 기억해 줘")
        self.dispatch.assert_not_called()
        self.assertFalse(self.service.save_assistant_memory("물 마시기")["ok"])
        self.service.save_settings(replace(self.settings, memory_enabled=True))
        self.assertTrue(self.service.save_assistant_memory("물 마시기")["ok"])
        self.assertEqual(self.service.memory.list_memories()[0].text, "물 마시기")

    def test_settings_validation_precedes_any_key_change(self):
        with self.assertRaises(SettingsError):
            self.service.save_settings(replace(self.settings, model=" "), remove_key=True)
        self.vault.delete.assert_not_called()
        self.assertTrue(self.service.ready())

    def test_damaged_saved_key_can_be_replaced_in_settings(self):
        self.vault.get.side_effect = SettingsError("저장된 키를 열 수 없어요.")
        service = AssistantService(self.path)
        self.assertFalse(service.ready())
        self.assertIn("키", service.settings_issue)
        service.save_settings(self.settings, new_key="test-replacement")
        self.assertTrue(service.ready())
        self.assertEqual(service.settings_issue, "")

    def test_applied_action_is_reported_when_followup_fails(self):
        self.api.respond.side_effect = [reply(calls=[tool_call()]), AIError("offline", "연결을 확인해 주세요.")]
        answer = self.ask("다시 시작해 줘")
        self.assertIn("복귀했어요.", answer)
        self.assertIn("연결을 확인해 주세요.", answer)
        self.assertEqual(self.service.recent_turns()[0].assistant, answer)
        self.dispatch.assert_called_once()

    def test_incomplete_response_shows_partial_text_without_executing_tools(self):
        self.api.respond.return_value = reply("분석의 첫 문단이에요.", [tool_call()], status="incomplete")
        answer = self.ask("자세히 분석해 줘")
        self.assertIn("분석의 첫 문단", answer)
        self.assertIn("중간에 끝났어요", answer)
        self.dispatch.assert_not_called()

    def test_cleared_history_cancels_in_flight_reply_and_tool(self):
        def respond(*args, **kwargs):
            self.service.clear_history()
            return reply(calls=[tool_call()])

        self.api.respond.side_effect = respond
        with self.assertRaises(AIError) as raised:
            self.ask("다시 시작해 줘")
        self.assertEqual(raised.exception.code, "cancelled")
        self.dispatch.assert_not_called()
        self.assertEqual(self.service.recent_turns(), [])

    def test_proactive_opt_in_silence_context_and_no_actions(self):
        cancel = threading.Event()
        self.assertIsNone(self.service.proactive("break", context={}, cancel=cancel))
        self.api.respond.assert_not_called()
        self.api.respond.return_value = reply("조금 쉬고 갈까요?")
        self.ask("회의를 막 끝냈어요")
        self.service.save_settings(replace(self.settings, proactive_enabled=True))
        self.api.respond.return_value = reply("SILENT")
        self.assertIsNone(self.service.proactive("break", context={"away": False}, cancel=cancel))
        args, kwargs = self.api.respond.call_args
        self.assertNotIn("tools", kwargs)
        self.assertIn("회의", args[1][0]["content"])
        self.assertIn('"away": false', kwargs["instructions"])
        self.assertEqual(len(self.service.recent_turns()), 1)


if __name__ == "__main__":
    unittest.main()
