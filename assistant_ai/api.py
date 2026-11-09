from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from decimal import Decimal
from http.client import HTTPException
import json
from pathlib import Path
import sqlite3
import unicodedata
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .config import AISettings, MODEL_PRICES, ModelPrice, SettingsError, validate_api_key


RESPONSES_URL = "https://api.openai.com/v1/responses"
WEB_SEARCH_TOOL = {"type": "web_search"}
_NANOS_PER_USD = 1_000_000_000
_MAX_RESPONSE_BYTES = 8 * 1024 * 1024
_MIN_OUTPUT_TOKENS = 16
_MAX_WEB_SEARCH_CALLS = 3
_WEB_SEARCH_CALL_NANOS = 10_000_000


class AIError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cached_input_tokens: int = 0
    cache_write_tokens: int = 0
    web_search_calls: int = 0


@dataclass(frozen=True)
class WebSource:
    title: str
    url: str
    start_index: int | None = None
    end_index: int | None = None
    cited: bool = False


@dataclass(frozen=True)
class Response:
    output: list[dict]
    text: str
    usage: Usage = Usage()
    response_id: str | None = None
    status: str = "completed"
    sources: tuple[WebSource, ...] = ()
    used_web_search: bool = False
    web_search_calls: int = 0


@dataclass(frozen=True)
class UsageSummary:
    date: str
    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float | None = 0.0
    unconfirmed_requests: int = 0


def _rates(price: ModelPrice, input_tokens: int) -> tuple[int, int, int, int]:
    """Standard, cached, cache write and output rates in nanodollars per token."""
    input_rate = round(price.input_per_million * 1000)
    cached_rate = round(price.cached_input_per_million * 1000)
    output_rate = round(price.output_per_million * 1000)
    if price.long_context_after is not None and input_tokens > price.long_context_after:
        input_rate *= 2
        cached_rate *= 2
        output_rate = round(output_rate * 1.5)
    return input_rate, cached_rate, round(input_rate * price.cache_write_multiplier), output_rate


def _cost_nanos(price: ModelPrice | None, usage: Usage) -> int | None:
    tool_cost = usage.web_search_calls * _WEB_SEARCH_CALL_NANOS
    if price is None:
        return None if usage.total_tokens else tool_cost
    input_rate, cached_rate, write_rate, output_rate = _rates(price, usage.input_tokens)
    regular_tokens = usage.input_tokens - usage.cached_input_tokens - usage.cache_write_tokens
    return (
        regular_tokens * input_rate + usage.cached_input_tokens * cached_rate
        + usage.cache_write_tokens * write_rate + usage.output_tokens * output_rate + tool_cost
    )


