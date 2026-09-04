from pathlib import Path

path = Path('desktop_compact.py')
text = path.read_text(encoding='utf-8')

start = text.index('    def _character_x_offset(self) -> int:\n')
end = text.index('    def _resize_for_page(self, name: str):\n', start)

replacement = '''    def _character_render_size(self) -> tuple[int, int]:
        # Prefer the exact PhotoImage dimensions after a live scale change.
        photo = getattr(self, "character_photo", None)
        if photo is not None:
            try:
                width = int(photo.width())
                height = int(photo.height())
                if width > 1 and height > 1:
                    return width, height
            except tk.TclError:
                pass
        return self._scale(self.CHARACTER_MAX[0]), self._scale(self.CHARACTER_MAX[1])

    def _clock_render_width(self) -> int:
        # 150 px is a conservative reserve for the default clock/status group.
        width = 150
        clock = getattr(self, "clock", None)
        if clock is not None:
            try:
                req = int(clock.winfo_reqwidth())
                if req > 1:
                    width = req
            except tk.TclError:
                pass
        return width

    def _cluster_horizontal_layout(self) -> tuple[int, int]:
        # Clock/status + Kyunghee are one visible cluster. Their edge-to-edge
        # horizontal gap is always 30 px at every widget scale.
        timer_width, _timer_height = self._timer_size()
        character_width, _character_height = self._character_render_size()
        clock_width = self._clock_render_width()
        gap = 30
        cluster_width = clock_width + gap + character_width
        cluster_left = max(24, round((timer_width - cluster_width) / 2))
        character_center = cluster_left + clock_width + gap + character_width / 2
        return cluster_left, round(character_center - timer_width / 2)

    def _character_x_offset(self) -> int:
        _clock_x, character_offset = self._cluster_horizontal_layout()
        return character_offset

    def _character_bottom_gap(self) -> int:
        # Fixed relation to the message lane: scaling must not push the artwork
        # farther away from the message.
        return 72

    def _message_x_offset(self) -> int:
        # Center the message directly under Kyunghee rather than under the canvas.
        return self._character_x_offset()

    def _message_bottom_gap(self) -> int:
        return 16

    def _clock_offset(self) -> tuple[int, int]:
        # Follow the rendered artwork both horizontally and vertically. This
        # removes the large empty diagonal gap visible at 80, 140 and 200%.
        _timer_width, timer_height = self._timer_size()
        clock_x, _character_offset = self._cluster_horizontal_layout()
        _character_width, character_height = self._character_render_size()
        character_top = timer_height - self._character_bottom_gap() - character_height
        return clock_x, max(18, round(character_top + 4))

    def _timer_size(self):
        # Keep a generous click-through transparent canvas, but guarantee enough
        # width for the whole visible cluster at every scale. The visible UI
        # spacing itself stays fixed while only the artwork and canvas grow.
        growth = self._layout_growth()
        width = self.MIN_TIMER_SIZE[0] + round(growth * 3.60)
        height = self.MIN_TIMER_SIZE[1] + round(growth * 3.40)
        fixed_side_margins = 48
        clock_reserve = 150
        cluster_gap = 30
        required_width = fixed_side_margins + clock_reserve + cluster_gap + self._scale(self.CHARACTER_MAX[0])
        required_height = self._scale(self.CHARACTER_MAX[1]) + 130
        return max(width, required_width), max(height, required_height)

'''

text = text[:start] + replacement + text[end:]

old_preview = '''        self._apply_widget_appearance()\n        self.character_role = None\n        self._set_character("default")\n        # Keep the settings panel usable while previewing. The timer window size\n'''
new_preview = '''        self._apply_widget_appearance()\n        self.character_role = None\n        self._set_character("default")\n        # Re-run placement after the PhotoImage has its new exact dimensions.\n        self._apply_widget_appearance()\n        # Keep the settings panel usable while previewing. The timer window size\n'''
if old_preview not in text:
    raise RuntimeError('preview placement block not found')
text = text.replace(old_preview, new_preview, 1)

path.write_text(text, encoding='utf-8')
