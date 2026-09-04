from __future__ import annotations

import tkinter as tk
from PIL import ImageTk

import app as core
from app import SingleInstance
from desktop_app import DesktopApp
from messages import pick


class CompactDesktopApp(DesktopApp):
    """Narrow frameless desktop widget using the approved Kyunghee artwork."""

    COMPACT_SIZE = (300, 430)
    DETAIL_SIZE = (410, 430)
    CHARACTER_MAX = (288, 320)
    BUBBLE_WRAP = 258

    MESSAGE_TEXT = "#F29AB7"
    MOVE_TEXT = "#AEB7C8"

    def __init__(self):
        super().__init__()
        # Compact mode is intentionally a desktop widget: no native title bar
        # and always above normal application windows.
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self._drag_origin = None

    @staticmethod
    def _clean_character_alpha(image):
        """Avoid dark colour-key fringes around anti-aliased PNG edges."""
        rgba = image.convert("RGBA")
        alpha = rgba.getchannel("A")
        binary_alpha = alpha.point(lambda value: 0 if value < 72 else 255)
        rgba.putalpha(binary_alpha)
        return rgba

    def _start_drag(self, event):
        self._drag_origin = (event.x_root, event.y_root, self.root.winfo_x(), self.root.winfo_y())

    def _drag_window(self, event):
        if not self._drag_origin:
            return
        start_x, start_y, win_x, win_y = self._drag_origin
        self.root.geometry(f"+{win_x + event.x_root - start_x}+{win_y + event.y_root - start_y}")

    def _stop_drag(self, _event=None):
        self._drag_origin = None

    def _bind_drag_surface(self, widget):
        widget.bind("<ButtonPress-1>", self._start_drag)
        widget.bind("<B1-Motion>", self._drag_window)
        widget.bind("<ButtonRelease-1>", self._stop_drag)

    def apply_preferences(self, preferences) -> None:
        # Persist the rest of the settings, but compact widget mode itself is
        # always-on-top by design.
        super().apply_preferences(preferences)
        self.root.attributes("-topmost", True)

    def show(self):
        self.root.deiconify()
        self.root.lift()
        self.root.attributes("-topmost", True)

    def _set_character(self, role: str):
        if role == self.character_role:
            return
        try:
            image = self._load_character_image(role, self.CHARACTER_MAX, preserve_alpha=True)
            image = self._clean_character_alpha(image)
            self.character_photo = ImageTk.PhotoImage(image)
            self.character.configure(image=self.character_photo)
            self.character_role = role
        except Exception:
            core.log.exception("character asset failed: %s", role)

    def _build_timer_page(self):
        page = self.timer_page
        page.configure(bg=self.TRANSPARENT_KEY)
        hero = tk.Frame(page, bg=self.TRANSPARENT_KEY, bd=0, highlightthickness=0)
        hero.pack(fill="both", expand=True)

        # Visible move handle. A colour-key transparent background means the
        # empty widget surface itself is not a reliable drag target on Windows,
        # so this text-only handle owns window dragging.
        move_handle = tk.Label(
            hero,
            text="↕ 이동",
            font=("Malgun Gothic", 8, "bold"),
            fg=self.MOVE_TEXT,
            bg=self.TRANSPARENT_KEY,
            bd=0,
            highlightthickness=0,
            cursor="fleur",
            padx=2,
            pady=1,
        )
        move_handle.place(relx=1.0, x=-6, y=6, anchor="ne")
        self._bind_drag_surface(move_handle)

        # Approved artwork only; no visible panel around it.
        self.character = tk.Label(hero, bg=self.TRANSPARENT_KEY, bd=0, cursor="hand2")
        self.character.place(relx=0.5, rely=1.0, y=-48, anchor="s")

        # Time/status are text-only on the colour-key transparent surface.
        clock = tk.Frame(hero, bg=self.TRANSPARENT_KEY, bd=0, highlightthickness=0, cursor="hand2")
        clock.place(x=6, y=6)
        self.cont = self._label(
            clock,
            "00:00:00",
            size=18,
            weight="bold",
            fg=core.GREEN,
            bg=self.TRANSPARENT_KEY,
            cursor="hand2",
        )
        self.cont.pack(anchor="w")
        self.main_status = self._label(
            clock,
            "집중 중 · 상세 보기",
            size=7,
            fg=core.GREEN,
            bg=self.TRANSPARENT_KEY,
            cursor="hand2",
        )
        self.main_status.pack(anchor="w", pady=(0, 2))

        # Dialogue is also text-only: no bubble fill, border, or surrounding card.
        self.speech = tk.Label(
            hero,
            text=pick("playful"),
            wraplength=self.BUBBLE_WRAP,
            justify="center",
            font=("Malgun Gothic", 9, "bold"),
            fg=self.MESSAGE_TEXT,
            bg=self.TRANSPARENT_KEY,
            bd=0,
            highlightthickness=0,
            padx=2,
            pady=1,
            cursor="hand2",
        )
        self.speech.place(relx=0.5, rely=1.0, y=-6, anchor="s")

        for widget in (clock, self.cont, self.main_status):
            widget.bind("<Button-1>", lambda _event: self.show_stats())
        self.character.bind("<Button-1>", lambda _event: self.show_stats())
        self.speech.bind("<Button-1>", self._cycle_message)


if __name__ == "__main__":
    singleton = SingleInstance()
    if not singleton.acquire():
        raise SystemExit(0)
    CompactDesktopApp().run()
