from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date
import io
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from assistant_ai.api import AIError, RESPONSES_URL, ResponsesClient, UsageLedger
from assistant_ai.config import AISettings, ConfigStore, KeyVault, SettingsError


TEST_KEY = "sk-example-dummy-key-1234567890"


class AssistantConfigTests(unittest.TestCase):
    def test_settings_round_trip_and_opt_in_defaults(self):
        with TemporaryDirectory() as directory:
            store = ConfigStore(Path(directory))
            defaults = store.load()
            self.assertFalse(defaults.enabled)
            self.assertFalse(defaults.memory_enabled)
            self.assertFalse(defaults.proactive_enabled)
            self.assertIsNone(defaults.daily_request_limit)
            self.assertIsNone(defaults.daily_token_limit)
            self.assertIsNone(defaults.daily_budget_usd)
            expected = replace(defaults, enabled=True, memory_enabled=True, daily_request_limit=5,
                               daily_token_limit=1000, daily_budget_usd=0.25)
            store.save(expected)
            self.assertEqual(store.load(), expected)
            self.assertNotIn("api_key", store.path.read_text(encoding="utf-8"))

    def test_settings_validation_and_corrupt_configuration(self):
        for change in (
            {"model": "not a model"}, {"model": TEST_KEY}, {"enabled": "true"},
            {"daily_request_limit": 0}, {"daily_token_limit": True},
            {"daily_budget_usd": float("nan")}, {"daily_budget_usd": 1, "model": "custom-model"},
        ):
            with self.subTest(change=change), self.assertRaises(SettingsError):
                replace(AISettings(), **change).validate()
        AISettings(model="ft:gpt-5.4-mini:team:assistant:1234").validate()
        with TemporaryDirectory() as directory:
            store = ConfigStore(Path(directory))
            store.path.write_text("{invalid", encoding="utf-8")
            with self.assertRaises(SettingsError):
                store.load()

    @unittest.skipIf(os.name == "nt", "non-Windows key storage is session-only")
    def test_non_windows_key_never_reaches_disk(self):
        with TemporaryDirectory() as directory:
            path = Path(directory)
            vault = KeyVault(path)
            self.assertFalse(vault.persistent)
            vault.set(f" {TEST_KEY} ")
            self.assertEqual(vault.get(), TEST_KEY)
            self.assertIsNone(KeyVault(path).get())
            self.assertEqual(list(path.iterdir()), [])
            vault.delete()
            self.assertIsNone(vault.get())

    @unittest.skipUnless(os.name == "nt", "Windows DPAPI is unavailable")
    def test_windows_key_is_encrypted_and_reopens(self):
        with TemporaryDirectory() as directory:
            path = Path(directory)
            vault = KeyVault(path)
            self.assertTrue(vault.persistent)
            vault.set(TEST_KEY)
            self.assertNotIn(TEST_KEY.encode("ascii"), vault.path.read_bytes())
            self.assertEqual(KeyVault(path).get(), TEST_KEY)
            vault.delete()
            self.assertIsNone(KeyVault(path).get())

    def test_protection_error_never_falls_back_to_plaintext(self):
        with TemporaryDirectory() as directory:
            vault = KeyVault(Path(directory))
            vault.persistent = True
            with patch("assistant_ai.config._dpapi", side_effect=OSError(TEST_KEY)):
                with self.assertRaises(SettingsError) as failure:
                    vault.set(TEST_KEY)
            self.assertNotIn(TEST_KEY, str(failure.exception))
            self.assertFalse(vault.path.exists())


