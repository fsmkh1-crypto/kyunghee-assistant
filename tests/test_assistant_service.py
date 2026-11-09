from dataclasses import replace
from datetime import datetime
from pathlib import Path
import json
import os
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from assistant_ai.api import AIError, WebSource
from assistant_ai.config import KeyVault, SettingsError
from assistant_ai.service import AssistantService, MEMORY_TOOL_NAME, WEATHER_TOOL_NAME, _lookup_kind
from assistant_ai.weather import WeatherError


def reply(text="", calls=(), *, status="completed", sources=(), searched=False):
    return SimpleNamespace(text=text, output=list(calls), status=status, sources=sources, used_web_search=searched)


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
        self.now = 10_000.0
        clock = patch("assistant_ai.service.time.monotonic", side_effect=lambda: self.now)
        clock.start()
        self.addCleanup(clock.stop)
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
        self.service.save_settings(replace(self.settings, memory_enabled=True, conversation_storage_enabled=True))
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

    def test_web_lookup_requires_provider_sources_and_displays_lookup_time(self):
        source = WebSource(title="정부 발표", url="https://example.com/update", start_index=0, end_index=5, cited=True)
        self.api.respond.side_effect = [reply("확인 결과예요.", sources=[source], searched=True), reply("근거 없는 최신 정보")]
        answer = self.ask("오늘 뉴스 검색해 줘")
        self.assertTrue(self.api.respond.call_args.kwargs["force_web_search"])
        self.assertIn("웹 조회 시각", answer)
        self.assertIn(f"[1](<{source.url}>)", answer)
        missing = self.ask("최신 뉴스 알려줘")
        self.assertIn("출처", missing)
        self.assertNotIn("근거 없는 최신 정보", missing)

    def test_weather_chat_displays_provider_text_and_uses_configured_region(self):
        call = tool_call(arguments='{"region":null}')
        call["name"] = WEATHER_TOOL_NAME
        self.api.respond.return_value = reply("근거 없는 기온", calls=[call])
        self.service.save_settings(replace(self.settings, weather_location="대전"))
        text = "대전 현재 기온 12°C\n조회 시각 2026-11-09\n출처 Open-Meteo"
        report = Mock()
        report.format_text.return_value = text
        report.to_tool_result.return_value = {"region": "대전"}
        self.service._weather.lookup = Mock(return_value=report)
        self.assertEqual(self.ask("오늘 날씨 알려줘"), text)
        self.service._weather.lookup.assert_called_once_with("대전")
        self.api.respond.assert_called_once()
        self.assertEqual(self.api.respond.call_args.kwargs["tool_choice"]["name"], WEATHER_TOOL_NAME)
        self.dispatch.assert_not_called()

    def test_weather_failure_does_not_use_model_text(self):
        call = tool_call(arguments='{"region":"서울"}')
        call["name"] = WEATHER_TOOL_NAME
        self.api.respond.return_value = reply("서울은 맑아요.", calls=[call])
        self.service._weather.lookup = Mock(side_effect=WeatherError("날씨 조회에 실패했어요."))
        self.assertEqual(self.ask("서울 날씨 어때?"), "날씨 조회에 실패했어요.")
        self.service._weather.lookup.assert_called_once_with("서울")

    def test_indirect_weather_tool_failure_stops_unverified_followup(self):
        call = tool_call(arguments='{"region":null}')
        call["name"] = WEATHER_TOOL_NAME
        self.api.respond.side_effect = [reply(calls=[call]), reply("맑을 것 같아요.")]
        self.service._weather.lookup = Mock(side_effect=WeatherError("날씨 조회에 실패했어요."))
        self.assertEqual(self.ask("우산 챙길까요?"), "날씨 조회에 실패했어요.")
        self.api.respond.assert_called_once()

    def test_weather_button_can_use_default_without_openai(self):
        self.service.save_settings(replace(self.settings, enabled=False), remove_key=True)
        report = Mock()
        report.format_text.return_value = "세종시 관측 자료"
        self.service._weather.lookup = Mock(return_value=report)
        self.assertEqual(self.service.weather_report(), "세종시 관측 자료")
        self.service._weather.lookup.assert_called_once_with("세종시")
        self.api.respond.assert_not_called()

    def test_proactive_opt_in_silence_context_and_no_actions(self):
        cancel = threading.Event()
        self.assertIsNone(self.service.proactive("rest", context={}, cancel=cancel))
        self.api.respond.assert_not_called()
        self.api.respond.return_value = reply("조금 쉬고 갈까요?")
        self.ask("회의를 막 끝냈어요")
        self.now += 300
        self.service.save_settings(replace(self.settings, proactive_enabled=True))
        self.api.respond.return_value = reply("SILENT")
        self.assertIsNone(self.service.proactive("rest", context={"away": False}, cancel=cancel))
        args, kwargs = self.api.respond.call_args
        self.assertNotIn("tools", kwargs)
        self.assertIn("회의", args[1][0]["content"])
        self.assertIn('"away": false', kwargs["instructions"])
        self.assertEqual(len(self.service.recent_turns()), 1)

    def test_cancellation_detaches_chat_but_restore_waits_for_network_cleanup(self):
        entered, release = threading.Event(), threading.Event()
        errors = []
        cancel = threading.Event()

        def first_response(*args, **kwargs):
            entered.set()
            self.assertTrue(release.wait(3))
            return reply(calls=[tool_call()])

        count = 0
        def respond(*args, **kwargs):
            nonlocal count
            count += 1
            return first_response() if count == 1 else reply("새 응답")
        self.api.respond.side_effect = respond
        def first_chat():
            try:
                self.ask("옛 요청", cancel)
            except AIError as error:
                errors.append(error.code)
        worker = threading.Thread(target=first_chat)
        worker.start()
        try:
            self.assertTrue(entered.wait(2))
            self.service.cancel_chat(cancel)
            self.assertEqual(self.service.recent_turns()[-1].status, "cancelled")
            self.assertEqual(self.ask("새 요청"), "새 응답")
            self.assertFalse(self.service.is_quiescent())
            self.assertFalse(self.service.try_begin_restore())
        finally:
            release.set()
            worker.join(3)
        self.assertEqual(errors, ["cancelled"])
        self.dispatch.assert_not_called()
        self.assertTrue(self.service.try_begin_restore())
        with self.assertRaises(AIError) as raised:
            self.ask("복원 중 요청")
        self.assertEqual(raised.exception.code, "restoring")
        self.service.end_restore_failure()
        self.assertEqual(self.ask("복원 실패 후 요청"), "새 응답")

    def test_retry_reuses_applied_actions_across_multiple_retries(self):
        self.api.respond.side_effect = [
            reply(calls=[tool_call()]), AIError("offline", "연결 실패"),
            reply(calls=[tool_call("retry_call")]), reply("확인했어요."),
            reply(calls=[tool_call("third_call")]), reply("확인했어요."),
        ]
        for request_id, retry_of in (("one", None), ("two", "one"), ("three", "two")):
            self.service.chat("복귀해 줘", context={}, dispatch=self.dispatch,
                              cancel=threading.Event(), request_id=request_id, retry_of=retry_of)
        self.dispatch.assert_called_once()
        self.assertEqual(len(self.service.action_receipts("three")), 1)

    def test_old_cancelled_worker_cannot_unlock_a_new_active_chat(self):
        entered = [threading.Event(), threading.Event()]
        releases = [threading.Event(), threading.Event()]
        cancels = [threading.Event(), threading.Event()]
        errors = []
        lock = threading.Lock()
        call_count = 0
        def respond(*args, **kwargs):
            nonlocal call_count
            with lock:
                index = call_count
                call_count += 1
            entered[index].set()
            self.assertTrue(releases[index].wait(3))
            return reply("완료")
        def ask(index):
            try:
                self.ask(f"요청 {index}", cancels[index])
            except AIError as error:
                errors.append(error.code)
        self.api.respond.side_effect = respond
        workers = [threading.Thread(target=ask, args=(index,)) for index in range(2)]
        workers[0].start()
        try:
            self.assertTrue(entered[0].wait(2))
            self.service.cancel_chat(cancels[0])
            workers[1].start()
            self.assertTrue(entered[1].wait(2))
            releases[0].set()
            workers[0].join(2)
            with self.assertRaises(AIError) as raised:
                self.ask("세 번째 요청")
            self.assertEqual(raised.exception.code, "busy")
        finally:
            for release in releases:
                release.set()
            for worker in workers:
                if worker.ident is not None:
                    worker.join(3)
        self.assertEqual(errors, ["cancelled"])

    def test_storage_toggle_keeps_session_without_retroactive_disk_copy(self):
        self.api.respond.return_value = reply("답변")
        self.ask("저장 전 임시 대화")
        self.service.save_settings(replace(self.settings, conversation_storage_enabled=True))
        self.assertEqual(len(self.service.recent_turns()), 1)
        self.assertEqual(self.service.memory.recent_turns(), [])
        self.ask("저장 허용한 대화")
        self.service.save_settings(self.settings)
        self.ask("다시 임시 대화")
        self.assertEqual(len(self.service.recent_turns()), 3)
        saved = self.service.memory.recent_turns()
        self.assertEqual([turn.user for turn in saved], ["저장 허용한 대화"])
        self.assertEqual([turn.user for turn in AssistantService(self.path).recent_turns()], ["저장 허용한 대화"])

    def test_failed_saved_turn_has_metadata_and_is_not_replayed_to_the_model(self):
        self.service.save_settings(replace(self.settings, conversation_storage_enabled=True))
        self.api.respond.side_effect = [AIError("offline", "연결 오류"), reply("새 답변")]
        with self.assertRaises(AIError):
            self.ask("실패한 명령")
        failed = self.service.recent_turns()[0]
        self.assertEqual(failed.status, "failed")
        self.assertIsNone(failed.assistant)
        self.assertEqual(self.service.memory.recent_turns()[0].status, "failed")
        self.ask("새 메시지")
        self.assertEqual(self.api.respond.call_args.args[1], [{"role": "user", "content": "새 메시지"}])

    def test_startup_marks_only_unfinished_saved_turns_interrupted(self):
        self.service.save_settings(replace(self.settings, conversation_storage_enabled=True))
        self.service.memory.begin_turn("중단된 질문")
        restarted = AssistantService(self.path)
        turn = restarted.recent_turns()[0]
        self.assertEqual(turn.status, "interrupted")
        self.assertIsNone(turn.assistant)

    def test_reading_size_change_does_not_cancel_request(self):
        cancel = threading.Event()
        self.service._active_chat_cancel = cancel
        revision = self.service.revision
        self.service.save_settings(replace(self.settings, reading_text_size=16))
        self.assertFalse(cancel.is_set())
        self.assertEqual(self.service.revision, revision)

    def test_ai_chatter_toggle_during_chat_cancels_old_reply_but_preserves_event_opt_in(self):
        self.service.save_settings(replace(self.settings, proactive_enabled=True, chatter_enabled=True))
        revision = self.service.revision
        cancel = threading.Event()

        def toggle_ai_chatter(*args, **kwargs):
            self.service.save_settings(replace(self.service.load_settings(), chatter_enabled=False, reading_text_size=16))
            return reply("이전 AI 설정으로 만든 응답이에요.")

        self.api.respond.side_effect = toggle_ai_chatter
        with self.assertRaises(AIError) as error:
            self.ask("대화 중 AI 말 걸기를 끌게요.", cancel)
        self.assertEqual(error.exception.code, "cancelled")
        self.assertTrue(cancel.is_set())
        self.assertIsNone(self.service.recent_turns()[-1].assistant)
        self.assertGreater(self.service.revision, revision)
        self.assertFalse(self.service.load_settings().chatter_enabled)
        self.assertTrue(self.service.load_settings().proactive_enabled)

    def test_ai_chatter_off_during_proactive_discards_old_generated_result(self):
        self.service.save_settings(replace(self.settings, proactive_enabled=False, chatter_enabled=True))
        self.now += 60
        revision = self.service.revision
        cancel = threading.Event()

        def toggle_ai_chatter(*args, **kwargs):
            self.service.save_settings(replace(self.service.load_settings(), chatter_enabled=False))
            return reply("이전 설정으로 만든 자동 대사예요.")

        self.api.respond.side_effect = toggle_ai_chatter
        with self.assertRaises(AIError) as error:
            self.service.proactive("periodic", context={}, cancel=cancel)
        self.assertEqual(error.exception.code, "cancelled")
        self.assertTrue(cancel.is_set())
        self.assertGreater(self.service.revision, revision)
        self.assertFalse(self.service.can_proactively_speak())
        self.assertEqual(self.service.proactive_diagnostics()["last_outcome"], "cancelled")

    def test_ai_opt_in_or_interval_change_still_cancels_when_chatter_changes_too(self):
        for change in ({"proactive_enabled": False}, {"proactive_interval_minutes": 2}):
            with self.subTest(change=change):
                self.service.save_settings(replace(self.settings, proactive_enabled=True))
                cancel = threading.Event()
                revision = self.service.revision

                def change_ai_setting(*args, **kwargs):
                    self.service.save_settings(replace(self.service.load_settings(), chatter_enabled=True, **change))
                    return reply("이전 설정의 응답은 표시하면 안 돼요.")

                self.api.respond.side_effect = change_ai_setting
                with self.assertRaises(AIError) as error:
                    self.service.proactive("rest", context={}, cancel=cancel)
                self.assertEqual(error.exception.code, "cancelled")
                self.assertTrue(cancel.is_set())
                self.assertGreater(self.service.revision, revision)
                self.assertEqual(self.service.proactive_diagnostics()["last_outcome"], "cancelled")
                self.now += 60

    def test_web_switch_removes_tool_and_explicit_search_does_not_spend(self):
        self.service.save_settings(replace(self.settings, web_search_enabled=False))
        self.api.respond.return_value = reply("안녕하세요.")
        self.ask("안녕")
        self.assertFalse(any(tool.get("type") == "web_search" for tool in self.api.respond.call_args.kwargs["tools"]))
        self.api.respond.reset_mock()
        self.assertIn("웹 검색이 꺼져", self.ask("오늘 주요 뉴스 검색해 줘"))
        self.api.respond.assert_not_called()

    def test_past_weather_uses_web_and_compound_weather_continues_actions(self):
        for text in ("어제 날씨", "지난주 서울 기온", "작년 날씨 알려줘", "2020-01-01 서울 날씨", "2020년 1월 1일 날씨"):
            self.assertEqual(_lookup_kind(text), "web")
        weather = tool_call(arguments='{"region":null}')
        weather["name"] = WEATHER_TOOL_NAME
        self.service._weather_tool = Mock(return_value={"ok": True, "message": "확인한 날씨 자료"})
        self.api.respond.side_effect = [reply(calls=[weather]), reply(calls=[tool_call("timer")]), reply("동작을 확인했어요.")]
        answer = self.ask("오늘 날씨 알려주고 휴식 시작해 줘")
        self.assertIn("확인한 날씨 자료", answer)
        self.assertEqual(self.api.respond.call_count, 3)
        self.dispatch.assert_called_once()

    def test_image_proposal_cannot_be_reported_as_already_applied(self):
        call = tool_call(arguments='{"kind":"base_set","role":null,"ref":null,"set_id":"03"}')
        call["name"] = "propose_image_action"
        self.dispatch.return_value = {"ok": True, "changed": False, "status": "pending", "summary": "기본 세트 03 제안"}
        self.api.respond.side_effect = [reply(calls=[call]), reply("이미 03으로 적용했어요.")]
        answer = self.ask("3번 세트로 바꿔줘")
        self.assertIn("아직 적용되지", answer)
        self.assertNotIn("이미 03으로 적용", answer)

    def test_connection_test_uses_draft_key_without_saving_or_enabling_chat(self):
        self.service.save_settings(replace(self.settings, enabled=False), remove_key=True)
        self.api.respond.return_value = reply("", status="incomplete")
        result = self.service.connection_test(new_key="fake-draft-key", model="gpt-5.4-mini")
        self.assertIn("연결을 확인", result)
        self.assertFalse(self.service.ready())
        self.vault.set.assert_not_called()
        self.assertEqual(self.api.respond.call_args.kwargs["purpose"], "test")
        self.assertEqual(self.api.respond.call_args.kwargs["tools"], ())

    def test_proactive_repeat_context_event_controls_and_quiet_today(self):
        self.service.save_settings(replace(self.settings, proactive_enabled=True, proactive_events=("rest",)))
        self.api.respond.return_value = reply("오빠, 물 한 잔 마셔요.")
        self.assertIsNone(self.service.proactive("periodic", context={}, cancel=threading.Event()))
        self.assertIsNotNone(self.service.proactive("rest", context={}, cancel=threading.Event()))
        self.now += 60
        self.assertIsNone(self.service.proactive("rest", context={}, cancel=threading.Event()))
        self.assertIn("물 한 잔", self.api.respond.call_args.kwargs["instructions"])
        self.assertEqual(self.api.respond.call_args.kwargs["purpose"], "event")
        self.service.quiet_today()
        self.assertFalse(self.service.can_proactively_speak("rest"))
        self.service.quiet_today(False)
        self.assertTrue(self.service.can_proactively_speak("rest"))

    def test_proactive_does_not_repeat_the_local_fallback_line(self):
        self.service.save_settings(replace(self.settings, proactive_enabled=True))
        self.api.respond.return_value = reply("물을 마셔요.")
        self.assertIsNone(self.service.proactive("rest", context={"recent_dialogue": ["물을 마셔요."]}, cancel=threading.Event()))

    def test_chatter_and_timer_event_opt_ins_are_independent_and_quiet_applies_to_both(self):
        for chatter, proactive, events, expected in (
            (False, False, ("rest", "periodic"), (False, False, False)),
            (True, False, (), (True, True, False)),
            (False, True, ("rest",), (True, False, True)),
            (False, True, ("periodic",), (True, True, False)),
            (False, True, (), (False, False, False)),
            (True, True, ("rest",), (True, True, True)),
        ):
            with self.subTest(chatter=chatter, proactive=proactive, events=events):
                self.service.save_settings(replace(self.settings, chatter_enabled=chatter,
                                                   proactive_enabled=proactive, proactive_events=events))
                actual = tuple(self.service.can_proactively_speak(event) for event in (None, "periodic", "rest"))
                self.assertEqual(actual, expected)
                self.assertFalse(self.service.can_proactively_speak("return"))
                self.service.quiet_today()
                self.assertFalse(any(self.service.can_proactively_speak(event) for event in (None, "periodic", "rest")))

    def test_chatter_only_generates_new_topic_without_tools_or_silence_instruction(self):
        self.service.save_settings(replace(self.settings, chatter_enabled=True, proactive_enabled=False, proactive_events=()))
        self.now += 60
        self.api.respond.return_value = reply("작은 책방에 들른다면 어떤 책부터 펼쳐보고 싶어요?")
        context = {"current_time": "2026-11-09T14:05:00+09:00", "workday_mode": "normal", "is_away": False,
                   "personality": "warm", "recent_dialogue": ["잠깐 창밖을 봐도 좋겠어요."]}
        answer = self.service.proactive("periodic", context=context, cancel=threading.Event())
        self.assertIn("책방", answer)
        args, kwargs = self.api.respond.call_args
        self.assertNotIn("tools", kwargs)
        self.assertEqual(kwargs["purpose"], "event")
        self.assertNotIn("SILENT", kwargs["instructions"])
        for expected in ("새로운 화제", '"mode": "chatter"', '"personality": "warm"', '"time_of_day": "오후"',
                         "도구나 웹 검색은 사용하지", "수치는 제공된 자료에 있을 때만"):
            self.assertIn(expected, kwargs["instructions"])
        self.assertIn("새로운 화제", args[1][-1]["content"])
        self.api.respond.assert_called_once()
        self.assertEqual(self.service.proactive_diagnostics()["last_outcome"], "generated")
        self.assertEqual(self.service.proactive_diagnostics()["retry_after_seconds"], 60)

    def test_both_modes_share_one_active_request_and_do_not_reset_user_activity(self):
        self.service.save_settings(replace(self.settings, chatter_enabled=True, proactive_enabled=True))
        self.now += 60
        original_user_activity = self.service._last_chat_activity

        def event_while_chattering(*args, **kwargs):
            self.now += 61
            self.assertIsNone(self.service.proactive("rest", context={}, cancel=threading.Event()))
            return reply("새 화제를 하나 꺼내 보고 싶었어요.")

        self.api.respond.side_effect = event_while_chattering
        self.assertIsNotNone(self.service.proactive("periodic", context={}, cancel=threading.Event()))
        self.api.respond.assert_called_once()
        self.assertEqual(self.service._last_chat_activity, original_user_activity)
        self.api.respond.side_effect = None
        self.api.respond.return_value = reply("SILENT")
        self.assertIsNone(self.service.proactive("periodic", context={}, cancel=threading.Event()))
        self.assertEqual(self.api.respond.call_count, 2)
        self.assertEqual(self.service.proactive_diagnostics()["last_outcome"], "silent")

    def test_chatter_only_keeps_budget_limits_and_reports_repeated_results(self):
        self.service.save_settings(replace(self.settings, chatter_enabled=True, proactive_enabled=False,
                                           proactive_events=(), daily_budget_usd=0.001))
        self.now += 60
        self.api.respond.side_effect = AIError("budget_limit", "secret provider detail")
        with self.assertRaises(AIError):
            self.service.proactive("periodic", context={}, cancel=threading.Event())
        self.assertEqual(self.api.respond.call_args.args[0].daily_budget_usd, 0.001)
        self.assertEqual(self.service.proactive_diagnostics()["last_error_code"], "budget_limit")
        self.now += 59
        self.assertIsNone(self.service.proactive("periodic", context={}, cancel=threading.Event()))
        self.api.respond.assert_called_once()
        self.now += 1
        self.api.respond.side_effect = None
        self.api.respond.return_value = reply("책방에서 고른 책은 어떤 이야기일까요?")
        self.assertIsNotNone(self.service.proactive("periodic", context={}, cancel=threading.Event()))
        self.now += 60
        self.assertIsNone(self.service.proactive("periodic", context={}, cancel=threading.Event()))
        self.assertEqual(self.service.proactive_diagnostics()["last_outcome"], "repeated")

    def test_proactive_does_not_repackage_a_recent_chat_sentence(self):
        self.service.save_settings(replace(self.settings, proactive_enabled=True))
        self.api.respond.return_value = reply("물 한 잔 마시고 잠깐 쉬어요.")
        self.ask("잠깐 쉴까요?")
        self.now += 300
        self.api.respond.return_value = reply("오빠, 물 한 잔 마시고 잠깐 쉬어요. 오늘 정말 수고했어요.")
        self.assertIsNone(self.service.proactive("rest", context={}, cancel=threading.Event()))
        self.assertIn("물 한 잔 마시고", self.api.respond.call_args.kwargs["instructions"])
        self.assertEqual(len(self.service.recent_turns()), 1)

    def test_proactive_waits_after_every_attempt_including_failure(self):
        self.service.save_settings(replace(self.settings, proactive_enabled=True))
        self.api.respond.side_effect = [AIError("network", "연결 실패"), reply("돌아오셨네요. 반가워요.")]
        with self.assertRaises(AIError):
            self.service.proactive("rest", context={}, cancel=threading.Event())
        self.now += 59
        self.assertIsNone(self.service.proactive("return", context={}, cancel=threading.Event()))
        self.assertEqual(self.api.respond.call_count, 1)
        self.now += 1
        self.assertIsNotNone(self.service.proactive("return", context={}, cancel=threading.Event()))
        self.assertEqual(self.api.respond.call_count, 2)

    def test_proactive_waits_five_minutes_after_chat_even_for_timer_events(self):
        self.service.save_settings(replace(self.settings, proactive_enabled=True))
        self.api.respond.return_value = reply("회의 내용은 확인했어요.")
        self.ask("회의를 끝냈어요.")
        self.api.respond.reset_mock()
        self.api.respond.return_value = reply("지금은 잠깐 쉬어도 괜찮아요.")
        self.now += 299
        self.assertIsNone(self.service.proactive("rest", context={}, cancel=threading.Event()))
        self.api.respond.assert_not_called()
        self.now += 1
        self.assertIsNotNone(self.service.proactive("rest", context={}, cancel=threading.Event()))

    def test_periodic_uses_configured_interval_and_only_active_work_context(self):
        self.service.save_settings(replace(self.settings, proactive_enabled=True, proactive_interval_minutes=5))
        self.api.respond.side_effect = [reply("오후가 깊어가네요. 잠깐 안부가 궁금했어요."), reply("SILENT")]
        context = {"workday_mode": "normal", "is_away": False}
        self.now += 299
        self.assertIsNone(self.service.proactive("periodic", context=context, cancel=threading.Event()))
        self.now += 1
        for change in ({"is_away": True}, {"workday_mode": "soft_stop"}, {"workday_mode": "hard_stop"}):
            self.assertIsNone(self.service.proactive("periodic", context={**context, **change}, cancel=threading.Event()))
        self.api.respond.assert_not_called()
        self.assertIsNotNone(self.service.proactive("periodic", context=context, cancel=threading.Event()))
        self.now += 299
        self.assertIsNone(self.service.proactive("periodic", context=context, cancel=threading.Event()))
        self.assertEqual(self.api.respond.call_count, 1)
        self.now += 1
        self.assertIsNone(self.service.proactive("periodic", context=context, cancel=threading.Event()))
        self.assertEqual(self.api.respond.call_count, 2)

    def test_one_minute_periodic_waits_until_sixty_seconds_at_startup_and_after_attempt(self):
        self.service.save_settings(replace(self.settings, proactive_enabled=True, proactive_interval_minutes=1))
        self.api.respond.return_value = reply("SILENT")
        context = {"workday_mode": "normal", "is_away": False}
        self.assertIsNone(self.service.proactive("periodic", context=context, cancel=threading.Event()))
        self.now += 59
        self.assertIsNone(self.service.proactive("periodic", context=context, cancel=threading.Event()))
        self.api.respond.assert_not_called()
        self.now += 1
        self.assertIsNone(self.service.proactive("periodic", context=context, cancel=threading.Event()))
        self.assertEqual(self.api.respond.call_count, 1)
        self.now += 59
        self.assertIsNone(self.service.proactive("periodic", context=context, cancel=threading.Event()))
        self.assertEqual(self.api.respond.call_count, 1)
        self.now += 1
        self.assertIsNone(self.service.proactive("periodic", context=context, cancel=threading.Event()))
        self.assertEqual(self.api.respond.call_count, 2)

    def test_timer_event_also_delays_periodic_until_sixty_seconds_after_its_attempt(self):
        self.service.save_settings(replace(self.settings, proactive_enabled=True, proactive_interval_minutes=1))
        self.api.respond.return_value = reply("SILENT")
        self.now += 30
        self.assertIsNone(self.service.proactive("rest", context={}, cancel=threading.Event()))
        self.assertEqual(self.api.respond.call_count, 1)
        self.now += 59
        self.assertIsNone(self.service.proactive("periodic", context={}, cancel=threading.Event()))
        self.assertEqual(self.api.respond.call_count, 1)
        self.now += 1
        self.assertIsNone(self.service.proactive("periodic", context={}, cancel=threading.Event()))
        self.assertEqual(self.api.respond.call_count, 2)

    def test_one_minute_periodic_keeps_budget_denial_cooldown_and_configuration(self):
        settings = replace(self.settings, proactive_enabled=True, proactive_interval_minutes=1, daily_budget_usd=0.001)
        self.service.save_settings(settings)
        self.api.respond.side_effect = AIError("budget_limit", "오늘 남은 비용 한도가 부족해요.")
        self.now += 60
        with self.assertRaises(AIError) as first:
            self.service.proactive("periodic", context={}, cancel=threading.Event())
        self.assertEqual(first.exception.code, "budget_limit")
        self.now += 59
        self.assertIsNone(self.service.proactive("periodic", context={}, cancel=threading.Event()))
        self.assertEqual(self.api.respond.call_count, 1)
        self.now += 1
        with self.assertRaises(AIError):
            self.service.proactive("periodic", context={}, cancel=threading.Event())
        self.assertEqual(self.api.respond.call_count, 2)
        self.assertEqual(self.api.respond.call_args.args[0].daily_budget_usd, 0.001)
        self.assertEqual(self.service.load_settings(), settings)

    def test_one_minute_periodic_still_obeys_ai_off_and_quiet_today(self):
        settings = replace(self.settings, proactive_enabled=True, proactive_interval_minutes=1)
        self.service.save_settings(settings)
        self.now += 60
        self.service.quiet_today()
        self.assertIsNone(self.service.proactive("periodic", context={}, cancel=threading.Event()))
        self.service.save_settings(replace(settings, enabled=False))
        self.assertIsNone(self.service.proactive("periodic", context={}, cancel=threading.Event()))
        self.service.save_settings(replace(settings, proactive_enabled=False))
        self.assertIsNone(self.service.proactive("periodic", context={}, cancel=threading.Event()))
        self.api.respond.assert_not_called()

    def test_periodic_does_not_interrupt_an_active_chat_even_after_five_minutes(self):
        self.service.save_settings(replace(self.settings, proactive_enabled=True, proactive_interval_minutes=1))

        def conversation_in_progress(*args, **kwargs):
            self.now += 600
            self.assertIsNone(self.service.proactive("periodic", context={}, cancel=threading.Event()))
            return reply("대화 답변이에요.")

        self.api.respond.side_effect = conversation_in_progress
        self.assertEqual(self.ask("오래 생각해 주세요."), "대화 답변이에요.")
        self.api.respond.assert_called_once()

    def test_proactive_context_keeps_local_time_personality_and_event_details(self):
        self.service.save_settings(replace(self.settings, proactive_enabled=True))
        self.api.respond.return_value = reply("오늘의 마무리는 조금 느긋해도 괜찮아요.")
        context = {"current_time": "2026-11-09T23:15:00+09:00", "personality": "warm",
                   "workday_mode": "soft_stop", "today_events": [{"event": "break_started"}]}
        self.assertIsNotNone(self.service.proactive("leave", context=context, cancel=threading.Event()))
        instructions = self.api.respond.call_args.kwargs["instructions"]
        for expected in ('"time_of_day": "밤"', '"kind": "leave"', '"personality": "warm"',
                         '"current_time": "2026-11-09T23:15:00+09:00"', '"event": "break_started"'):
            self.assertIn(expected, instructions)
        self.assertIn("일을 더 권하지", instructions)
        self.assertNotIn("tools", self.api.respond.call_args.kwargs)

    def test_proactive_diagnostics_is_a_read_only_snapshot_with_periodic_time_gates(self):
        with patch.object(self.service.ledger, "summary", side_effect=AssertionError("must not read usage")):
            initial = self.service.proactive_diagnostics()
            self.assertEqual(initial["state"], "idle")
            self.assertIsNone(initial["last_outcome"])
            self.assertIsNone(initial["last_event"])
            self.assertIsNone(initial["last_updated_at"])
            self.assertEqual(initial["retry_after_seconds"], 60)
            initial["last_message"] = "caller changed its snapshot"
            self.assertNotEqual(self.service.proactive_diagnostics()["last_message"], initial["last_message"])
            self.now += 0.5
            self.assertEqual(self.service.proactive_diagnostics()["retry_after_seconds"], 60)
            self.now += 58.5
            self.assertEqual(self.service.proactive_diagnostics()["retry_after_seconds"], 1)
            self.now += 1
            self.assertEqual(self.service.proactive_diagnostics()["retry_after_seconds"], 0)
        self.api.respond.assert_not_called()
        self.api.respond.return_value = reply("대화 답변이에요.")
        self.ask("질문이에요.")
        self.assertEqual(self.service.proactive_diagnostics()["retry_after_seconds"], 300)

    def test_proactive_diagnostics_reports_safe_generated_repeated_silent_and_incomplete_results(self):
        self.service.save_settings(replace(self.settings, proactive_enabled=True))
        private_reply = "절대 진단에 노출하면 안 되는 응답 sk-fake-private-content"
        self.api.respond.return_value = reply(private_reply)
        self.assertEqual(self.service.proactive("rest", context={}, cancel=threading.Event()), private_reply)
        generated = self.service.proactive_diagnostics()
        self.assertEqual((generated["state"], generated["last_outcome"], generated["last_event"]),
                         ("idle", "generated", "rest"))
        self.assertIsNone(generated["last_error_code"])
        self.assertIn("화면 표시 여부", generated["last_message"])
        self.assertIsNotNone(datetime.fromisoformat(generated["last_updated_at"]).tzinfo)
        self.assertNotIn(private_reply, json.dumps(generated, ensure_ascii=False))
        self.assertNotIn("sk-fake-private-content", json.dumps(generated))
        self.assertIsNone(self.service.proactive("return", context={}, cancel=threading.Event()))
        self.assertEqual(self.service.proactive_diagnostics()["last_event"], "rest")
        self.now += 60
        self.assertIsNone(self.service.proactive("rest", context={}, cancel=threading.Event()))
        self.assertEqual(self.service.proactive_diagnostics()["last_outcome"], "repeated")
        self.now += 60
        self.api.respond.return_value = reply("SILENT")
        self.assertIsNone(self.service.proactive("return", context={}, cancel=threading.Event()))
        silent = self.service.proactive_diagnostics()
        self.assertEqual(silent["last_outcome"], "silent")
        self.assertTrue(silent["last_message"])
        self.now += 60
        self.api.respond.return_value = reply(private_reply, status="incomplete")
        self.assertIsNone(self.service.proactive("return", context={}, cancel=threading.Event()))
        self.assertEqual(self.service.proactive_diagnostics()["last_outcome"], "incomplete")
        self.service.quiet_today()
        self.now += 60
        self.assertIsNone(self.service.proactive("rest", context={}, cancel=threading.Event()))
        self.assertEqual(self.service.proactive_diagnostics()["last_outcome"], "incomplete")

    def test_proactive_diagnostics_whitelists_error_codes_without_exception_or_response_text(self):
        self.service.save_settings(replace(self.settings, proactive_enabled=True))
        secret = "sk-fake-secret-key-and-private-provider-error"
        for error, expected in (
            (AIError("authentication", secret), "authentication"),
            (AIError("budget_limit", secret), "budget_limit"),
            (AIError("network", secret), "network"),
            (AIError(secret, secret), "unexpected_error"),
            (AIError({"private": secret}, secret), "unexpected_error"),
            (ValueError(secret), "unexpected_error"),
        ):
            with self.subTest(code=expected):
                self.now += 60
                self.api.respond.side_effect = error
                with self.assertRaises(type(error)):
                    self.service.proactive("rest", context={}, cancel=threading.Event())
                diagnostic = self.service.proactive_diagnostics()
                self.assertEqual((diagnostic["state"], diagnostic["last_outcome"], diagnostic["last_error_code"]),
                                 ("idle", "error", expected))
                self.assertEqual(diagnostic["retry_after_seconds"], 60)
                self.assertNotIn(secret, json.dumps(diagnostic, ensure_ascii=False))
                self.assertTrue(diagnostic["last_message"])
        self.now += 60
        self.api.respond.side_effect = None
        self.api.respond.return_value = reply("SILENT")
        self.service.proactive("rest", context={}, cancel=threading.Event())
        self.assertIsNone(self.service.proactive_diagnostics()["last_error_code"])

    def test_proactive_diagnostics_sanitizes_context_failure_and_clears_worker_state(self):
        self.service.save_settings(replace(self.settings, proactive_enabled=True))
        secret = "sk-fake-private-storage-error"
        with patch.object(self.service, "_history_context", side_effect=OSError(secret)):
            with self.assertRaises(OSError):
                self.service.proactive("rest", context={}, cancel=threading.Event())
        diagnostic = self.service.proactive_diagnostics()
        self.assertEqual((diagnostic["state"], diagnostic["last_outcome"], diagnostic["last_error_code"]),
                         ("idle", "error", "unexpected_error"))
        self.assertNotIn(secret, json.dumps(diagnostic, ensure_ascii=False))
        self.api.respond.assert_not_called()

    def test_proactive_keeps_single_flight_until_cancelled_worker_returns(self):
        self.service.save_settings(replace(self.settings, proactive_enabled=True))
        entered, release = threading.Event(), threading.Event()
        cancel = threading.Event()
        errors = []

        def delayed(*args, **kwargs):
            entered.set()
            if not release.wait(5):
                raise TimeoutError("fake transport did not release")
            return reply("늦게 온 자동 안내예요.")

        self.api.respond.side_effect = delayed

        def request():
            try:
                self.service.proactive("rest", context={}, cancel=cancel)
            except AIError as error:
                errors.append(error.code)

        worker = threading.Thread(target=request)
        worker.start()
        try:
            self.assertTrue(entered.wait(5))
            requesting = self.service.proactive_diagnostics()
            self.assertEqual((requesting["state"], requesting["last_event"], requesting["last_outcome"]),
                             ("requesting", "rest", None))
            cancel.set()
            self.now += 61
            self.assertEqual(self.service.proactive_diagnostics()["state"], "requesting")
            self.assertIsNone(self.service.proactive("return", context={}, cancel=threading.Event()))
            self.assertEqual(self.api.respond.call_count, 1)
        finally:
            release.set()
            worker.join(5)
        self.assertFalse(worker.is_alive())
        self.assertEqual(errors, ["cancelled"])
        self.assertIsNone(self.service._active_proactive_cancel)
        self.assertEqual(list(self.service._proactive_recent), [])
        cancelled = self.service.proactive_diagnostics()
        self.assertEqual((cancelled["state"], cancelled["last_outcome"], cancelled["last_error_code"]),
                         ("idle", "cancelled", None))

    def test_new_chat_cancels_in_flight_proactive_and_discards_its_result(self):
        self.service.save_settings(replace(self.settings, proactive_enabled=True))
        cancel = threading.Event()

        def chat_during_proactive(*args, **kwargs):
            if kwargs.get("purpose") == "event":
                self.api.respond.side_effect = None
                self.api.respond.return_value = reply("사용자 질문에 답했어요.")
                self.assertEqual(self.ask("질문이 있어요."), "사용자 질문에 답했어요.")
                return reply("표시되면 안 되는 이전 자동 안내예요.")
            raise AssertionError("unexpected fake call")

        self.api.respond.side_effect = chat_during_proactive
        with self.assertRaises(AIError) as error:
            self.service.proactive("rest", context={}, cancel=cancel)
        self.assertEqual(error.exception.code, "cancelled")
        self.assertTrue(cancel.is_set())
        self.assertEqual(list(self.service._proactive_recent), [])
        self.assertIsNone(self.service._active_proactive_cancel)

    def test_quiet_setting_cancels_proactive_and_incomplete_text_is_not_displayed(self):
        self.service.save_settings(replace(self.settings, proactive_enabled=True))

        def quiet_during_request(*args, **kwargs):
            self.service.quiet_today()
            return reply("표시되면 안 되는 자동 안내예요.")

        self.api.respond.side_effect = quiet_during_request
        with self.assertRaises(AIError) as error:
            self.service.proactive("rest", context={}, cancel=threading.Event())
        self.assertEqual(error.exception.code, "cancelled")
        self.assertEqual(list(self.service._proactive_recent), [])
        self.service.quiet_today(False)
        self.now += 60
        self.api.respond.side_effect = None
        self.api.respond.return_value = reply("아직 끝나지 않은 문장", status="incomplete")
        self.assertIsNone(self.service.proactive("rest", context={}, cancel=threading.Event()))
        self.assertEqual(list(self.service._proactive_recent), [])


