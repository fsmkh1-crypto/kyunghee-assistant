from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


compact_path = Path("desktop_compact.py")
text = compact_path.read_text(encoding="utf-8")

text = replace_once(
    text,
    "        self._drag_origin = None\n        self._hotkey_stop = threading.Event()",
    "        self._drag_origin = None\n        self._character_dragged = False\n        self._hotkey_stop = threading.Event()",
    "character drag state",
)

text = replace_once(
    text,
    "    def _bind_drag_surface(self, widget):\n        widget.bind(\"<ButtonPress-1>\", self._start_drag)\n        widget.bind(\"<B1-Motion>\", self._drag_window)\n        widget.bind(\"<ButtonRelease-1>\", self._stop_drag)\n\n    def _emergency_hide(self, _event=None):",
    "    def _bind_drag_surface(self, widget):\n        widget.bind(\"<ButtonPress-1>\", self._start_drag)\n        widget.bind(\"<B1-Motion>\", self._drag_window)\n        widget.bind(\"<ButtonRelease-1>\", self._stop_drag)\n\n    def _start_character_drag(self, event):\n        self._character_dragged = False\n        self._start_drag(event)\n\n    def _drag_character(self, event):\n        if self._drag_origin:\n            start_x, start_y, _win_x, _win_y = self._drag_origin\n            if abs(event.x_root - start_x) >= 4 or abs(event.y_root - start_y) >= 4:\n                self._character_dragged = True\n        self._drag_window(event)\n\n    def _stop_character_drag(self, event):\n        dragged = self._character_dragged\n        self._stop_drag(event)\n        self._character_dragged = False\n        if not dragged:\n            self.show_stats()\n\n    def _emergency_hide(self, _event=None):",
    "character click-drag handlers",
)

text = replace_once(
    text,
    "            max_size = (self._scale(self.CHARACTER_MAX[0]), self._scale(self.CHARACTER_MAX[1]))",
    "            max_size = (self._scale(self.CHARACTER_MAX[0]), self._scale(self.CHARACTER_MAX[1]))",
    "character max size anchor",
)

text = replace_once(
    text,
    "            clock, \"00:00:00\", family=self.FONT_FAMILY, size=self._scale(p.time_text_size),",
    "            clock, \"00:00:00\", family=self.FONT_FAMILY, size=p.time_text_size,",
    "initial time font decouple",
)
text = replace_once(
    text,
    "            clock, \"집중 중\", family=self.FONT_FAMILY, size=self._scale(p.status_text_size),",
    "            clock, \"집중 중\", family=self.FONT_FAMILY, size=p.status_text_size,",
    "initial status font decouple",
)
text = replace_once(
    text,
    "            hero, text=\"×\", font=(self.FONT_FAMILY, self._scale(12), \"normal\"),",
    "            hero, text=\"×\", font=(self.FONT_FAMILY, 12, \"normal\"),",
    "initial close font decouple",
)
text = replace_once(
    text,
    "            hero, pick(\"playful\"), family=self.FONT_FAMILY, size=self._scale(p.message_text_size),",
    "            hero, pick(\"playful\"), family=self.FONT_FAMILY, size=p.message_text_size,",
    "initial message font decouple",
)

text = replace_once(
    text,
    "        self.character.bind(\"<Button-1>\", lambda _event: self.show_stats())\n        self.speech.bind(\"<Button-1>\", self._cycle_message)",
    "        self.character.bind(\"<ButtonPress-1>\", self._start_character_drag)\n        self.character.bind(\"<B1-Motion>\", self._drag_character)\n        self.character.bind(\"<ButtonRelease-1>\", self._stop_character_drag)\n        self.speech.bind(\"<Button-1>\", self._cycle_message)",
    "character bindings",
)

text = replace_once(
    text,
    "            size=self._scale(p.time_text_size), fg=p.time_text_color,",
    "            size=p.time_text_size, fg=p.time_text_color,",
    "live time font decouple",
)
text = replace_once(
    text,
    "            size=self._scale(p.status_text_size), fg=p.status_text_color,",
    "            size=p.status_text_size, fg=p.status_text_color,",
    "live status font decouple",
)
text = replace_once(
    text,
    "            size=self._scale(p.message_text_size), fg=p.message_text_color,",
    "            size=p.message_text_size, fg=p.message_text_color,",
    "live message font decouple",
)
text = replace_once(
    text,
    "        self.escape_control.configure(font=(self.FONT_FAMILY, self._scale(12), \"normal\"))",
    "        self.escape_control.configure(font=(self.FONT_FAMILY, 12, \"normal\"))",
    "live close font decouple",
)

text = replace_once(
    text,
    "            content, from_=80, to=140, orient=\"horizontal\", resolution=5,",
    "            content, from_=80, to=200, orient=\"horizontal\", resolution=5,",
    "scale range",
)
text = replace_once(
    text,
    "            \"시간과 상태를 모두 꺼도 위쪽 투명 드래그 영역으로 창을 이동할 수 있습니다.\",",
    "            \"시간과 상태를 모두 꺼도 경희 이미지를 누른 채 움직이면 창을 이동할 수 있습니다.\",",
    "drag help text",
)

compact_path.write_text(text, encoding="utf-8")

settings_path = Path("settings.py")
settings = settings_path.read_text(encoding="utf-8")
settings = replace_once(
    settings,
    "        if not 80 <= self.widget_scale <= 140:\n            raise ValueError(\"위젯 크기는 80~140% 사이로 설정해 주세요.\")",
    "        if not 80 <= self.widget_scale <= 200:\n            raise ValueError(\"위젯 크기는 80~200% 사이로 설정해 주세요.\")",
    "settings validation range",
)
settings = replace_once(
    settings,
    "        widget_scale=_bounded_int(raw.get(\"widget_scale\"), d.widget_scale, 80, 140),",
    "        widget_scale=_bounded_int(raw.get(\"widget_scale\"), d.widget_scale, 80, 200),",
    "settings load range",
)
settings_path.write_text(settings, encoding="utf-8")

print("Phase 3 scale/drag polish applied")