class AssistantAPITests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(TemporaryDirectory())
        self.path = Path(directory)
        self.day = date(2026, 11, 9)
        self.ledger = UsageLedger(self.path, today=lambda: self.day)
        self.settings = AISettings(enabled=True)
        self.requests = []
        self.input = [{"role": "user", "content": "오늘 사용량을 알려 줘."}]

    def respond(self, *, settings=None, transport=None, input_items=None, tools=()):
        client = ResponsesClient(TEST_KEY, self.ledger, transport=transport or self.successful_transport)
        return client.respond(settings or self.settings, self.input if input_items is None else input_items,
                              instructions="타이머 도우미", tools=tools)

    def successful_transport(self, request, *, timeout):
        self.requests.append(request)
        return self.response_stream()

    @staticmethod
    def response_stream(*, output=None, usage=None, status="completed"):
        if output is None:
            output = [{"type": "message", "content": [{"type": "output_text", "text": "확인했어요."}]}]
        if usage is None:
            usage = {"input_tokens": 100, "output_tokens": 10, "total_tokens": 110,
                     "input_tokens_details": {"cached_tokens": 20}}
        return io.BytesIO(json.dumps({"id": "resp_test", "status": status, "output": output, "usage": usage}).encode())

    def test_stateless_tool_history_and_usage_round_trip(self):
        output = [
            {"id": "rs_1", "type": "reasoning", "summary": [], "encrypted_content": "ciphertext"},
            {"id": "fc_1", "type": "function_call", "call_id": "call_1", "name": "get_usage_stats",
             "arguments": '{"days":1}'},
        ]
        tools = [{"type": "function", "name": "get_usage_stats", "parameters": {"type": "object"}}]
        first = self.respond(transport=lambda *args, **kwargs: self.response_stream(output=output), tools=tools)
        self.assertEqual(first.output, output)
        continuation = self.input + first.output + [{"type": "function_call_output", "call_id": "call_1", "output": "{}"}]
        second = self.respond(input_items=continuation, tools=tools)
        self.assertEqual(second.text, "확인했어요.")
        self.assertEqual(second.response_id, "resp_test")
        request = self.requests[0]
        payload = json.loads(request.data)
        self.assertEqual(request.full_url, RESPONSES_URL)
        self.assertEqual(request.get_header("Authorization"), f"Bearer {TEST_KEY}")
        self.assertFalse(payload["store"])
        self.assertFalse(payload["parallel_tool_calls"])
        self.assertEqual(payload["include"], ["reasoning.encrypted_content"])
        self.assertEqual(payload["input"], continuation)
        self.assertEqual(payload["tools"], tools)
        self.assertNotIn("max_output_tokens", payload)
        summary = UsageLedger(self.path, today=lambda: self.day).summary()
        self.assertEqual((summary.requests, summary.input_tokens, summary.output_tokens, summary.total_tokens), (2, 200, 20, 220))
        self.assertAlmostEqual(summary.estimated_cost_usd, 0.000213)
        contents = self.ledger.path.read_bytes()
        self.assertNotIn(TEST_KEY.encode(), contents)
        self.assertNotIn(b"ciphertext", contents)
        self.assertNotIn(self.input[0]["content"].encode(), contents)

    def test_request_cap_is_atomic_and_rolls_over_by_local_date(self):
        entered = Event()
        release = Event()
        settings = replace(self.settings, daily_request_limit=1)

        def wait_transport(request, *, timeout):
            entered.set()
            if not release.wait(5):
                raise TimeoutError
            return self.response_stream()

        with ThreadPoolExecutor(max_workers=1) as workers:
            first = workers.submit(self.respond, settings=settings, transport=wait_transport)
            try:
                self.assertTrue(entered.wait(5))
                other = ResponsesClient(TEST_KEY, UsageLedger(self.path, today=lambda: self.day),
                                        transport=self.successful_transport)
                with self.assertRaises(AIError) as error:
                    other.respond(settings, self.input, instructions="타이머 도우미")
                self.assertEqual(error.exception.code, "request_limit")
                self.assertEqual(self.requests, [])
            finally:
                release.set()
            first.result(timeout=5)
        self.assertEqual(self.ledger.summary().requests, 1)
        self.day = date(2026, 11, 10)
        self.respond(settings=settings)
        self.assertEqual(self.ledger.summary().date, "2026-11-10")
        self.assertEqual(self.ledger.summary().requests, 1)

    def test_optional_token_and_budget_limits_apply_before_transport(self):
        for field, amount, code in (
            ("daily_token_limit", 20, "token_limit"), ("daily_budget_usd", 0.000001, "budget_limit"),
        ):
            with self.subTest(code=code), self.assertRaises(AIError) as error:
                self.respond(settings=replace(self.settings, **{field: amount}))
            self.assertEqual(error.exception.code, code)
        self.assertEqual(self.requests, [])
        self.assertEqual(self.ledger.summary().requests, 0)

        self.respond(settings=replace(self.settings, daily_token_limit=1200, daily_budget_usd=0.002))
        cap = json.loads(self.requests[0].data)["max_output_tokens"]
        self.assertGreaterEqual(cap, 16)
        self.assertLess(cap, 0.002 / 0.0000045)

    def test_http_errors_are_mapped_without_echoing_secrets(self):
        for provider_code, app_code in (
            ("insufficient_quota", "quota"), ("project_spend_limit_exceeded", "quota"),
            ("rate_limit_exceeded", "rate_limit"),
        ):
            def rejected(request, *, timeout):
                details = io.BytesIO(json.dumps({"error": {"code": provider_code, "message": TEST_KEY}}).encode())
                raise HTTPError(request.full_url, 429, TEST_KEY, {}, details)

            with self.subTest(provider_code=provider_code), self.assertRaises(AIError) as error:
                self.respond(transport=rejected)
            self.assertEqual(error.exception.code, app_code)
            self.assertNotIn(TEST_KEY, str(error.exception))
        summary = self.ledger.summary()
        self.assertEqual((summary.requests, summary.total_tokens, summary.unconfirmed_requests), (3, 0, 0))

    def test_timeout_keeps_conservative_reservation(self):
        def lost_response(request, *, timeout):
            raise URLError(TimeoutError(TEST_KEY))

        settings = replace(self.settings, daily_token_limit=1200)
        with self.assertRaises(AIError) as error:
            self.respond(transport=lost_response, settings=settings)
        self.assertEqual(error.exception.code, "timeout")
        self.assertNotIn(TEST_KEY, str(error.exception))
        self.assertEqual(self.ledger.summary().unconfirmed_requests, 1)
        with self.assertRaises(AIError) as blocked:
            self.respond(settings=settings)
        self.assertEqual(blocked.exception.code, "token_limit")

    def test_unpriced_model_keeps_token_counts_and_disables_usd_estimate(self):
        self.respond(settings=replace(self.settings, model="custom-model"))
        summary = self.ledger.summary()
        self.assertEqual(summary.total_tokens, 110)
        self.assertIsNone(summary.estimated_cost_usd)
        with self.assertRaises(AIError) as error:
            self.respond(settings=replace(self.settings, daily_budget_usd=1))
        self.assertEqual(error.exception.code, "budget_usage_unknown")

    def test_incomplete_response_text_is_marked_and_usage_is_retained(self):
        result = self.respond(transport=lambda *args, **kwargs: self.response_stream(status="incomplete"))
        self.assertEqual((result.status, result.text), ("incomplete", "확인했어요."))
        with self.assertRaises(AIError) as error:
            self.respond(transport=lambda *args, **kwargs: self.response_stream(output=[], status="incomplete"))
        self.assertEqual(error.exception.code, "response_incomplete")
        self.assertEqual(self.ledger.summary().total_tokens, 220)

    def test_gpt61_cache_write_and_long_context_cost_estimate(self):
        usage = {"input_tokens": 300_000, "output_tokens": 1_000, "total_tokens": 301_000,
                 "input_tokens_details": {"cached_tokens": 50_000, "cache_write_tokens": 100_000}}
        self.respond(settings=replace(self.settings, model="gpt-6.1-sol"),
                     transport=lambda *args, **kwargs: self.response_stream(usage=usage))
        self.assertAlmostEqual(self.ledger.summary().estimated_cost_usd, 1.125)
