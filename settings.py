from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import time as dt_time
import json
import os
from pathlib import Path
import re
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
HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


def parse_clock(value: str) -> dt_time:
    parts = value.strip().split(":")
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        raise ValueError("시간은 HH:MM 형식으로 입력해 주세요.")
    hour, minute = map(int, parts)
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise ValueError("시간은 00:00부터 23:59 사이여야 합니다.")
    return dt_time(hour, minute)


def validate_hex_color(value: str) -> str:
    value = value.strip().upper()
    if not HEX_COLOR_RE.fullmatch(value):
        raise ValueError("글자 색상은 #RRGGBB 형식으로 입력해 주세요.")
    return value


def _coerce_bool(value: object, default: bool) -> bool:
    return value if isinstance(value, bool) else default


def _bounded_int(value: object, default: int, low: int, high: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if low <= parsed <= high else default


def _position_int(value: object, default: int = -1) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _fit_mode(value: object) -> str:
    return str(value) if str(value) in {"fit", "crop"} else "fit"


def _color_or(value: object, default: str) -> str:
    try:
        return validate_hex_color(str(value))
    except ValueError:
        return default


def _clock_or(value: object, default: str) -> str:
    candidate = str(value)
    try:
        parse_clock(candidate)
    except ValueError:
        return default
    return candidate


@dataclass(frozen=True)
class UserSettings:
    schema_version: int = 4
    start_with_windows: bool = False
    always_on_top: bool = False
    break_reminders: bool = True
    workday_reminders: bool = True
    wind_down: str = "17:00"
    leave_mode: str = "17:30"
    strong_leave: str = "18:00"
    late_leave: str = "18:30"

    window_x: int = -1
    window_y: int = -1

    widget_scale: int = 110
    show_time: bool = True
    show_status: bool = True
    show_message: bool = True

    time_text_size: int = 16
    status_text_size: int = 9
    message_text_size: int = 11
    time_text_color: str = "#13A45C"
    status_text_color: str = "#11854B"
    message_text_color: str = "#E05A88"

    image_default: str = ""
    image_cheer: str = ""
    image_rest: str = ""
    image_away: str = ""
    image_warning: str = ""
    image_leave: str = ""
    image_stats: str = ""
    image_settings: str = ""
    image_alert: str = ""
    image_profile: str = ""

    image_default_mode: str = "fit"
    image_cheer_mode: str = "fit"
    image_rest_mode: str = "fit"
    image_away_mode: str = "fit"
    image_warning_mode: str = "fit"
    image_leave_mode: str = "fit"
    image_stats_mode: str = "fit"
    image_settings_mode: str = "fit"
    image_alert_mode: str = "fit"
    image_profile_mode: str = "fit"

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

    def validate_widget_style(self) -> None:
        if not 80 <= self.widget_scale <= 140:
            raise ValueError("위젯 크기는 80~140% 사이로 설정해 주세요.")
        if not 14 <= self.time_text_size <= 24:
            raise ValueError("시간 글자 크기는 14~24 사이로 설정해 주세요.")
        if not 7 <= self.status_text_size <= 12:
            raise ValueError("상태 글자 크기는 7~12 사이로 설정해 주세요.")
        if not 9 <= self.message_text_size <= 16:
            raise ValueError("메시지 글자 크기는 9~16 사이로 설정해 주세요.")
        validate_hex_color(self.time_text_color)
        validate_hex_color(self.status_text_color)
        validate_hex_color(self.message_text_color)


def settings_from_dict(raw: object) -> UserSettings:
    if not isinstance(raw, dict):
        return UserSettings()

    d = UserSettings()
    wind_down = _clock_or(raw.get("wind_down", d.wind_down), d.wind_down)
    leave_mode = _clock_or(raw.get("leave_mode", d.leave_mode), d.leave_mode)
    strong_leave = _clock_or(raw.get("strong_leave", d.strong_leave), d.strong_leave)
    late_leave = _clock_or(raw.get("late_leave", d.late_leave), d.late_leave)

    try:
        ordered = [parse_clock(v) for v in (wind_down, leave_mode, strong_leave, late_leave)]
        if ordered != sorted(ordered):
            raise ValueError
    except ValueError:
        wind_down, leave_mode, strong_leave, late_leave = (
            d.wind_down, d.leave_mode, d.strong_leave, d.late_leave
        )

    return UserSettings(
        start_with_windows=_coerce_bool(raw.get("start_with_windows"), d.start_with_windows),
        always_on_top=_coerce_bool(raw.get("always_on_top"), d.always_on_top),
        break_reminders=_coerce_bool(raw.get("break_reminders"), d.break_reminders),
        workday_reminders=_coerce_bool(raw.get("workday_reminders"), d.workday_reminders),
        wind_down=wind_down,
        leave_mode=leave_mode,
        strong_leave=strong_leave,
        late_leave=late_leave,
        window_x=_position_int(raw.get("window_x"), d.window_x),
        window_y=_position_int(raw.get("window_y"), d.window_y),
        widget_scale=_bounded_int(raw.get("widget_scale"), d.widget_scale, 80, 140),
        show_time=_coerce_bool(raw.get("show_time"), d.show_time),
        show_status=_coerce_bool(raw.get("show_status"), d.show_status),
        show_message=_coerce_bool(raw.get("show_message"), d.show_message),
        time_text_size=_bounded_int(raw.get("time_text_size"), d.time_text_size, 14, 24),
        status_text_size=_bounded_int(raw.get("status_text_size"), d.status_text_size, 7, 12),
        message_text_size=_bounded_int(raw.get("message_text_size"), d.message_text_size, 9, 16),
        time_text_color=_color_or(raw.get("time_text_color"), d.time_text_color),
        status_text_color=_color_or(raw.get("status_text_color"), d.status_text_color),
        message_text_color=_color_or(raw.get("message_text_color"), d.message_text_color),
        image_default=str(raw.get("image_default", "")),
        image_cheer=str(raw.get("image_cheer", "")),
        image_rest=str(raw.get("image_rest", "")),
        image_away=str(raw.get("image_away", "")),
        image_warning=str(raw.get("image_warning", "")),
        image_leave=str(raw.get("image_leave", "")),
        image_stats=str(raw.get("image_stats", "")),
        image_settings=str(raw.get("image_settings", "")),
        image_alert=str(raw.get("image_alert", "")),
        image_profile=str(raw.get("image_profile", "")),
        image_default_mode=_fit_mode(raw.get("image_default_mode", "fit")),
        image_cheer_mode=_fit_mode(raw.get("image_cheer_mode", "fit")),
        image_rest_mode=_fit_mode(raw.get("image_rest_mode", "fit")),
        image_away_mode=_fit_mode(raw.get("image_away_mode", "fit")),
        image_warning_mode=_fit_mode(raw.get("image_warning_mode", "fit")),
        image_leave_mode=_fit_mode(raw.get("image_leave_mode", "fit")),
        image_stats_mode=_fit_mode(raw.get("image_stats_mode", "fit")),
        image_settings_mode=_fit_mode(raw.get("image_settings_mode", "fit")),
        image_alert_mode=_fit_mode(raw.get("image_alert_mode", "fit")),
        image_profile_mode=_fit_mode(raw.get("image_profile_mode", "fit")),
    )


def load_user_settings(path: Path) -> UserSettings:
    if not path.is_file():
        return UserSettings()
    try:
        return settings_from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return UserSettings()


def save_user_settings(path: Path, settings: UserSettings) -> None:
    settings.workday_policy()
    settings.validate_widget_style()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        temp.write_text(json.dumps(asdict(settings), ensure_ascii=False, indent=2), encoding="utf-8")
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
    script = Path(__file__).resolve().parent / "desktop_compact.py"
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