class UsageLedger:
    """One row per API attempt. A pending row reserves allowance across threads/processes."""

    def __init__(self, data_dir: Path, *, today=date.today):
        self.path = Path(data_dir) / "ai_usage.sqlite3"
        self._today = today

    @contextmanager
    def _connection(self):
        connection = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(self.path)
            with connection:
                connection.execute("""
                    CREATE TABLE IF NOT EXISTS calls (
                        id INTEGER PRIMARY KEY,
                        day TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        model TEXT NOT NULL,
                        status TEXT NOT NULL,
                        input_tokens INTEGER NOT NULL,
                        output_tokens INTEGER NOT NULL,
                        total_tokens INTEGER NOT NULL,
                        cost_nanos INTEGER
                    )
                """)
                connection.execute("CREATE INDEX IF NOT EXISTS calls_by_day ON calls(day)")
                yield connection
        except (OSError, sqlite3.Error):
            raise AIError("usage_storage", "AI 사용량을 기록하거나 읽을 수 없어요.") from None
        finally:
            if connection is not None:
                connection.close()

    def summary(self) -> UsageSummary:
        day = self._today().isoformat()
        with self._connection() as connection:
            requests, input_tokens, output_tokens, total, cost, unpriced, unconfirmed = connection.execute("""
                SELECT COUNT(*),
                       COALESCE(SUM(CASE WHEN status = 'complete' THEN input_tokens ELSE 0 END), 0),
                       COALESCE(SUM(CASE WHEN status = 'complete' THEN output_tokens ELSE 0 END), 0),
                       COALESCE(SUM(CASE WHEN status = 'complete' THEN total_tokens ELSE 0 END), 0),
                       COALESCE(SUM(CASE WHEN status = 'complete' THEN cost_nanos ELSE 0 END), 0),
                       COUNT(*) - COUNT(cost_nanos),
                       COALESCE(SUM(CASE WHEN status IN ('pending', 'unconfirmed') THEN 1 ELSE 0 END), 0)
                FROM calls WHERE day = ?
            """, (day,)).fetchone()
        return UsageSummary(
            day, requests, input_tokens, output_tokens, total,
            None if unpriced else cost / _NANOS_PER_USD, unconfirmed,
        )

    def _reserve(
        self, settings: AISettings, estimated_input: int, output_cap: int | None, *, web_search: bool = False,
    ) -> tuple[int, int | None, int]:
        day = self._today().isoformat()
        price = MODEL_PRICES.get(settings.model)
        search_limit = _MAX_WEB_SEARCH_CALLS if web_search else 0
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            requests, tokens, cost, unpriced = connection.execute("""
                SELECT COUNT(*), COALESCE(SUM(total_tokens), 0), COALESCE(SUM(cost_nanos), 0),
                       COUNT(*) - COUNT(cost_nanos)
                FROM calls WHERE day = ?
            """, (day,)).fetchone()
            if settings.daily_request_limit is not None and requests >= settings.daily_request_limit:
                raise AIError("request_limit", "오늘 설정한 AI 요청 횟수 한도에 도달했어요.")

            if settings.daily_token_limit is not None:
                remaining = settings.daily_token_limit - tokens - estimated_input
                if remaining < _MIN_OUTPUT_TOKENS:
                    raise AIError("token_limit", "이 요청을 보내기에는 오늘 남은 AI 토큰이 부족해요.")
                output_cap = min(output_cap if output_cap is not None else 32_768, remaining)

            reserved_rate = _rates(price, estimated_input) if price is not None else None
            if settings.daily_budget_usd is not None:
                if unpriced or reserved_rate is None:
                    raise AIError("budget_usage_unknown", "오늘 요금을 알 수 없는 사용량이 있어 비용 한도를 적용할 수 없어요.")
                budget = int(Decimal(str(settings.daily_budget_usd)) * _NANOS_PER_USD)
                remaining_cost = budget - cost - estimated_input * reserved_rate[2]
                if web_search:
                    search_limit = min(search_limit, (remaining_cost - _MIN_OUTPUT_TOKENS * reserved_rate[3])
                                       // _WEB_SEARCH_CALL_NANOS)
                    if search_limit < 1:
                        raise AIError("web_search_budget_limit", "오늘 남은 AI 추정 비용으로는 웹을 검색할 수 없어요.")
                    remaining_cost -= search_limit * _WEB_SEARCH_CALL_NANOS
                affordable = remaining_cost // reserved_rate[3]
                if affordable < _MIN_OUTPUT_TOKENS:
                    raise AIError("budget_limit", "이 요청을 보내기에는 오늘 남은 AI 추정 비용 한도가 부족해요.")
                output_cap = min(output_cap if output_cap is not None else 32_768, affordable)

            # With no configured output limit the API chooses its own generation limit.
            # A local estimate still protects today's allowance if a call loses its response.
            reserved_output = output_cap if output_cap is not None else 2048
            reserved_cost = None
            if reserved_rate is not None:
                reserved_cost = (estimated_input * reserved_rate[2] + reserved_output * reserved_rate[3]
                                 + search_limit * _WEB_SEARCH_CALL_NANOS)
            row = connection.execute("""
                INSERT INTO calls(day, created_at, model, status, input_tokens, output_tokens, total_tokens, cost_nanos)
                VALUES (?, ?, ?, 'pending', ?, ?, ?, ?)
            """, (
                day, datetime.now(timezone.utc).isoformat(), settings.model,
                estimated_input, reserved_output, estimated_input + reserved_output, reserved_cost,
            ))
            return row.lastrowid, output_cap, search_limit

    def _finish(self, call_id: int, model: str, usage: Usage | None, *, failed: bool = False) -> None:
        with self._connection() as connection:
            if usage is None:
                connection.execute("UPDATE calls SET status = 'unconfirmed' WHERE id = ?", (call_id,))
                return
            connection.execute("""
                UPDATE calls SET status = ?, input_tokens = ?, output_tokens = ?, total_tokens = ?, cost_nanos = ?
                WHERE id = ?
            """, (
                "failed" if failed else "complete", usage.input_tokens, usage.output_tokens, usage.total_tokens,
                _cost_nanos(MODEL_PRICES.get(model), usage), call_id,
            ))


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_open_responses = build_opener(_NoRedirect()).open


def _error_response(error: HTTPError, *, web_search: bool = False) -> AIError:
    details = {}
    with error:
        try:
            body = json.loads(error.read(65_536)) if error.fp is not None else None
            if isinstance(body, dict) and isinstance(body.get("error"), dict):
                details = body["error"]
        except (OSError, ValueError, RecursionError, HTTPException):
            pass
    code = details.get("code")
    if error.code == 401:
        return AIError("authentication", "OpenAI API 키를 확인해 주세요. 인증에 실패했어요.")
    if code == "model_not_found" or error.code == 404:
        return AIError("model_unavailable", "선택한 모델을 찾을 수 없거나 이 API 키로 사용할 수 없어요.")
    if error.code == 403:
        return AIError("permission", "이 API 키의 프로젝트 또는 모델 사용 권한을 확인해 주세요.")
    if code in (
        "insufficient_quota", "billing_hard_limit_reached", "credit_balance_exhausted",
        "organization_spend_limit_exceeded", "project_spend_limit_exceeded", "organization_usage_limit_exceeded",
    ):
        return AIError("quota", "OpenAI API 프로젝트의 결제 상태와 사용 한도를 확인해 주세요.")
    if error.code == 429:
        return AIError("rate_limit", "OpenAI의 요청 한도에 걸렸어요. 잠시 후 다시 시도해 주세요.")
    if code == "context_length_exceeded":
        return AIError("context_limit", "선택한 모델에 보낼 수 있는 대화 길이를 넘었어요.")
    if error.code in (400, 422):
        message = details.get("message")
        if web_search and isinstance(message, str):
            message = message.lower()
            if "web_search" in message and any(phrase in message for phrase in (
                "not supported", "unsupported", "does not support", "not available",
            )):
                return AIError("web_search_unsupported", "선택한 모델 또는 API 프로젝트에서 웹 검색을 사용할 수 없어요.")
        return AIError("request_invalid", "OpenAI가 요청을 받지 못했어요. 모델 ID와 지원 기능을 확인해 주세요.")
    if error.code >= 500:
        return AIError("service_unavailable", "OpenAI API가 일시적으로 응답하지 못했어요. 잠시 후 다시 시도해 주세요.")
    return AIError("http_error", "OpenAI API 요청을 완료하지 못했어요.")


def _read_usage(raw: object, web_search_calls: int = 0) -> Usage | None:
    if not isinstance(raw, dict):
        return None
    input_tokens = raw.get("input_tokens")
    output_tokens = raw.get("output_tokens")
    if any(type(value) is not int or not 0 <= value <= 100_000_000 for value in (input_tokens, output_tokens)):
        return None
    details = raw.get("input_tokens_details")
    if not isinstance(details, dict):
        details = {}
    cached = details.get("cached_tokens", 0)
    written = details.get("cache_write_tokens", 0)
    cached = cached if type(cached) is int and 0 <= cached <= input_tokens else 0
    written = written if type(written) is int and 0 <= written <= input_tokens - cached else 0
    total = raw.get("total_tokens")
    if type(total) is not int or not input_tokens + output_tokens <= total <= 200_000_000:
        total = input_tokens + output_tokens
    return Usage(input_tokens, output_tokens, total, cached, written, web_search_calls)


def _web_source(data: dict, *, offset: int | None = None, length: int = 0) -> WebSource | None:
    url = data.get("url")
    if not isinstance(url, str) or not 1 <= len(url) <= 4096 or "\\" in url:
        return None
    if any(character.isspace() or unicodedata.category(character).startswith("C") for character in url):
        return None
    try:
        parsed = urlsplit(url)
        host = parsed.hostname
        port = parsed.port
    except ValueError:
        return None
    if (parsed.scheme not in {"http", "https"} or not host or parsed.username is not None
            or parsed.password is not None or port == 0):
        return None
    raw_title = data.get("title")
    title = ""
    if isinstance(raw_title, str):
        safe_title = "".join(c for c in raw_title[:512] if not unicodedata.category(c).startswith("C") or c.isspace())
        title = " ".join(safe_title.split())[:160]
    start, end = data.get("start_index"), data.get("end_index")
    if offset is not None and type(start) is int and type(end) is int and 0 <= start < end <= length:
        return WebSource(title or host, url, offset + start, offset + end, True)
    return WebSource(title or host, url, cited=offset is not None)


def _response_content(output: list[dict]) -> tuple[str, tuple[WebSource, ...]]:
    text = []
    refusals = []
    citations = []
    offset = 0
    for item in output:
        content = item.get("content")
        if item.get("type") != "message" or not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "output_text" and isinstance(part.get("text"), str):
                fragment = part["text"]
                text.append(fragment)
                annotations = part.get("annotations")
                if isinstance(annotations, list):
                    for annotation in annotations:
                        if isinstance(annotation, dict) and annotation.get("type") == "url_citation":
                            source = _web_source(annotation, offset=offset, length=len(fragment))
                            if source is not None:
                                citations.append(source)
                offset += len(fragment) + 1  # Account for the newline between text fragments.
            if part.get("type") == "refusal" and isinstance(part.get("refusal"), str):
                refusals.append(part["refusal"])
    joined = "\n".join(text or refusals)
    stripped = joined.strip()
    leading = len(joined) - len(joined.lstrip())
    return stripped, tuple(_trimmed_source(source, leading, len(stripped)) for source in citations)


def _trimmed_source(source: WebSource, leading: int, length: int) -> WebSource:
    if source.start_index is None or source.end_index is None:
        return source
    start = max(0, source.start_index - leading)
    end = min(length, source.end_index - leading)
    if start < end:
        return replace(source, start_index=start, end_index=end)
    return replace(source, start_index=None, end_index=None)


def _search_results(output: list[dict]) -> tuple[int, tuple[WebSource, ...]]:
    searches = 0
    sources = []
    for item in output:
        if item.get("type") != "web_search_call" or item.get("status") != "completed":
            continue
        action = item.get("action")
        if not isinstance(action, dict):
            searches += 1
            continue
        if action.get("type") != "search":
            continue  # Opening a page and searching within it are not billable searches.
        searches += 1
        retrieved = action.get("sources")
        if isinstance(retrieved, list):
            for data in retrieved:
                if isinstance(data, dict) and data.get("type", "url") == "url":
                    source = _web_source(data)
                    if source is not None:
                        sources.append(source)
    return searches, tuple(sources)


def _merge_sources(citations: tuple[WebSource, ...], retrieved: tuple[WebSource, ...]) -> tuple[WebSource, ...]:
    # Keep repeat annotations because the same URL can support multiple passages.
    merged = list(citations)
    seen = {source.url for source in citations}
    for source in retrieved:
        if source.url not in seen:
            merged.append(source)
            seen.add(source.url)
    return tuple(merged)


def _billed_searches(result: dict, observed: int) -> int:
    tool_usage = result.get("tool_usage")
    web_usage = tool_usage.get("web_search") if isinstance(tool_usage, dict) else None
    count = web_usage.get("num_requests") if isinstance(web_usage, dict) else None
    return count if type(count) is int and 0 <= count <= 100_000 else observed


class ResponsesClient:
    def __init__(self, api_key: str, usage_ledger: UsageLedger, *, timeout: float = 30.0, transport=None):
        self._api_key = api_key
        self.usage_ledger = usage_ledger
        self.timeout = timeout
        self._open = transport if transport is not None else _open_responses

    def respond(
        self, settings: AISettings, input_items: list[dict], *, instructions: str,
        tools=(), max_output_tokens: int | None = None, force_web_search: bool = False,
        tool_choice: str | dict | None = None,
    ) -> Response:
        settings.validate()
        if not settings.enabled:
            raise AIError("disabled", "설정에서 AI 대화를 켜 주세요.")
        if not self._api_key:
            raise AIError("missing_key", "설정에서 OpenAI API 키를 입력해 주세요.")
        try:
            api_key = validate_api_key(self._api_key)
        except SettingsError:
            raise AIError("authentication", "OpenAI API 키 형식을 확인해 주세요.") from None
        if max_output_tokens is not None and (
            type(max_output_tokens) is not int or max_output_tokens < _MIN_OUTPUT_TOKENS
        ):
            raise AIError("request_invalid", "AI 응답 토큰 설정을 확인해 주세요.")

        payload = {
            "model": settings.model, "input": input_items, "instructions": instructions,
            "store": False, "service_tier": "default", "include": ["reasoning.encrypted_content"],
        }
        tool_list = list(tools)
        web_search = any(tool.get("type") == "web_search" for tool in tool_list)
        if force_web_search:
            if not web_search or tool_choice is not None:
                raise AIError("request_invalid", "웹 검색 도구 설정을 확인해 주세요.")
            tool_choice = {"type": "web_search"}
        if tool_choice is not None:
            payload["tool_choice"] = tool_choice
        if tool_list:
            payload["tools"] = tool_list
            payload["parallel_tool_calls"] = False
        if web_search:
            payload["include"].append("web_search_call.action.sources")
            payload["max_tool_calls"] = _MAX_WEB_SEARCH_CALLS
        if settings.model == "gpt-5.6-luna":
            payload["reasoning"] = {"effort": "low"}
        try:
            body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        except (TypeError, ValueError, UnicodeError):
            raise AIError("request_invalid", "AI 요청에 보낼 데이터를 처리하지 못했어요.") from None
        # Conservative local estimate for text JSON, with room for server-side framing.
        estimated_input = len(body) + 256 + 16 * (len(input_items) + len(payload.get("tools", ())))
        call_id, output_cap, search_limit = self.usage_ledger._reserve(
            settings, estimated_input, max_output_tokens, web_search=web_search,
        )
        if web_search:
            payload["max_tool_calls"] = search_limit
        if output_cap is not None:
            payload["max_output_tokens"] = output_cap
        if output_cap is not None or web_search:
            body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        request = Request(RESPONSES_URL, method="POST", data=body, headers={
            "Authorization": f"Bearer {api_key}", "Content-Type": "application/json", "Accept": "application/json",
        })

        try:
            with self._open(request, timeout=self.timeout) as stream:
                raw = stream.read(_MAX_RESPONSE_BYTES + 1)
        except HTTPError as error:
            mapped_error = _error_response(error, web_search=web_search)
            # A rejected 4xx request counts toward request limits, with no reported usage.
            usage = Usage() if 400 <= error.code < 500 and error.code != 408 else None
            self.usage_ledger._finish(call_id, settings.model, usage, failed=True)
            raise mapped_error from None
        except (OSError, HTTPException) as error:
            self.usage_ledger._finish(call_id, settings.model, None)
            reason = error.reason if isinstance(error, URLError) else error
            if isinstance(reason, TimeoutError):
                raise AIError("timeout", "OpenAI 응답을 기다리는 시간이 길어졌어요. 잠시 후 다시 시도해 주세요.") from None
            raise AIError("network", "OpenAI에 연결할 수 없어요. 인터넷 연결을 확인해 주세요.") from None

        try:
            result = json.loads(raw) if len(raw) <= _MAX_RESPONSE_BYTES else None
        except (ValueError, RecursionError):
            result = None
        output = result.get("output") if isinstance(result, dict) else None
        valid_output = isinstance(output, list) and all(isinstance(item, dict) for item in output)
        searches, retrieved = _search_results(output) if web_search and valid_output else (0, ())
        billed = _billed_searches(result, searches) if web_search and isinstance(result, dict) else 0
        usage = _read_usage(result.get("usage"), billed) if isinstance(result, dict) else None
        self.usage_ledger._finish(call_id, settings.model, usage)
        if not isinstance(result, dict):
            raise AIError("response_invalid", "OpenAI에서 읽을 수 없는 응답을 받았어요.")
        status = result.get("status", "completed")
        if status not in ("completed", "incomplete") or result.get("error"):
            raise AIError("response_failed", "OpenAI가 이번 답변을 완료하지 못했어요.")
        if not valid_output:
            raise AIError("response_invalid", "OpenAI 응답에 대화 결과가 없어요.")
        text, citations = _response_content(output)
        if status == "incomplete" and not text:
            raise AIError("response_incomplete", "OpenAI가 이번 답변을 끝내지 못했어요. 설정된 토큰 한도를 확인해 주세요.")
        response_id = result.get("id")
        return Response(
            output, text, usage or Usage(), response_id if isinstance(response_id, str) else None, status,
            _merge_sources(citations, retrieved) if web_search else (), bool(searches), billed,
        )
