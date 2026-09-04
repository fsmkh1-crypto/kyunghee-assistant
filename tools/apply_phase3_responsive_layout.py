from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


path = Path("desktop_compact.py")
text = path.read_text(encoding="utf-8")

text = replace_once(
    text,
    "    def _timer_size(self):\n        return self._scale(self.COMPACT_SIZE[0]), self._scale(self.COMPACT_SIZE[1])\n",
    "    def _layout_growth(self) -> int:\n        return max(0, self._effective_widget_scale() - 100)\n\n"
    "    def _character_x_offset(self) -> int:\n        # As the transparent canvas grows, shift Kyunghee gradually to the right\n"
    "        # so the fixed-size clock/status area keeps clear of the artwork.\n"
    "        return round(self._layout_growth() * 0.60)\n\n"
    "    def _message_gutter(self) -> int:\n        # Extra transparent space below the character. The message stays near the\n"
    "        # real window bottom, so this visually moves it down as scale increases.\n"
    "        return round(self._layout_growth() * 0.60)\n\n"
    "    def _timer_size(self):\n"
    "        growth = self._layout_growth()\n"
    "        width = self._scale(self.COMPACT_SIZE[0]) + round(growth * 0.30)\n"
    "        height = self._scale(self.COMPACT_SIZE[1]) + self._message_gutter()\n"
    "        return width, height\n",
    "responsive layout helpers",
)

text = replace_once(
    text,
    "        self.character.place(relx=0.5, rely=1.0, y=-self._scale(18), anchor=\"s\")",
    "        self.character.place(\n"
    "            relx=0.5, x=self._character_x_offset(), rely=1.0,\n"
    "            y=-(self._scale(18) + self._message_gutter()), anchor=\"s\",\n"
    "        )",
    "initial character responsive placement",
)

text = replace_once(
    text,
    "        self.character.place(relx=0.5, rely=1.0, y=-self._scale(18), anchor=\"s\")",
    "        self.character.place(\n"
    "            relx=0.5, x=self._character_x_offset(), rely=1.0,\n"
    "            y=-(self._scale(18) + self._message_gutter()), anchor=\"s\",\n"
    "        )",
    "live character responsive placement",
)

text = replace_once(
    text,
    "        self.speech.place(relx=0.5, rely=1.0, y=-self._scale(3), anchor=\"s\")",
    "        self.speech.place(relx=0.5, rely=1.0, y=-self._scale(3), anchor=\"s\")",
    "initial message placement anchor",
)

# The message placement call appears again in _apply_widget_appearance; keep it at
# the actual bottom of the expanded transparent window so the new gutter separates
# it from the character instead of scaling the text itself.

path.write_text(text, encoding="utf-8")
print("Phase 3 responsive layout applied")
