from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def replace_exact(text: str, old: str, new: str, expected: int, label: str) -> str:
    count = text.count(old)
    if count != expected:
        raise SystemExit(f"{label}: expected {expected} matches, found {count}")
    return text.replace(old, new, expected)


path = Path("desktop_compact.py")
text = path.read_text(encoding="utf-8")

text = replace_once(
    text,
    "    def _timer_size(self):\n        return self._scale(self.COMPACT_SIZE[0]), self._scale(self.COMPACT_SIZE[1])\n",
    "    def _layout_growth(self) -> int:\n        return max(0, self._effective_widget_scale() - 100)\n\n"
    "    def _character_x_offset(self) -> int:\n"
    "        # Shift Kyunghee gradually right as the transparent canvas grows.\n"
    "        return round(self._layout_growth() * 0.60)\n\n"
    "    def _message_gutter(self) -> int:\n"
    "        # Add transparent room below the character so the message can move\n"
    "        # downward without being clipped or covering the artwork.\n"
    "        return round(self._layout_growth() * 0.60)\n\n"
    "    def _timer_size(self):\n"
    "        growth = self._layout_growth()\n"
    "        width = self._scale(self.COMPACT_SIZE[0]) + round(growth * 0.30)\n"
    "        height = self._scale(self.COMPACT_SIZE[1]) + self._message_gutter()\n"
    "        return width, height\n",
    "responsive layout helpers",
)

old_character_place = "        self.character.place(relx=0.5, rely=1.0, y=-self._scale(18), anchor=\"s\")"
new_character_place = (
    "        self.character.place(\n"
    "            relx=0.5, x=self._character_x_offset(), rely=1.0,\n"
    "            y=-(self._scale(18) + self._message_gutter()), anchor=\"s\",\n"
    "        )"
)
text = replace_exact(
    text,
    old_character_place,
    new_character_place,
    2,
    "responsive character placement",
)

path.write_text(text, encoding="utf-8")
print("Phase 3 responsive layout applied")
