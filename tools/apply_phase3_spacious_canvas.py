from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def replace_first(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"{label}: expected a match, found 0")
    return text.replace(old, new, 1)


path = Path("desktop_compact.py")
text = path.read_text(encoding="utf-8")

text = replace_once(
    text,
    '    COMPACT_SIZE = (300, 430)\n    DETAIL_SIZE = (410, 430)',
    '    COMPACT_SIZE = (300, 430)\n    MIN_TIMER_SIZE = (460, 610)\n    DETAIL_SIZE = (410, 430)',
    "minimum timer canvas",
)

old_helpers = '''    def _layout_growth(self) -> int:\n        return max(0, self._effective_widget_scale() - 100)\n\n    def _character_x_offset(self) -> int:\n        # Shift Kyunghee gradually right as the transparent canvas grows.\n        return round(self._layout_growth() * 0.60)\n\n    def _message_gutter(self) -> int:\n        # Add transparent room below the character so the message can move\n        # downward without being clipped or covering the artwork.\n        return round(self._layout_growth() * 0.60)\n\n    def _timer_size(self):\n        growth = self._layout_growth()\n        width = self._scale(self.COMPACT_SIZE[0]) + round(growth * 0.30)\n        height = self._scale(self.COMPACT_SIZE[1]) + self._message_gutter()\n        return width, height\n'''
new_helpers = '''    def _layout_growth(self) -> int:\n        return max(0, self._effective_widget_scale() - 100)\n\n    def _character_x_offset(self) -> int:\n        # The transparent canvas is deliberately generous even at low scale, so\n        # Kyunghee can sit clear of the clock. At high scale the artwork moves\n        # right only gradually; the canvas grows much faster than the spacing.\n        return 95 + round(self._layout_growth() * 0.20)\n\n    def _character_bottom_gap(self) -> int:\n        # Reserve a message lane below the artwork without letting the two drift\n        # too far apart as the widget grows.\n        return 78 + round(self._layout_growth() * 0.38)\n\n    def _message_x_offset(self) -> int:\n        # Keep the message visually related to Kyunghee rather than centered on\n        # the much wider transparent canvas.\n        return round(self._character_x_offset() * 0.36)\n\n    def _message_bottom_gap(self) -> int:\n        return 18 + round(self._layout_growth() * 0.05)\n\n    def _clock_offset(self) -> tuple[int, int]:\n        growth = self._layout_growth()\n        return 18 + round(growth * 0.08), 18 + round(growth * 0.04)\n\n    def _timer_size(self):\n        # Keep a roomy transparent canvas even at 80-100%. Above 100%, expand\n        # the canvas much faster than the UI spacing so 200% artwork still fits\n        # while the clock, character and message remain visually grouped.\n        growth = self._layout_growth()\n        width = self.MIN_TIMER_SIZE[0] + round(growth * 3.60)\n        height = self.MIN_TIMER_SIZE[1] + round(growth * 3.40)\n        return width, height\n'''
text = replace_once(text, old_helpers, new_helpers, "responsive layout helpers")

old_character = '''        self.character.place(\n            relx=0.5, x=self._character_x_offset(), rely=1.0,\n            y=-(self._scale(18) + self._message_gutter()), anchor="s",\n        )'''
new_character = '''        self.character.place(\n            relx=0.5, x=self._character_x_offset(), rely=1.0,\n            y=-self._character_bottom_gap(), anchor="s",\n        )'''
text = replace_first(text, old_character, new_character, "initial character placement")

text = replace_once(
    text,
    '        clock.place(x=self._scale(6), y=self._scale(6))',
    '        clock_x, clock_y = self._clock_offset()\n        clock.place(x=clock_x, y=clock_y)',
    "initial clock placement",
)

text = replace_first(
    text,
    '        self.speech.place(relx=0.5, rely=1.0, y=-self._scale(3), anchor="s")',
    '        self.speech.place(\n            relx=0.5, x=self._message_x_offset(), rely=1.0,\n            y=-self._message_bottom_gap(), anchor="s",\n        )',
    "initial message placement",
)

old_live = '''        if self._effective_display_flag("show_message"):\n            self.speech.place(relx=0.5, rely=1.0, y=-self._scale(3), anchor="s")\n        else:\n            self.speech.place_forget()\n\n        self.clock.place(x=self._scale(6), y=self._scale(6))\n        self.character.place(\n            relx=0.5, x=self._character_x_offset(), rely=1.0,\n            y=-(self._scale(18) + self._message_gutter()), anchor="s",\n        )\n        self.escape_control.configure(font=(self.FONT_FAMILY, 12, "normal"))\n        self.escape_control.place(relx=1.0, x=-self._scale(8), y=self._scale(5), anchor="ne")\n'''
new_live = '''        if self._effective_display_flag("show_message"):\n            self.speech.place(\n                relx=0.5, x=self._message_x_offset(), rely=1.0,\n                y=-self._message_bottom_gap(), anchor="s",\n            )\n        else:\n            self.speech.place_forget()\n\n        clock_x, clock_y = self._clock_offset()\n        self.clock.place(x=clock_x, y=clock_y)\n        self.character.place(\n            relx=0.5, x=self._character_x_offset(), rely=1.0,\n            y=-self._character_bottom_gap(), anchor="s",\n        )\n        self.escape_control.configure(font=(self.FONT_FAMILY, 12, "normal"))\n        self.escape_control.place(relx=1.0, x=-18, y=14, anchor="ne")\n'''
text = replace_once(text, old_live, new_live, "live responsive placement")

text = replace_once(
    text,
    '            bg=self.TRANSPARENT_KEY, wraplength=self._scale(self.BUBBLE_WRAP),',
    '            bg=self.TRANSPARENT_KEY, wraplength=min(360, max(250, self._scale(self.BUBBLE_WRAP))),',
    "message wrap clamp",
)

path.write_text(text, encoding="utf-8")
print("Phase 3 spacious canvas layout applied")
