"""Pure synthetic metadata tests: no user images, file writes, or API calls."""
from dataclasses import FrozenInstanceError
import json
import unittest
from unittest.mock import patch

from chat_asset_commands import (
    AssetCatalog, AssetChoice, AssetCommand, MAX_CATALOG_IMAGES,
    allowed_asset_tools, build_asset_tools, build_scoped_asset_tools,
    catalog_context, classify_chat_intent, guard_asset_command,
    is_asset_change_request, is_timer_status_query, is_timer_status_request,
    validate_asset_call,
)

REST_ID = "img_" + "a" * 24
CHEER_ID = "img_" + "b" * 24
DEFAULT_ID = "img_" + "c" * 24
MASTER_ID = "img_" + "d" * 24


def catalog():
    return AssetCatalog((3, 1), (
        AssetChoice(REST_ID, "rest", 3, "rest_03.png"),
        AssetChoice(CHEER_ID, "cheer", 3, "cheer_03.png"),
        AssetChoice(DEFAULT_ID, "default", 1, "default_01.png"),
        AssetChoice(MASTER_ID, "default", None, "main_kyunghee.png"),
    ), current_set=3, current_asset_id=REST_ID)


class CatalogTests(unittest.TestCase):
    def test_catalog_and_choices_are_immutable_typed_metadata(self):
        value = catalog()
        self.assertEqual(value.sets, (1, 3))
        with self.assertRaises(FrozenInstanceError):
            value.current_set = 1
        with self.assertRaises(FrozenInstanceError):
            value.images[0].role = "away"
        self.assertEqual(AssetChoice(REST_ID, "rest", filename="REST_03.PNG").number, 3)

    def test_catalog_rejects_invalid_ids_roles_numbers_and_private_names(self):
        invalid = (
            ("../../rest_03.png", "rest", 3, ""), ("img_short", "rest", 3, ""),
            (REST_ID, "other", 3, ""), (REST_ID, "rest", True, ""),
            (REST_ID, "rest", 0, ""), (REST_ID, "rest", 100, ""),
            (REST_ID, "rest", 3, "/home/user/rest_03.png"),
            (REST_ID, "rest", 3, "C:\\private\\rest_03.png"),
            (REST_ID, "rest", 3, "sk-secret-key.png"),
            (REST_ID, "rest", 3, "arbitrary_private_name.png"),
            (REST_ID, "cheer", 3, "rest_03.png"), (REST_ID, "rest", 1, "rest_03.png"),
            (REST_ID, "default", 3, "main_kyunghee.png"), (REST_ID, "rest", 0, "rest_00.png"),
        )
        for args in invalid:
            with self.subTest(args=args), self.assertRaises(ValueError):
                AssetChoice(*args)

    def test_duplicate_ids_mutable_collections_and_oversized_catalog_are_rejected(self):
        choice = AssetChoice(REST_ID, "rest", 3, "rest_03.png")
        for sets, images in (
            ([1], (choice,)), ((True,), (choice,)), ((1, 1), (choice,)),
            ((100,), (choice,)), ((1,), [choice]), ((1,), ("invalid",)),
            ((1,), (choice, choice)),
        ):
            with self.subTest(sets=sets), self.assertRaises(ValueError):
                AssetCatalog(sets, images)
        images = tuple(AssetChoice(f"img_{n:024x}", "default") for n in range(MAX_CATALOG_IMAGES + 1))
        with self.assertRaises(ValueError):
            AssetCatalog((), images)

    def test_context_contains_generated_labels_and_only_valid_current_members(self):
        value = catalog_context(catalog())
        self.assertEqual(value["available_sets"], [1, 3])
        self.assertEqual(value["current_set"], 3)
        self.assertEqual(value["current_asset_id"], REST_ID)
        self.assertEqual(value["images"][0]["label"], "휴식 · 03번")
        custom = AssetCatalog((1,), (AssetChoice(REST_ID, "rest"),), 3, CHEER_ID)
        metadata = catalog_context(custom)
        self.assertNotIn("current_set", metadata)
        self.assertNotIn("current_asset_id", metadata)
        self.assertNotIn("filename", metadata["images"][0])
        self.assertNotIn("/", json.dumps(metadata))
        value["images"][0]["role"] = "away"
        self.assertEqual(catalog().images[0].role, "rest")

    def test_dynamic_schemas_use_catalog_enums_and_strict_empty_read_tools(self):
        tools = {item["name"]: item for item in build_asset_tools(catalog())}
        self.assertEqual(set(tools), {"select_asset_set", "select_asset_image", "list_assets", "get_timer_status"})
        self.assertEqual(tools["select_asset_set"]["parameters"]["properties"]["number"]["enum"], [1, 3])
        self.assertEqual(tools["select_asset_image"]["parameters"]["properties"]["asset_id"]["enum"],
                         [REST_ID, CHEER_ID, DEFAULT_ID, MASTER_ID])
        for tool in tools.values():
            self.assertTrue(tool["strict"])
            self.assertFalse(tool["parameters"]["additionalProperties"])
            self.assertEqual(set(tool["parameters"]["required"]), set(tool["parameters"]["properties"]))
        for name in ("list_assets", "get_timer_status"):
            self.assertEqual(tools[name]["parameters"]["properties"], {})
        self.assertEqual({t["name"] for t in build_asset_tools(AssetCatalog())},
                         {"list_assets", "get_timer_status"})


