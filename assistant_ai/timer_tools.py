from __future__ import annotations

from dataclasses import replace
import re

from stats_summary import summarize_recent
from workday import should_encourage_more_work


TIMER_ACTIONS = {
    "start_break": "지금 휴식 시작",
    "start_away": "자리비움 시작",
    "resume": "자리비움 종료 및 집중 시간 기록 재개",
    "snooze_break": "이번 휴식 알림 미루기",
}
NOTIFICATION_TOGGLES = {
    "break": ("break_reminders", "휴식 알림"),
    "workday": ("workday_reminders", "퇴근 시간 알림"),
}
NOTIFICATION_MINUTES = {
    "break_interval": ("break_interval_minutes", "휴식 알림 간격", 20, 180),
    "snooze": ("snooze_minutes", "휴식 알림 미루기 시간", 1, 30),
}
WORKDAY_FIELDS = {
    "wind_down": "마무리 예고",
    "leave_mode": "퇴근 모드",
    "strong_leave": "적극 퇴근 권고",
    "late_leave": "야근 알림",
}


def _function(name, description, properties):
    return {
        "type": "function",
        "name": name,
        "description": description,
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": properties,
            "required": list(properties),
            "additionalProperties": False,
        },
    }


def _choices(values):
    return {"type": "string", "enum": list(values)}


_MUTATION = " Call only when the user explicitly asks to make this change. The app asks for confirmation."
TOOLS = [
    _function("get_timer_status", "Read the current focus, away, break and workday status.", {}),
    _function(
        "get_usage_stats",
        "Read actual timer statistics for today or the most recent 7 or 30 calendar days, including today.",
        {"days": {"type": "integer", "enum": [1, 7, 30]}},
    ),
    _function("get_notification_settings", "Read saved break and workday notification preferences.", {}),
    _function(
        "set_timer_action",
        "Start a break or an away session, resume from away, or snooze a due break." + _MUTATION,
        {"action": _choices(TIMER_ACTIONS)},
    ),
    _function(
        "set_notification_enabled",
        "Change whether scheduled break or workday reminders are enabled." + _MUTATION,
        {"kind": _choices(NOTIFICATION_TOGGLES), "enabled": {"type": "boolean"}},
    ),
    _function(
        "set_notification_minutes",
        "Change break interval (20–180 minutes) or snooze length (1–30 minutes)." + _MUTATION,
        {"kind": _choices(NOTIFICATION_MINUTES), "minutes": {"type": "integer"}},
    ),
    _function(
        "set_workday_schedule",
        "Change named workday reminder times. Use 24-hour HH:MM and null for unchanged fields." + _MUTATION,
        {field: {"type": ["string", "null"]} for field in WORKDAY_FIELDS},
    ),
]

_TOOL_PARAMETERS = {tool["name"]: tool["parameters"]["properties"] for tool in TOOLS}
_JSON_TYPES = {"string": str, "integer": int, "boolean": bool, "null": type(None)}
_CLOCK = re.compile(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]\Z")


def validate_arguments(name, arguments):
    if not isinstance(name, str) or name not in _TOOL_PARAMETERS:
        raise ValueError("지원하지 않는 타이머 기능이에요.")
    parameters = _TOOL_PARAMETERS[name]
    if not isinstance(arguments, dict) or arguments.keys() != parameters.keys():
        raise ValueError("타이머 기능에 필요한 값이 맞지 않아요.")
    for key, spec in parameters.items():
        kinds = spec["type"] if isinstance(spec["type"], list) else [spec["type"]]
        value = arguments[key]
        if type(value) not in [_JSON_TYPES[kind] for kind in kinds]:
            raise ValueError("타이머 설정에 사용할 값의 형식이 맞지 않아요.")
        if "enum" in spec and value not in spec["enum"]:
            raise ValueError("지원하지 않는 타이머 설정 값이에요.")

    if name == "set_notification_minutes":
        _, label, minimum, maximum = NOTIFICATION_MINUTES[arguments["kind"]]
        if not minimum <= arguments["minutes"] <= maximum:
            raise ValueError(f"{label}은 {minimum}~{maximum}분으로 설정할 수 있어요.")
    if name == "set_workday_schedule":
        if not any(arguments.values()):
            raise ValueError("바꿀 퇴근 알림 시간을 알려줘요.")
        if any(value is not None and not _CLOCK.fullmatch(value) for value in arguments.values()):
            raise ValueError("퇴근 알림 시간은 00:00부터 23:59 사이의 HH:MM으로 입력해 주세요.")
    return arguments.copy()


def _seconds(value):
    return max(0, int(value))