class AssistantStartupKeyRecoveryTests(unittest.TestCase):
    def test_settings_read_failures_preserve_protected_key_across_restarts(self):
        fake_key = "sk-fake-recovery-test-never-used"
        windows = SimpleNamespace(name="nt", fsync=os.fsync, replace=os.replace)
        def fake_dpapi(data, *, protect):
            return b"protected:" + data[::-1] if protect else data.removeprefix(b"protected:")[::-1]
        for failure in ("invalid_json", "invalid_encoding", "unreadable"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory, \
                    patch("assistant_ai.config.os", windows), \
                    patch("assistant_ai.config._dpapi", side_effect=fake_dpapi), \
                    patch("assistant_ai.service.ResponsesClient") as client:
                root = Path(directory)
                vault = KeyVault(root)
                vault.set(fake_key, persist=True)
                ciphertext = vault.path.read_bytes()
                settings_path = root / "ai_settings.json"
                settings_path.write_bytes(b"\xff" if failure == "invalid_encoding" else b"{broken")
                original_read = Path.read_text
                def read_text(path, *args, **kwargs):
                    if failure == "unreadable" and path == settings_path:
                        raise PermissionError("test settings read denied")
                    return original_read(path, *args, **kwargs)
                with patch.object(Path, "read_text", read_text):
                    for _ in range(2):
                        service = AssistantService(root)
                        self.assertEqual(vault.path.read_bytes(), ciphertext)
                        self.assertEqual(KeyVault(root).get(), fake_key)
                        self.assertTrue(service.has_key())
                        self.assertTrue(service.persistent_key)
                        self.assertEqual(service.load_settings().key_persistence, "windows")
                        self.assertFalse(service.ready())
                        self.assertFalse(service.load_settings().memory_enabled)
                        self.assertFalse(service.load_settings().conversation_storage_enabled)
                        self.assertTrue(service.settings_issue)
                        self.assertNotIn(fake_key, service.settings_issue)
                # The user can repair settings without changing key storage.
                service.save_settings(service.load_settings())
                self.assertEqual(vault.path.read_bytes(), ciphertext)
                self.assertEqual(AssistantService(root).load_settings().key_persistence, "windows")
                # An explicit, valid session-only choice still performs conversion.
                service.save_settings(replace(service.load_settings(), key_persistence="session"))
                self.assertFalse(vault.path.exists())
                self.assertTrue(service.has_key())
                client.assert_not_called()


if __name__ == "__main__":
    unittest.main()
