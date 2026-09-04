from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


path = Path("desktop_compact.py")
text = path.read_text(encoding="utf-8")

old = '''    def _layout_growth(self) -> int:\n        return max(0, self._effective_widget_scale() - 100)\n\n    def _character_x_offset(self) -> int:\n        # As the transparent canvas grows, shift Kyunghee gradually to the right\n        # so the fixed-size clock/status area keeps clear of the artwork.\n        return round(self._layout_growth() * 0.60)\n\n    def _message_gutter(self) -> int:\n        # Extra transparent space below the character. The message stays near the\n        # real window bottom, so this visually moves it down as scale increases.\n        return round(self._layout_growth() * 0.60)\n\n    def _timer_size(self):\n        growth = self._layout_growth()\n        width = self._scale(self.COMPACT_SIZE[0]) + round(growth * 0.30)\n        height = self._scale(self.COMPACT_SIZE[1]) + self._message_gutter()\n        return width, height\n'''

new = '''    def _layout_growth(self) -> int:\n        return max(0, self._effective_widget_scale() - 100)\n\n    def _character_render_size(self):\n        return self._scale(self.CHARACTER_MAX[0]), self._scale(self.CHARACTER_MAX[1])\n\n    def _left_ui_reserve(self) -> int:\n        # Reserve enough transparent canvas for the clock/status block at every\n        # scale. Text sizes are independent of widget scale, so this can stay\n        # mostly fixed while the character grows.\n        return 145\n\n    def _right_ui_reserve(self) -> int:\n        # Keep the close control clear of the character on large scales.\n        return 28\n\n    def _message_reserve(self) -> int:\n        # Dedicated transparent area below the character for the message line.\n        # Increase it mildly on large scales so long messages stay visually clear.\n        return 82 + round(self._layout_growth() * 0.45)\n\n    def _character_x_offset(self) -> int:\n        width, _height = self._timer_size()\n        char_w, _char_h = self._character_render_size()\n        left = self._left_ui_reserve() + 14\n        right = self._right_ui_reserve()\n        available_left = left\n        available_right = max(available_left + char_w, width - right)\n        centered = (available_left + available_right) / 2\n        return round(centered - width / 2)\n\n    def _message_gutter(self) -> int:\n        return self._message_reserve()\n\n    def _timer_size(self):\n        char_w, char_h = self._character_render_size()\n        width = max(\n            480,\n            self._left_ui_reserve() + 14 + char_w + self._right_ui_reserve(),\n        )\n        height = max(\n            650,\n            34 + char_h + self._message_reserve(),\n        )\n        return int(width), int(height)\n'''
text = replace_once(text, old, new, "large transparent canvas helpers")

old = '            max_size = (self._scale(self.CHARACTER_MAX[0]), self._scale(self.CHARACTER_MAX[1]))'
new = '            max_size = self._character_render_size()'
text = replace_once(text, old, new, "character render size helper")

old = '''        self.character.place(\n            relx=0.5, x=self._character_x_offset(), rely=1.0,\n            y=-(self._scale(18) + self._message_gutter()), anchor="s",\n        )'''
new = '''        self.character.place(\n            relx=0.5, x=self._character_x_offset(), rely=1.0,\n            y=-self._message_gutter(), anchor="s",\n        )'''
if text.count(old) != 2:
    raise SystemExit(f"character placement: expected 2 matches, found {text.count(old)}")
text = text.replace(old, new)

# Clock/status remain in the fixed top-left safety area. Keep their inset fixed so
# shrinking the character to 80% does not pull the text toward the artwork.
old = '        self.clock.place(x=self._scale(6), y=self._scale(6))'
new = '        self.clock.place(x=12, y=10)'
text = replace_once(text, old, new, "fixed clock safety position")

# Keep close button at a fixed safe inset from the enlarged transparent canvas.
old = '        self.escape_control.place(relx=1.0, x=-self._scale(8), y=self._scale(5), anchor="ne")'
new = '        self.escape_control.place(relx=1.0, x=-12, y=8, anchor="ne")'
if text.count(old) != 2:
    raise SystemExit(f"close placement: expected 2 matches, found {text.count(old)}")
text = text.replace(old, new)

path.write_text(text, encoding="utf-8")
print("Phase 3 large transparent canvas layout applied")
