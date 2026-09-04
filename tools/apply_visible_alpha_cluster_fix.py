from pathlib import Path

path = Path('desktop_compact.py')
text = path.read_text(encoding='utf-8')

old = '''    def _character_render_size(self) -> tuple[int, int]:
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
'''
new = '''    def _character_render_size(self) -> tuple[int, int]:
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

    def _character_visible_bounds(self) -> tuple[int, int, int, int]:
        # Layout against the actually visible alpha silhouette, not the full PNG
        # rectangle. Transparent padding otherwise makes a nominal 30 px gap look
        # much larger and the visual gap grows with widget scale.
        image_width, image_height = self._character_render_size()
        bounds = getattr(self, "_character_alpha_bbox", None)
        if bounds:
            left, top, right, bottom = (int(v) for v in bounds)
            left = min(max(0, left), image_width)
            top = min(max(0, top), image_height)
            right = min(max(left + 1, right), image_width)
            bottom = min(max(top + 1, bottom), image_height)
            return left, top, right, bottom
        return 0, 0, image_width, image_height

    def _clock_render_width(self) -> int:
'''
if old not in text:
    raise SystemExit('character render block not found')
text = text.replace(old, new, 1)

old = '''    def _cluster_horizontal_layout(self) -> tuple[int, int]:
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
'''
new = '''    def _cluster_horizontal_layout(self) -> tuple[int, int]:
        # Treat the clock/status + visible Kyunghee silhouette as one cluster.
        # Keep a fixed *visible* edge-to-edge gap at every scale; transparent PNG
        # padding is deliberately excluded from the gap calculation.
        timer_width, _timer_height = self._timer_size()
        character_width, _character_height = self._character_render_size()
        visible_left, _visible_top, visible_right, _visible_bottom = self._character_visible_bounds()
        clock_width = self._clock_render_width()
        visible_gap = 12
        visible_character_width = max(1, visible_right - visible_left)
        visible_cluster_width = clock_width + visible_gap + visible_character_width
        cluster_left = max(18, round((timer_width - visible_cluster_width) / 2))
        visible_character_left = cluster_left + clock_width + visible_gap
        image_left = visible_character_left - visible_left
        character_center = image_left + character_width / 2
        return cluster_left, round(character_center - timer_width / 2)
'''
if old not in text:
    raise SystemExit('cluster layout block not found')
text = text.replace(old, new, 1)

old = '''        _timer_width, timer_height = self._timer_size()
        clock_x, _character_offset = self._cluster_horizontal_layout()
        _character_width, character_height = self._character_render_size()
        character_top = timer_height - self._character_bottom_gap() - character_height
        return clock_x, max(18, round(character_top + 4))
'''
new = '''        _timer_width, timer_height = self._timer_size()
        clock_x, _character_offset = self._cluster_horizontal_layout()
        _character_width, character_height = self._character_render_size()
        _visible_left, visible_top, _visible_right, _visible_bottom = self._character_visible_bounds()
        character_top = timer_height - self._character_bottom_gap() - character_height
        return clock_x, max(18, round(character_top + visible_top + 4))
'''
if old not in text:
    raise SystemExit('clock offset block not found')
text = text.replace(old, new, 1)

old = '''            image = self._clean_character_alpha(image)
            self.character_photo = ImageTk.PhotoImage(image)
'''
new = '''            image = self._clean_character_alpha(image)
            alpha_bbox = image.getchannel("A").getbbox()
            self._character_alpha_bbox = alpha_bbox or (0, 0, image.width, image.height)
            self.character_photo = ImageTk.PhotoImage(image)
'''
if old not in text:
    raise SystemExit('set character alpha block not found')
text = text.replace(old, new, 1)

path.write_text(text, encoding='utf-8')
print('patched desktop_compact.py to use visible alpha silhouette for cluster spacing')
