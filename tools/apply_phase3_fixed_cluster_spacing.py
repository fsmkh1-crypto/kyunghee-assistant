from pathlib import Path

path = Path('desktop_compact.py')
text = path.read_text(encoding='utf-8')

start = text.index('    def _character_x_offset(self) -> int:\n')
end = text.index('    def _timer_size(self):\n', start)

replacement = '''    def _character_render_size(self) -> tuple[int, int]:
        width = self._scale(self.CHARACTER_MAX[0])
        height = self._scale(self.CHARACTER_MAX[1])
        character = getattr(self, "character", None)
        if character is not None:
            try:
                req_width = int(character.winfo_reqwidth())
                req_height = int(character.winfo_reqheight())
                if req_width > 1:
                    width = req_width
                if req_height > 1:
                    height = req_height
            except tk.TclError:
                pass
        return width, height

    def _clock_render_width(self) -> int:
        width = 128
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
        # Treat clock/status + Kyunghee as one visual cluster. The visible gap
        # is intentionally constant at every widget scale; only the transparent
        # canvas and artwork size change.
        timer_width, _timer_height = self._timer_size()
        character_width, _character_height = self._character_render_size()
        clock_width = self._clock_render_width()
        gap = 30
        cluster_width = clock_width + gap + character_width
        cluster_left = max(18, round((timer_width - cluster_width) / 2))
        character_center = cluster_left + clock_width + gap + character_width / 2
        return cluster_left, round(character_center - timer_width / 2)

    def _character_x_offset(self) -> int:
        _clock_x, character_offset = self._cluster_horizontal_layout()
        return character_offset

    def _character_bottom_gap(self) -> int:
        # Keep the artwork-to-message relationship stable instead of pushing
        # Kyunghee farther upward as scale increases.
        return 72

    def _message_x_offset(self) -> int:
        # Center the message under Kyunghee, not under the whole transparent canvas.
        return self._character_x_offset()

    def _message_bottom_gap(self) -> int:
        return 16

    def _clock_offset(self) -> tuple[int, int]:
        # Keep clock/status beside the actual top-left region of the rendered
        # artwork. Horizontal spacing is always 30 px; vertical placement follows
        # the artwork top, so low scales no longer leave a large empty gap.
        timer_width, timer_height = self._timer_size()
        _ = timer_width
        clock_x, _character_offset = self._cluster_horizontal_layout()
        _character_width, character_height = self._character_render_size()
        character_top = timer_height - self._character_bottom_gap() - character_height
        return clock_x, max(18, round(character_top + 4))

'''

text = text[:start] + replacement + text[end:]
path.write_text(text, encoding='utf-8')
