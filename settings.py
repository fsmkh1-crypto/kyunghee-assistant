from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import time as dt_time
import json
import os
from pathlib import Path
import sys


@dataclass(frozen=True)
class WorkdayPolicy:
    usual_start: dt_time = dt_time(8, 40)
    wind_down: dt_time = dt_time(17, 0)
    leave_mode: dt_time = dt_time(17, 30)
    strong_leave: dt_time = dt_time(18, 0)
    late_leave: dt_time = dt_time(18, 30)
    hard_active_limit_sec: int = 9 * 60 * 60


WORKDAY = WorkdayPolicy()


def parse_clock(value: str) -> dt_time:
    parts = value.strip().split(":")
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        raise ValueError("시간은 HH:MM 형식으로 입력해 주세요.")
    hour, minute = map(int, parts)
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise ValueError("시간은 00:00부터 23:59 사이여야 합니다.")
    return dt_time(hour, minute)


@dataclass(frozen=True)
class UserSettings:
    schema_version: int = 1
    start_with_windows: bool = False
    always_on_top: bool = False
    break_reminders: bool = True
    workday_reminders: bool = True
    wind_down: str = "17:00"
    leave_mode: str = "17:30"
    strong_leave: str = "18:00"
    late_leave: str = "18:30"

    def workday_policy(self) -> WorkdayPolicy:
        times = [
            parse_clock(self.wind_down),
            parse_clock(self.leave_mode),
            parse_clock(self.strong_leave),
            parse_clock(self.late_leave),
        ]
        if times != sorted(times):
            raise ValueError("퇴근 알림 시간은 앞 단계부터 순서대로 설정해 주세요.")
        return WorkdayPolicy(
            wind_down=times[0],
            leave_mode=times[1],
            strong_leave=times[2],
            late_leave=times[3],
        )


def _coerce_bool(value: object, default: bool) -> bool:
    return value if isinstance(value, bool) else default


def settings_from_dict(raw: object) -> UserSettings:
    if not isinstance(raw, dict):
        return UserSettings()
    defaults = UserSettings()
    result = UserSettings(
        start_with_windows=_coerce_bool(raw.get("start_with_windows"), defaults.start_with_windows),
        always_on_top=_coerce_bool(raw.get("always_on_top"), defaults.always_on_top),
        break_reminders=_coerce_bool(raw.get("break_reminders"), defaults.break_reminders),
        workday_reminders=_coerce_bool(raw.get("workday_reminders"), defaults.workday_reminders),
        wind_down=str(raw.get("wind_down", defaults.wind_down)),
        leave_mode=str(raw.get("leave_mode", defaults.leave_mode)),
        strong_leave=str(raw.get("strong_leave", defaults.strong_leave)),
        late_leave=str(raw.get("late_leave", defaults.late_leave)),
    )
    try:
        result.workday_policy()
    except ValueError:
        return defaults
    return result


def load_user_settings(path: Path) -> UserSettings:
    if not path.is_file():
        return UserSettings()
    try:
        return settings_from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return UserSettings()


def save_user_settings(path: Path, settings: UserSettings) -> None:
    settings.workday_policy()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        temp.write_text(
            json.dumps(asdict(settings), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temp, path)
    finally:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass


def startup_command() -> str:
    executable = Path(sys.executable)
    if getattr(sys, "frozen", False):
        return f'"{executable}"'
    pythonw = executable.with_name("pythonw.exe")
    launcher = pythonw if pythonw.is_file() else executable
    script = Path(__file__).resolve().parent / "desktop_app.py"
    return f'"{launcher}" "{script}"'


def set_windows_startup(enabled: bool) -> None:
    if os.name != "nt":
        raise OSError("Windows에서만 자동 시작을 설정할 수 있습니다.")
    import winreg

    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, "KyungheeTimer", 0, winreg.REG_SZ, startup_command())
        else:
            try:
                winreg.DeleteValue(key, "KyungheeTimer")
            except FileNotFoundError:
                pass
