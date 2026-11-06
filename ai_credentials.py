"""Session credentials with opt-in, current-Windows-user DPAPI persistence.

The API key never belongs in UserSettings, the app's state, or a log. The
default controller keeps it in memory. Unsupported platforms deliberately
have no persistent-storage fallback.
"""
from __future__ import annotations

import ctypes
from dataclasses import dataclass
import os
from pathlib import Path
import sys
import tempfile
from typing import Protocol


KEY_FILENAME = "openai_api_key.dpapi"
_FILE_HEADER = b"KYUNGHEE_DPAPI_V1\x00"
_MAX_KEY_BYTES = 4096
_MAX_FILE_BYTES = 64 * 1024


class SecureStorageError(Exception):
    """A deliberately content-free error; never includes key or OS details."""


class Protector(Protocol):
    @property
    def available(self) -> bool: ...

    def protect(self, plaintext: bytes) -> bytes: ...

    def unprotect(self, ciphertext: bytes) -> bytes: ...


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


class WindowsDPAPI:
    """DPAPI without CRYPTPROTECT_LOCAL_MACHINE: only the current user can decrypt."""

    @property
    def available(self) -> bool:
        return sys.platform == "win32" and os.name == "nt"

    def protect(self, plaintext: bytes) -> bytes:
        return self._crypt(plaintext, decrypt=False)

    def unprotect(self, ciphertext: bytes) -> bytes:
        return self._crypt(ciphertext, decrypt=True)

    def _crypt(self, data: bytes, *, decrypt: bool) -> bytes:
        if not self.available:
            raise SecureStorageError("unsupported_platform")
        if not data or len(data) > _MAX_FILE_BYTES:
            raise SecureStorageError("invalid_credential")

        # Loading and typing the functions here keeps imports safe on non-Windows.
        try:
            crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.LocalFree.argtypes = [ctypes.c_void_p]
            kernel32.LocalFree.restype = ctypes.c_void_p
            crypt32.CryptProtectData.argtypes = [
                ctypes.POINTER(_DataBlob), ctypes.c_wchar_p,
                ctypes.POINTER(_DataBlob), ctypes.c_void_p, ctypes.c_void_p,
                ctypes.c_uint32, ctypes.POINTER(_DataBlob),
            ]
            crypt32.CryptProtectData.restype = ctypes.c_int
            crypt32.CryptUnprotectData.argtypes = [
                ctypes.POINTER(_DataBlob), ctypes.c_void_p,
                ctypes.POINTER(_DataBlob), ctypes.c_void_p, ctypes.c_void_p,
                ctypes.c_uint32, ctypes.POINTER(_DataBlob),
            ]
            crypt32.CryptUnprotectData.restype = ctypes.c_int
        except Exception:
            raise SecureStorageError("secure_storage_unavailable") from None

        source = ctypes.create_string_buffer(data)
        incoming = _DataBlob(len(data), ctypes.cast(source, ctypes.POINTER(ctypes.c_ubyte)))
        outgoing = _DataBlob()
        try:
            # UI_FORBIDDEN prevents a blocking Windows credential prompt. No
            # machine-wide flag is used, including when the app runs elevated.
            if decrypt:
                success = crypt32.CryptUnprotectData(
                    ctypes.byref(incoming), None, None, None, None, 1, ctypes.byref(outgoing)
                )
            else:
                success = crypt32.CryptProtectData(
                    ctypes.byref(incoming), "Kyunghee OpenAI credential",
                    None, None, None, 1, ctypes.byref(outgoing),
                )
            if not success or not outgoing.pbData or not 0 < outgoing.cbData <= _MAX_FILE_BYTES:
                raise SecureStorageError("secure_storage_failed")
            return ctypes.string_at(outgoing.pbData, outgoing.cbData)
        except SecureStorageError:
            raise
        except Exception:
            raise SecureStorageError("secure_storage_failed") from None
        finally:
            if not decrypt:
                ctypes.memset(ctypes.addressof(source), 0, ctypes.sizeof(source))
            if outgoing.pbData:
                if decrypt:
                    ctypes.memset(outgoing.pbData, 0, outgoing.cbData)
                kernel32.LocalFree(ctypes.cast(outgoing.pbData, ctypes.c_void_p))


@dataclass(frozen=True)
class CredentialStatus:
    ok: bool
    code: str
    message: str
    remembered: bool = False


