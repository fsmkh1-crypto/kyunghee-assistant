from pathlib import Path

path = Path("desktop_compact.py")
text = path.read_text(encoding="utf-8")


def replace_once(old: str, new: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"expected one match, found {count}: {old[:120]!r}")
    text = text.replace(old, new, 1)


replace_once(
'''    def _character_bottom_gap(self) -> int:\n        # Fixed relation to the message lane: scaling must not push the artwork\n        # farther away from the message.\n        return 72\n\n    def _message_x_offset(self) -> int:\n''',
'''    def _message_render_height(self) -> int:\n        if not self._effective_display_flag("show_message"):\n            return 0\n        speech = getattr(self, "speech", None)\n        if speech is not None:\n            try:\n                req = int(speech.winfo_reqheight())\n                if req > 1:\n                    return req\n            except tk.TclError:\n                pass\n        return 36\n\n    def _character_bottom_gap(self) -> int:\n        # Keep Kyunghee's *visible* feet above the message even when narrower\n        # scales make the message wrap to extra lines. The message remains pinned\n        # near the bottom; only the artwork rises when more vertical clearance is\n        # actually required. Transparent padding below the visible silhouette is\n        # excluded so custom images and all widget scales behave consistently.\n        base_gap = 72\n        message_height = self._message_render_height()\n        if not message_height:\n            return base_gap\n        _image_width, image_height = self._character_render_size()\n        _visible_left, _visible_top, _visible_right, visible_bottom = self._character_visible_bounds()\n        transparent_bottom = max(0, image_height - visible_bottom)\n        visible_clearance = 6\n        needed_gap = (\n            self._message_bottom_gap()\n            + message_height\n            + visible_clearance\n            - transparent_bottom\n        )\n        return max(base_gap, round(needed_gap))\n\n    def _message_x_offset(self) -> int:\n'''
)

path.write_text(text, encoding="utf-8")