class ToolValidationTests(unittest.TestCase):
    def setUp(self):
        self.catalog = catalog()

    def test_valid_calls_return_only_immutable_typed_commands(self):
        self.assertEqual(validate_asset_call("select_asset_set", {"number": 3}, self.catalog), AssetCommand("set", 3))
        self.assertEqual(validate_asset_call("select_asset_image", {"asset_id": REST_ID}, self.catalog),
                         AssetCommand("file", asset_id=REST_ID))
        self.assertEqual(validate_asset_call("list_assets", {}, self.catalog), AssetCommand("list"))
        self.assertEqual(validate_asset_call("get_timer_status", "{}", self.catalog), AssetCommand("status"))
        with self.assertRaises(FrozenInstanceError):
            validate_asset_call("select_asset_set", {"number": 3}, self.catalog).number = 1

    def test_missing_extra_untyped_and_out_of_catalog_args_are_rejected(self):
        calls = (
            ("select_asset_set", {}), ("select_asset_set", {"number": True}),
            ("select_asset_set", {"number": "3"}), ("select_asset_set", {"number": 3.0}),
            ("select_asset_set", {"number": 0}), ("select_asset_set", {"number": 99}),
            ("select_asset_set", {"number": 3, "path": "/secret"}),
            ("select_asset_image", {"asset_id": "rest_03.png"}),
            ("select_asset_image", {"asset_id": "img_" + "f" * 24}),
            ("select_asset_image", {"asset_id": REST_ID, "role": "rest"}),
            ("select_asset_image", {"asset_id": [REST_ID]}),
            ("list_assets", {"number": 1}), ("get_timer_status", {"settings": {"timer": 0}}),
            ("run_shell", {"command": "anything"}), ("select_asset_set", []), ("select_asset_set", None),
        )
        for name, args in calls:
            with self.subTest(name=name, args=args), self.assertRaises(ValueError):
                validate_asset_call(name, args, self.catalog)

    def test_json_is_bounded_and_duplicate_keys_invalid_unicode_or_nested_values_fail(self):
        for args in (
            '{"number":1,"number":3}', '{"number":', "null", "[]",
            '{"number":{"value":3}}', '{"number":3}' + " " * 2048, "\ud800",
        ):
            with self.subTest(args=repr(args)[:80]), self.assertRaises(ValueError):
                validate_asset_call("select_asset_set", args, self.catalog)
        self.assertEqual(validate_asset_call("select_asset_set", '{"number":3}', self.catalog), AssetCommand("set", 3))

    def test_command_constructor_rejects_extra_scope_and_untyped_numbers(self):
        for args in (
            ("set", True, None), ("set", 0, None), ("set", 3, REST_ID),
            ("file", 3, REST_ID), ("file", None, "/tmp/rest.png"),
            ("status", 3, None), ("list", None, REST_ID), ("shell", None, None), ([], None, None),
        ):
            with self.subTest(args=args), self.assertRaises(ValueError):
                AssetCommand(*args)