def normalize_api_key(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("invalid_key_format")
    candidate = value.strip()
    if len(candidate) > _MAX_KEY_BYTES or any(not "!" <= char <= "~" for char in candidate):
        raise ValueError("invalid_key_format")
    return candidate


class AICredentials:
    """The session key holder. Its representation and status never expose the key.

    ``load_saved_key`` is an explicit startup action based on ai_remember_key.
    ``configure_key`` accepts an empty field to keep an already loaded session
    key; ``clear`` is the explicit way to remove both session and saved keys.
    A custom protector is useful for isolated tests; production uses DPAPI only.
    """

    def __init__(self, data_dir: Path, *, protector: Protector | None = None):
        self.path = Path(data_dir) / KEY_FILENAME
        self._protector = protector if protector is not None else WindowsDPAPI()
        self._api_key = ""

    @property
    def api_key(self) -> str:
        return self._api_key

    @property
    def has_key(self) -> bool:
        return bool(self._api_key)

    @property
    def supports_persistence(self) -> bool:
        return self._protector.available

    def load_saved_key(self, remember: bool) -> CredentialStatus:
        if not remember:
            return self.delete_saved_key()
        if not self.supports_persistence:
            return CredentialStatus(False, "unsupported_platform", "이 환경에서는 키를 기억할 수 없습니다. 실행 중에만 사용합니다.")
        try:
            # Bound the read even when a corrupt file has an unreasonable size.
            with self.path.open("rb") as saved:
                encrypted = saved.read(_MAX_FILE_BYTES + 1)
            if len(encrypted) > _MAX_FILE_BYTES or not encrypted.startswith(_FILE_HEADER):
                raise SecureStorageError("invalid_saved_key")
            decrypted = self._protector.unprotect(encrypted[len(_FILE_HEADER):])
            candidate = normalize_api_key(decrypted.decode("utf-8"))
            if not candidate:
                raise SecureStorageError("invalid_saved_key")
            self._api_key = candidate
        except FileNotFoundError:
            return CredentialStatus(True, "missing", "기억된 키가 없습니다. 키를 입력해 주세요.")
        except Exception:
            return CredentialStatus(False, "load_failed", "기억된 키를 열 수 없습니다. 키를 다시 입력해 주세요.")
        return CredentialStatus(True, "loaded", "이 Windows 계정의 암호화된 키를 불러왔습니다.", True)

    def configure_key(self, api_key: str, remember: bool) -> CredentialStatus:
        try:
            candidate = normalize_api_key(api_key)
        except ValueError:
            return CredentialStatus(False, "invalid_key_format", "API 키에는 공백·줄바꿈 없이 키 문자열만 입력해 주세요.")
        if candidate:
            self._api_key = candidate

        if not remember:
            return self.delete_saved_key()
        if not self._api_key:
            deletion = self.delete_saved_key()
            if not deletion.ok:
                return deletion
            return CredentialStatus(False, "missing_key", "API 키를 입력해 주세요. 키는 기본적으로 실행 중에만 사용합니다.")
        if not self.supports_persistence:
            return CredentialStatus(False, "unsupported_platform", "키는 실행 중에만 사용합니다. Windows DPAPI 저장을 사용할 수 없습니다.")

        temp_path = None
        try:
            encrypted = self._protector.protect(self._api_key.encode("utf-8"))
            if not encrypted or len(encrypted) + len(_FILE_HEADER) > _MAX_FILE_BYTES:
                raise SecureStorageError("invalid_encrypted_key")
            self.path.parent.mkdir(parents=True, exist_ok=True)
            # Only encrypted bytes ever enter a file, including temporary files.
            fd, name = tempfile.mkstemp(prefix=f".{KEY_FILENAME}.", suffix=".tmp", dir=self.path.parent)
            temp_path = Path(name)
            with os.fdopen(fd, "wb") as output:
                output.write(_FILE_HEADER + encrypted)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temp_path, self.path)
        except Exception:
            # An older saved key must not silently reappear after a failed
            # replacement. It is safe to keep the newly entered session key.
            deletion = self.delete_saved_key()
            if not deletion.ok:
                return CredentialStatus(False, "save_and_delete_failed", "키는 실행 중에만 사용합니다. 기존 암호화 파일을 지우지 못했습니다. 폴더 권한을 확인해 주세요.")
            return CredentialStatus(False, "save_failed", "키 저장에 실패했습니다. 키는 이번 실행 중에만 사용합니다.")
        finally:
            if temp_path is not None:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass
        return CredentialStatus(True, "saved", "이 Windows 계정에서만 열 수 있도록 키를 암호화해 기억했습니다.", True)

    def delete_saved_key(self) -> CredentialStatus:
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            return CredentialStatus(False, "delete_failed", "암호화된 키 파일을 지우지 못했습니다. 폴더 권한을 확인해 주세요.")
        message = "키는 이번 실행 중에만 사용합니다." if self.has_key else "키를 입력해 주세요. 기본값은 실행 중에만 사용입니다."
        return CredentialStatus(True, "session_only", message)

    def clear(self) -> CredentialStatus:
        self._api_key = ""
        status = self.delete_saved_key()
        if not status.ok:
            return status
        return CredentialStatus(True, "cleared", "실행 중인 키와 기억된 키를 지웠습니다.")
