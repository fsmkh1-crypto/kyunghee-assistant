from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import asdict, dataclass, fields
import json
import math
import os
from pathlib import Path
import re
import tempfile
from threading import RLock


@dataclass(frozen=True)
class ModelPrice:
    input_per_million: float
    cached_input_per_million: float
    output_per_million: float
    cache_write_multiplier: float = 1.0
    long_context_after: int | None = None


DEFAULT_MODEL = "gpt-5.4-mini"
DEFAULT_WEATHER_LOCATION = "세종시"
MODELS = (DEFAULT_MODEL, "gpt-5.6-luna", "gpt-6.1-sol")
# Standard Responses text prices in USD from the official model pages.
_MINI_PRICE = ModelPrice(0.75, 0.075, 4.50)
MODEL_PRICES = {
    DEFAULT_MODEL: _MINI_PRICE,
    "gpt-5.4-mini-2026-03-17": _MINI_PRICE,
    "gpt-5.6-luna": ModelPrice(0.20, 0.02, 1.20, 1.25, 272_000),
    "gpt-6.1-sol": ModelPrice(2.00, 0.10, 10.00, 1.25, 272_000),
}
_MODEL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,199}")
_KEY_VALUE = re.compile(r"[!-~]{1,1024}")


class SettingsError(ValueError):
    pass


@dataclass(frozen=True)
class AISettings:
    model: str = DEFAULT_MODEL
    enabled: bool = False
    daily_request_limit: int | None = None
    daily_token_limit: int | None = None
    proactive_enabled: bool = False
    memory_enabled: bool = False
    daily_budget_usd: float | None = None
    weather_location: str = DEFAULT_WEATHER_LOCATION

    def validate(self) -> None:
        if not isinstance(self.model, str) or not _MODEL_ID.fullmatch(self.model) or self.model.startswith("sk-"):
            raise SettingsError("OpenAI 모델 ID를 확인해 주세요.")
        if not all(type(value) is bool for value in (self.enabled, self.proactive_enabled, self.memory_enabled)):
            raise SettingsError("AI 기능의 사용 여부를 다시 설정해 주세요.")
        location = self.weather_location
        if not isinstance(location, str) or not 2 <= len(location.strip()) <= 80 or not location.isprintable():
            raise SettingsError("기본 날씨 지역은 2~80자의 한 줄로 입력해 주세요.")
        if self.daily_request_limit is not None and (
            type(self.daily_request_limit) is not int or not 1 <= self.daily_request_limit <= 10_000
        ):
            raise SettingsError("하루 요청 한도는 1~10,000회로 설정해 주세요.")
        if self.daily_token_limit is not None and (
            type(self.daily_token_limit) is not int or not 16 <= self.daily_token_limit <= 10_000_000
        ):
            raise SettingsError("하루 토큰 한도는 16~10,000,000으로 설정해 주세요.")
        budget = self.daily_budget_usd
        if budget is not None:
            if type(budget) not in (int, float) or not 0.000001 <= budget <= 10_000 or not math.isfinite(budget):
                raise SettingsError("하루 추정 비용 한도는 0.000001~10,000달러로 설정해 주세요.")
            if self.model not in MODEL_PRICES:
                raise SettingsError("추정 비용 한도는 요금 정보가 있는 모델에서 설정할 수 있어요.")


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as temp:
            temp_path = Path(temp.name)
            temp.write(data)
            temp.flush()
            os.fsync(temp.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


class ConfigStore:
    def __init__(self, data_dir: Path):
        self.path = Path(data_dir) / "ai_settings.json"

    def load(self) -> AISettings:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return AISettings()
        except (OSError, UnicodeError, ValueError):
            raise SettingsError("AI 설정 파일을 읽을 수 없어요.") from None
        if not isinstance(raw, dict):
            raise SettingsError("AI 설정 파일의 형식이 올바르지 않아요.")
        settings = AISettings(**{field.name: raw[field.name] for field in fields(AISettings) if field.name in raw})
        settings.validate()
        return settings

    def save(self, settings: AISettings) -> None:
        settings.validate()
        try:
            _atomic_write(self.path, json.dumps(asdict(settings), ensure_ascii=False, indent=2).encode("utf-8"))
        except OSError:
            raise SettingsError("AI 설정을 저장할 수 없어요.") from None


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.c_void_p)]


def _dpapi(data: bytes, *, protect: bool) -> bytes:
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    operation = crypt.CryptProtectData if protect else crypt.CryptUnprotectData
    operation.argtypes = (
        ctypes.POINTER(_DataBlob), ctypes.c_void_p, ctypes.c_void_p,
        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_DataBlob),
    )
    operation.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = (ctypes.c_void_p,)
    kernel.LocalFree.restype = ctypes.c_void_p
    buffer = ctypes.create_string_buffer(data)
    source = _DataBlob(len(data), ctypes.addressof(buffer))
    output = _DataBlob()
    try:
        # CRYPTPROTECT_UI_FORBIDDEN; the default scope is the current Windows user.
        if not operation(ctypes.byref(source), None, None, None, None, 0x01, ctypes.byref(output)):
            raise ctypes.WinError(ctypes.get_last_error())
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        ctypes.memset(buffer, 0, len(buffer))
        if output.pbData:
            if not protect:
                ctypes.memset(output.pbData, 0, output.cbData)
            kernel.LocalFree(output.pbData)


def validate_api_key(value: str) -> str:
    key = value.strip() if isinstance(value, str) else ""
    if not _KEY_VALUE.fullmatch(key):
        raise SettingsError("OpenAI API 키를 확인해 주세요.")
    return key


class KeyVault:
    """Persist only a DPAPI blob on Windows. Other platforms retain the key in this instance."""

    def __init__(self, data_dir: Path):
        self.path = Path(data_dir) / "openai_key.dpapi"
        self.persistent = os.name == "nt"
        self._session_key: str | None = None
        self._lock = RLock()

    def get(self) -> str | None:
        with self._lock:
            if not self.persistent:
                return self._session_key
            try:
                encrypted = self.path.read_bytes()
            except FileNotFoundError:
                return None
            except OSError:
                raise SettingsError("저장된 OpenAI API 키 파일을 읽을 수 없어요.") from None
            try:
                return validate_api_key(_dpapi(encrypted, protect=False).decode("ascii"))
            except (OSError, UnicodeError, SettingsError):
                raise SettingsError("이 Windows 계정에서 저장된 API 키를 열 수 없어요. 키를 다시 입력해 주세요.") from None

    def set(self, value: str) -> None:
        key = validate_api_key(value)
        with self._lock:
            if not self.persistent:
                self._session_key = key
                return
            try:
                encrypted = _dpapi(key.encode("ascii"), protect=True)
                _atomic_write(self.path, encrypted)
            except OSError:
                raise SettingsError("Windows에서 OpenAI API 키를 보호해 저장할 수 없어요.") from None

    def delete(self) -> None:
        with self._lock:
            if self.persistent:
                try:
                    self.path.unlink(missing_ok=True)
                except OSError:
                    raise SettingsError("저장된 OpenAI API 키를 삭제할 수 없어요.") from None
            self._session_key = None