class OriginalIntentGuardTests(unittest.TestCase):
    def setUp(self):
        self.catalog = catalog()
        self.set3 = AssetCommand("set", 3)
        self.rest3 = AssetCommand("file", asset_id=REST_ID)

    def test_clear_set_commands_allow_spaces_politeness_and_number_normalization(self):
        for text in (
            "3번 세트로 바꿔", "이미지 3번으로 변경", "3번세트로바꿔줘",
            "세트03으로 변경해주세요", "사진 3번으로 설정해줘", "３번 세트로 바꿔 주세요",
            "승아야, 지금 3번 세트로 바꿔줄래?", "3번 이미지 세트 보고 싶어",
        ):
            with self.subTest(text=text):
                self.assertEqual(guard_asset_command(self.set3, text, self.catalog), self.set3)

    def test_specific_role_and_exact_filename_select_only_matching_image(self):
        for text in (
            "3번 휴식 이미지로 바꿔", "3번휴식이미지로바꿔줘", "휴식03 보여줘",
            "rest 3번 이미지로 변경해줘", "rest_03.png로 바꿔", "REST_03.PNG를 보여주세요",
        ):
            with self.subTest(text=text):
                self.assertEqual(guard_asset_command(self.rest3, text, self.catalog), self.rest3)
        master = AssetCommand("file", asset_id=MASTER_ID)
        self.assertEqual(guard_asset_command(master, "main_kyunghee.png로 바꿔", self.catalog), master)

    def test_model_cannot_substitute_an_installed_number_or_change_scope(self):
        for command, text in (
            (self.set3, "99번 세트로 바꿔"), (self.set3, "1번 세트로 바꿔"),
            (self.set3, "3번 휴식 이미지로 바꿔"), (self.rest3, "3번 세트로 바꿔"),
            (self.rest3, "이미지 3번으로 변경"), (self.rest3, "3번 응원 이미지로 바꿔"),
            (self.rest3, "cheer_03.png로 바꿔"),
        ):
            with self.subTest(text=text), self.assertRaises(ValueError):
                guard_asset_command(command, text, self.catalog)

    def test_negation_and_hypothetical_requests_never_authorize_a_tool_action(self):
        for text in (
            "3번 세트로 바꾸지 마", "3번 세트로 바꿔 주지 마", "3번 세트로 바꿔주지 마",
            "3번 세트로 바꿔선 안 돼", "3번 세트로 바꿔 주면 좋을까?", "3번 세트로 바꿔도 될까?",
            "3번 세트로 변경해 주지 마세요", "3번 세트로 보여주지 말아줘",
            "3번 세트로 바꿔야 하나?", "3번 세트로 바꿔줄 필요 없어",
            "3번 세트로 바꿔주지 않으면 좋겠어", "만약 3번 세트로 바꿔줘",
            "3번 세트로 바꿔달라고 말하면 돼?", "3번 세트로 바꿔줄래라고 물어봐",
        ):
            with self.subTest(text=text), self.assertRaises(ValueError):
                guard_asset_command(self.set3, text, self.catalog)

    def test_quotes_unrelated_numbered_chat_ambiguities_and_compound_requests_are_refused(self):
        for text in (
            "'3번 세트로 바꿔'", "“3번 세트로 바꿔”라고 하면 돼?",
            chr(96) + "3번 세트로 바꿔" + chr(96), "3번 회의가 힘들었어", "3번 세트가 좋아",
            "3번 세트로 변경했어?", "3번 또는 1번 세트로 바꿔", "3번이랑 1번 세트로 바꿔",
            "3번 휴식 응원 이미지로 바꿔", "3번 세트로 바꿔 그리고 타이머 종료해",
            "다른 이미지로 바꿔", "3번으로 바꿔", "3분 휴식으로 바꿔", "아무 이미지나 보여줘",
            "3번 세트로 바꿔\n1번 세트로 바꿔", "3번 세트로 바꿔\0", "3번 세트로 바꿔" + " " * 400, "",
        ):
            with self.subTest(text=text), self.assertRaises(ValueError):
                guard_asset_command(self.set3, text, self.catalog)

    def test_paths_urls_unknown_files_and_model_prose_are_not_commands(self):
        for text in (
            "../../rest_03.png로 바꿔", "C:\\secret\\rest_03.png로 바꿔", "C:rest_03.png로 바꿔",
            "https://example.com/rest_03.png로 바꿔", "other.png로 바꿔", "3번 휴식 이미지로 바꿨어요.",
        ):
            with self.subTest(text=text), self.assertRaises(ValueError):
                guard_asset_command(self.rest3, text, self.catalog)

    def test_duplicate_filename_role_number_and_stale_choices_need_clarification(self):
        duplicate = AssetChoice("img_" + "e" * 24, "rest", 3, "rest_03.png")
        ambiguous = AssetCatalog((3,), self.catalog.images + (duplicate,))
        for text in ("rest_03.png로 바꿔", "3번 휴식 이미지로 바꿔"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                guard_asset_command(self.rest3, text, ambiguous)
        fresh = AssetCatalog((1,), ())
        with self.assertRaises(ValueError):
            guard_asset_command(self.rest3, "rest_03.png로 바꿔", fresh)
        with self.assertRaises(ValueError):
            guard_asset_command(self.set3, "3번 세트로 바꿔", fresh)

    def test_broad_change_hint_does_not_authorize_an_ambiguous_write(self):
        for text in ("3번 세트로 바꿔", "3번 휴식 이미지로 바꿔", "rest_03.png로 바꿔", "다른 이미지로 바꿔"):
            self.assertTrue(is_asset_change_request(text))
        for text in ("오늘 3번 회의했어", "고마워", "지금 몇 시야?"):
            self.assertFalse(is_asset_change_request(text))
        with self.assertRaises(ValueError):
            guard_asset_command(self.set3, "다른 이미지로 바꿔", self.catalog)


class ReadOnlyStatusTests(unittest.TestCase):
    def test_clock_and_actual_usage_queries_accept_common_wording(self):
        for text in (
            "지금 몇시야?", "몇 시인지 알려주세요", "현재 시간 알려줘", "오늘 얼마나 일했어?",
            "오늘 일한 시간 알려줘", "지금 상태 알려줘", "사용 시간 알려줘", "오늘얼마나썼어",
            "연속 사용 시간 알려줘", "자리비움 시간 알려줘", "지금 얼마나 썼어?",
            "현재 사용시간 얼마야", "타이머 상태 알려줘", "집중 시간 알려줘", "휴식 시간 알려줘",
        ):
            with self.subTest(text=text):
                self.assertTrue(is_timer_status_query(text))
                self.assertTrue(is_timer_status_request(text))
                self.assertEqual(guard_asset_command(AssetCommand("status"), text, AssetCatalog()), AssetCommand("status"))

    def test_ordinary_or_negative_time_talk_is_not_a_status_query(self):
        for text in (
            "시간 여행 영화 추천해줘", "오늘 3번 회의했어", "시간 알려주지 마", "만약 지금 몇시야",
            "'지금 몇시야'라고 물어봐", "타이머 시간을 3분으로 바꿔", "시스템 명령 실행해", "",
        ):
            with self.subTest(text=text):
                self.assertFalse(is_timer_status_query(text))
                with self.assertRaises(ValueError):
                    guard_asset_command(AssetCommand("status"), text, AssetCatalog())

    def test_read_only_list_and_pure_helpers_do_no_filesystem_io(self):
        with patch("builtins.open", side_effect=AssertionError("unexpected file access")):
            self.assertEqual(guard_asset_command(AssetCommand("list"), "목록 보여줘", AssetCatalog()), AssetCommand("list"))
            self.assertTrue(is_timer_status_query("지금 몇시야"))
            self.assertEqual(validate_asset_call("get_timer_status", {}, AssetCatalog()), AssetCommand("status"))


class ChatIntentRoutingTests(unittest.TestCase):
    def test_ordinary_conversation_never_exposes_tools_or_looks_like_asset_mutation(self):
        for text in (
            "안녕", "오늘 기분 어때", "나 오늘 피곤해", "고마워", "오늘 점심 뭐 먹었어?",
            "오늘 피곤하니까 쉬는 방법 알려줘", "쉬는 방법 보여줘", "휴식의 기본을 보여줘",
            "기본 설정해줘", "기본을 설정해줘", "휴식 보여줘", "오늘 작업 어때",
            "오늘 3번 회의했어", "휴식 3분 보여줘", "세트메뉴 보여줘",
        ):
            with self.subTest(text=text):
                self.assertEqual(classify_chat_intent(text), "chat")
                self.assertEqual(allowed_asset_tools(text), ())
                self.assertEqual(build_scoped_asset_tools(catalog(), text), [])
                self.assertFalse(is_asset_change_request(text))

    def test_asset_discussion_negatives_and_hypotheticals_remain_text_conversation(self):
        for text in (
            "3번 이미지 어때?", "사진이 마음에 들어", "이미지를 바꾸는 방법 알려줘",
            "이미지 변경은 어떻게 하는 거야?", "사진 선택 방법 보여줘",
            "3번 세트로 변경했어?", "3번 세트로 바꿔 주지 마",
            "3번 세트로 바꿔선 안 돼", "3번 세트로 바꿔 주면 좋을까?",
            "만약 3번 세트로 바꿔줘", "'3번 세트로 바꿔'라고 말하면 돼?",
        ):
            with self.subTest(text=text):
                self.assertEqual(classify_chat_intent(text), "chat")
                self.assertEqual(allowed_asset_tools(text), ())
                self.assertFalse(is_asset_change_request(text))

    def test_clear_set_and_image_requests_offer_only_the_matching_selection_tool(self):
        examples = {
            "3번 세트로 바꿔": "select_asset_set",
            "이미지 3번으로 변경": "select_asset_set",
            "99번 세트로 바꿔": "select_asset_set",
            "3번 휴식 이미지로 바꿔": "select_asset_image",
            "휴식03 보여줘": "select_asset_image",
            "rest_03.png로 바꿔": "select_asset_image",
            "main_kyunghee.png로 바꿔": "select_asset_image",
        }
        for text, name in examples.items():
            with self.subTest(text=text):
                self.assertEqual(classify_chat_intent(text), "asset_change")
                self.assertEqual(allowed_asset_tools(text), (name,))
                self.assertEqual([tool["name"] for tool in build_scoped_asset_tools(catalog(), text)], [name])
                self.assertTrue(is_asset_change_request(text))

    def test_ambiguous_asset_mutations_need_clarification_without_tools(self):
        for text in (
            "다른 이미지로 바꿔", "이미지 바꿔줘", "이미지좀보여줘", "휴식 이미지 보여줘",
            "3번 또는 1번 세트로 바꿔", "3번 휴식 응원 이미지로 바꿔",
            "3번 세트로 바꿔 그리고 1번으로 바꿔", "0번 세트로 바꿔",
            "003번 세트로 바꿔", "unknown.png로 바꿔",
        ):
            with self.subTest(text=text):
                self.assertEqual(classify_chat_intent(text), "asset_ambiguous")
                self.assertEqual(allowed_asset_tools(text), ())
                self.assertEqual(build_scoped_asset_tools(catalog(), text), [])
                self.assertTrue(is_asset_change_request(text))

    def test_installed_asset_list_queries_offer_only_read_only_list_tool(self):
        for text in (
            "이미지 목록 보여줘", "세트 목록", "설치된 세트 알려줘", "사용 가능한 이미지 보여줘",
            "어떤 이미지가 있어?", "무슨 세트가 있니?", "이미지들 목록 보여줘", "이미지가 몇 개야?",
        ):
            with self.subTest(text=text):
                self.assertEqual(classify_chat_intent(text), "asset_list")
                self.assertEqual(allowed_asset_tools(text), ("list_assets",))
                self.assertEqual([t["name"] for t in build_scoped_asset_tools(AssetCatalog(), text)], ["list_assets"])
                self.assertFalse(is_asset_change_request(text))

    def test_actual_timer_queries_offer_only_status_without_an_asset_catalog(self):
        for text in ("지금 몇시야?", "오늘 사용 시간 알려줘", "현재 타이머 상태 알려줘"):
            with self.subTest(text=text):
                self.assertEqual(classify_chat_intent(text), "timer_status")
                self.assertEqual(allowed_asset_tools(text), ("get_timer_status",))
                self.assertEqual([t["name"] for t in build_scoped_asset_tools(AssetCatalog(), text)], ["get_timer_status"])
                self.assertFalse(is_asset_change_request(text))

    def test_scoper_preserves_existing_schema_api_and_does_not_replace_write_guard(self):
        self.assertEqual(len(build_asset_tools(catalog())), 4)
        self.assertEqual(build_scoped_asset_tools(AssetCatalog(), "3번 세트로 바꿔"), [])
        # Routing may offer an existing-number enum, but cannot authorize a
        # substituted model choice when the user explicitly requested 99.
        proposed = validate_asset_call("select_asset_set", {"number": 3}, catalog())
        with self.assertRaises(ValueError):
            guard_asset_command(proposed, "99번 세트로 바꿔", catalog())
        with patch("builtins.open", side_effect=AssertionError("unexpected file access")):
            self.assertEqual(classify_chat_intent("안녕"), "chat")
            self.assertEqual(allowed_asset_tools("안녕"), ())


if __name__ == "__main__":
    unittest.main()
