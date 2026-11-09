from dataclasses import replace
import io
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from assistant_ai.api import ResponsesClient, UsageLedger, WEB_SEARCH_TOOL
from assistant_ai.config import AISettings, ConfigStore, DEFAULT_MODEL, MODELS


NEW_MODELS = (
    "gpt-6-luna", "gpt-6.1-terra", "gpt-6-sol", "gpt-6-astra", "gpt-5.4", "gpt-5.5",
)


class ModelSelectionTests(unittest.TestCase):
    def test_nine_choices_keep_default_and_saved_custom_selections(self):
        self.assertEqual(len(MODELS), 9)
        self.assertEqual(len(set(MODELS)), 9)
        self.assertEqual(MODELS[0], DEFAULT_MODEL)
        self.assertEqual(AISettings().model, "gpt-5.4-mini")
        with TemporaryDirectory() as directory:
            store = ConfigStore(Path(directory))
            for model in (*MODELS, "ft:gpt-5.4-mini:team:assistant:1234", "custom-model"):
                with self.subTest(model=model):
                    settings = AISettings(model=model, enabled=True)
                    if model in MODELS:
                        settings = replace(settings, daily_budget_usd=0.50)
                    store.save(settings)
                    self.assertEqual(store.load(), settings)

    @unittest.skipUnless(os.name == "nt" or os.environ.get("DISPLAY"), "Tk display required")
    def test_help_changes_with_model_and_does_not_claim_custom_pricing(self):
        from assistant_ai.ui_settings import _SettingsWindow

        class Variable:
            def __init__(self, value=""):
                self.value = value

            def get(self):
                return self.value

            def set(self, value):
                self.value = value

        window = SimpleNamespace(model=Variable("gpt-6-astra"), price=Variable())
        _SettingsWindow._update_price(window)
        self.assertIn("빠른 응답용 low 추론", window.price.get())
        self.assertIn("입력 $10", window.price.get())
        self.assertIn("캐시 쓰기 $12.5", window.price.get())
        self.assertIn("272,000토큰 초과", window.price.get())
        window.model.set("gpt-6.1-sol")
        _SettingsWindow._update_price(window)
        self.assertIn("API 기본 추론", window.price.get())
        self.assertNotIn("low 추론", window.price.get())
        window.model.set("custom-model")
        _SettingsWindow._update_price(window)
        self.assertIn("비용을 추정할 수 없어요", window.price.get())
        self.assertNotIn("$", window.price.get())
        self.assertNotIn("low 추론", window.price.get())


class ModelRequestTests(unittest.TestCase):
    def setUp(self):
        self.path = Path(self.enterContext(TemporaryDirectory()))

    @staticmethod
    def response(usage):
        return io.BytesIO(json.dumps({
            "id": "resp_fake", "status": "completed", "usage": usage,
            "output": [{"type": "message", "content": [{"type": "output_text", "text": "확인했어요."}]}],
        }).encode())

    def test_choices_support_existing_tool_payload_and_preserve_old_reasoning_defaults(self):
        tool = {"type": "function", "name": "get_timer_state", "parameters": {"type": "object"}}
        for model in (*MODELS, "custom-model", "gpt-5.5-2026-04-23"):
            with self.subTest(model=model):
                requests = []

                def transport(request, *, timeout):
                    requests.append(json.loads(request.data))
                    self.assertEqual(timeout, 30)
                    return self.response({"input_tokens": 100, "output_tokens": 10, "total_tokens": 110})

                client = ResponsesClient("fake-model-test-key", UsageLedger(self.path / model), transport=transport)
                result = client.respond(
                    AISettings(model=model, enabled=True), [{"role": "user", "content": "날씨와 타이머"}],
                    instructions="짧은 대화", tools=(tool, WEB_SEARCH_TOOL), max_output_tokens=1024,
                )
                payload = requests[0]
                self.assertEqual(result.text, "확인했어요.")
                self.assertEqual(payload["model"], model)
                self.assertEqual(payload["tools"], [tool, WEB_SEARCH_TOOL])
                self.assertFalse(payload["parallel_tool_calls"])
                self.assertEqual(payload["max_output_tokens"], 1024)
                self.assertEqual(payload["service_tier"], "default")
                self.assertIn("reasoning.encrypted_content", payload["include"])
                self.assertNotIn("temperature", payload)
                self.assertNotIn("prompt_cache_retention", payload)
                if model in (*NEW_MODELS, "gpt-5.6-luna"):
                    self.assertEqual(payload["reasoning"], {"effort": "low"})
                else:
                    self.assertNotIn("reasoning", payload)

    def test_new_model_actual_costs_at_long_context_boundary_include_cache_reads_and_writes(self):
        # Expected USD totals calculated from official standard prices for the
        # complete billed request, not just the tokens above the threshold.
        cases = {
            "gpt-6-luna": (0.0284, 0.0565502),
            "gpt-6.1-terra": (0.283, 0.563502),
            "gpt-6-sol": (0.568, 1.131004),
            "gpt-6-astra": (2.84, 5.65502),
            "gpt-5.4": (0.65, 1.292505),
            "gpt-5.5": (1.3, 2.58501),
        }
        for model, expected_costs in cases.items():
            for input_tokens, expected in zip((272_000, 272_001), expected_costs):
                with self.subTest(model=model, input_tokens=input_tokens):
                    usage = {
                        "input_tokens": input_tokens, "output_tokens": 1_000, "total_tokens": input_tokens + 1_000,
                        "input_tokens_details": {"cached_tokens": 20_000, "cache_write_tokens": 100_000},
                    }
                    ledger = UsageLedger(self.path / model / str(input_tokens))
                    client = ResponsesClient("fake-model-test-key", ledger,
                                             transport=lambda *_args, **_kwargs: self.response(usage))
                    client.respond(AISettings(model=model, enabled=True), [], instructions="비용 검증")
                    summary = ledger.summary()
                    self.assertEqual(summary.confirmed_requests, 1)
                    self.assertEqual(summary.total_tokens, input_tokens + 1_000)
                    self.assertAlmostEqual(summary.estimated_cost_usd, expected, places=9)

    def test_new_model_budget_reservation_limits_generation_before_transport(self):
        for model in NEW_MODELS:
            with self.subTest(model=model):
                ledger = UsageLedger(self.path / model)
                settings = AISettings(model=model, enabled=True, daily_budget_usd=0.05)

                def transport(request, *, timeout):
                    pending = ledger.summary(settings)
                    self.assertEqual(pending.pending_requests, 1)
                    self.assertGreater(pending.reserved_cost_usd, 0)
                    self.assertLessEqual(pending.reserved_cost_usd, 0.05)
                    self.assertGreaterEqual(json.loads(request.data)["max_output_tokens"], 16)
                    return self.response({"input_tokens": 100, "output_tokens": 10, "total_tokens": 110})

                client = ResponsesClient("fake-model-test-key", ledger, transport=transport)
                client.respond(settings, [], instructions="짧게 답하세요.")
                summary = ledger.summary(settings)
                self.assertEqual(summary.pending_requests, 0)
                self.assertGreater(summary.remaining_budget_usd, 0)


if __name__ == "__main__":
    unittest.main()
