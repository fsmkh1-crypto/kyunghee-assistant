from pathlib import Path

path = Path('desktop_compact.py')
text = path.read_text(encoding='utf-8')
old = '''    def _clock_offset(self) -> tuple[int, int]:
        growth = self._layout_growth()
        return 18 + round(growth * 0.08), 18 + round(growth * 0.04)
'''
new = '''    def _clock_offset(self) -> tuple[int, int]:
        # Keep the clock/status group visually attached to Kyunghee instead of
        # pinning it to the far-left edge of an increasingly large transparent
        # canvas. Use the rendered artwork width when available and leave a
        # small safety gap so the clock never sits on top of the character.
        width, _height = self._timer_size()
        character_width = self._scale(self.CHARACTER_MAX[0])
        character = getattr(self, "character", None)
        if character is not None:
            try:
                req = int(character.winfo_reqwidth())
                if req > 1:
                    character_width = req
            except tk.TclError:
                pass

        clock_width = 128
        clock = getattr(self, "clock", None)
        if clock is not None:
            try:
                req = int(clock.winfo_reqwidth())
                if req > 1:
                    clock_width = req
            except tk.TclError:
                pass

        character_center = width / 2 + self._character_x_offset()
        character_left = character_center - character_width / 2
        gap = 14 + round(self._layout_growth() * 0.02)
        x = max(18, round(character_left - clock_width - gap))
        y = 18 + round(self._layout_growth() * 0.04)
        return x, y
'''
if old not in text:
    raise SystemExit('clock offset block not found')
text = text.replace(old, new, 1)
path.write_text(text, encoding='utf-8')