class TimerTools:
    """Run validated actions against the existing desktop app on its Tk thread."""

    def __init__(self, app):
        self.app = app

    def context(self):
        app = self.app
        daily, session = app.state.daily, app.state.session
        break_enabled_today = app.preferences.break_reminders and not daily.break_reminders_suppressed
        return {
            "date": daily.day,
            "is_away": session.is_away,
            "manual_away": session.manual_away,
            "continuous_seconds": _seconds(session.continuous_seconds),
            "today_active_seconds": _seconds(daily.active_seconds),
            "today_away_seconds": _seconds(daily.away_seconds),
            "today_away_count": daily.away_count,
            "break_reminders_enabled_today": break_enabled_today,
            "next_break_in_seconds": _seconds(app.engine.remaining_to_break()) if break_enabled_today and not session.is_away else None,
            "workday_mode": app._current_workday_state().mode,
        }

    def notification_settings(self):
        preferences = self.app.preferences
        fields = (*WORKDAY_FIELDS, "break_reminders", "workday_reminders", "break_interval_minutes", "snooze_minutes")
        return {field: getattr(preferences, field) for field in fields}

    def execute(self, name, arguments, confirm):
        try:
            arguments = validate_arguments(name, arguments)
            if name == "get_timer_status":
                return {"ok": True, **self.context()}
            if name == "get_notification_settings":
                return {"ok": True, **self.notification_settings()}
            if name == "get_usage_stats":
                return {"ok": True, **self._usage_stats(arguments["days"])}
            if name == "set_timer_action":
                return self._timer_action(arguments["action"], confirm)
            changes, description = self._preference_change(name, arguments)
            return self._apply_preferences(changes, description, confirm)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}

    def _usage_stats(self, days):
        summary = summarize_recent(self.app.state, days=days)
        return {
            "days": summary.days,
            "tracked_days": summary.tracked_days,
            "active_seconds": _seconds(summary.active_seconds),
            "away_seconds": _seconds(summary.away_seconds),
            "away_count": summary.away_count,
            "longest_continuous_seconds": _seconds(summary.longest_continuous),
            "average_active_seconds": _seconds(summary.average_active_seconds),
            "active_ratio_percent": round(summary.active_ratio, 1),
            "best_day": summary.best_day,
            "best_day_active_seconds": _seconds(summary.best_day_active_seconds),
        }

    def _check_timer_action(self, action):
        app = self.app
        away = app.state.session.is_away
        if action == "resume" and not away:
            raise ValueError("이미 집중 시간을 기록하고 있어요.")
        if action != "resume" and away:
            raise ValueError("지금은 이미 자리비움 상태예요.")
        if action == "snooze_break":
            if not should_encourage_more_work(app._current_workday_state().mode):
                raise ValueError("퇴근 모드에서는 휴식 알림을 미룰 수 없어요.")
            if (
                not app.preferences.break_reminders
                or app.state.daily.break_reminders_suppressed
                or app.engine.remaining_to_break() > 0
            ):
                raise ValueError("지금 미룰 수 있는 휴식 알림이 없어요.")

    def _timer_action(self, action, confirm):
        app = self.app
        self._check_timer_action(action)
        description = TIMER_ACTIONS[action]
        if action == "snooze_break":
            minutes = app.preferences.snooze_minutes
            description += f" ({minutes}분)"
        if not confirm(description):
            return {"ok": False, "error": "확인하지 않아 타이머 상태를 그대로 뒀어요."}
        self._check_timer_action(action)
        if action == "snooze_break" and minutes != app.preferences.snooze_minutes:
            raise ValueError("확인하는 동안 미루기 시간이 바뀌었어요. 다시 요청해 주세요.")
        if action == "start_break":
            app.accept_break()
        elif action == "snooze_break":
            app.snooze_break()
        else:
            app.toggle_manual_away()
        messages = {
            "start_break": "휴식을 시작했어요.",
            "start_away": "자리비움 상태로 바꿨어요.",
            "resume": "집중 시간 기록을 다시 시작했어요.",
            "snooze_break": "이번 휴식 알림을 미뤘어요.",
        }
        return {"ok": True, "changed": True, "message": messages[action], "action": action, **self.context()}

    @staticmethod
    def _preference_change(name, arguments):
        if name == "set_notification_enabled":
            field, label = NOTIFICATION_TOGGLES[arguments["kind"]]
            enabled = arguments["enabled"]
            return {field: enabled}, f"{label} {'켜기' if enabled else '끄기'}"
        if name == "set_notification_minutes":
            field, label, _, _ = NOTIFICATION_MINUTES[arguments["kind"]]
            minutes = arguments["minutes"]
            return {field: minutes}, f"{label}을 {minutes}분으로 변경"
        changes = {field: arguments[field] for field in WORKDAY_FIELDS if arguments[field] is not None}
        return changes, "\n".join(f"{WORKDAY_FIELDS[field]} {value}" for field, value in changes.items())

    def _candidate_preferences(self, changes):
        candidate = replace(self.app.preferences, **changes)
        candidate.workday_policy()
        candidate.validate_widget_style()
        return candidate

    def _apply_preferences(self, changes, description, confirm):
        candidate = self._candidate_preferences(changes)
        if candidate == self.app.preferences:
            return {"ok": True, "changed": False, "message": "이미 요청하신 설정이에요.", **self.notification_settings()}
        if not confirm(description):
            return {"ok": False, "error": "확인하지 않아 설정을 그대로 뒀어요."}
        candidate = self._candidate_preferences(changes)
        self.app.apply_preferences(candidate)
        self.app._sync_assistant_preference_controls(changes)
        return {"ok": True, "changed": True, "message": f"설정을 적용했어요.\n{description}", **self.notification_settings()}
