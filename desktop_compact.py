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

    FONT_FAMILY = "Pretendard"
    TIME_TEXT = "#159A55"
    STATUS_TEXT = "#178A50"
    MESSAGE_TEXT = "#C85B7D"

    def __init__(self):
        super().__init__()
        # Frameless widget mode. Top-most behavior follows the saved setting
        # instead of being forced on by the compact shell.
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", self.preferences.always_on_top)
        self._drag_origin = None

    def _label(self, parent, text="", size=10, weight="normal", fg=core.TEXT, bg=None, **kwargs):
        return tk.Label(
            parent,
            text=text,
            font=(self.FONT_FAMILY, size, weight),
            fg=fg,
            bg=bg or parent.cget("bg"),
            **kwargs,
        )

    def _button(self, parent, text, command, primary=False, width=None):
        button = super()._button(parent, text, command, primary=primary, width=width)
        button.configure(font=(self.FONT_FAMILY, 9, "bold"))
        return button

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
        # The base implementation saves preferences and applies -topmost
        # immediately, so the setting now works in compact mode as well.
        super().apply_preferences(preferences)

    def show(self):
        self.root.deiconify()
        self.root.lift()
        self.root.attributes("-topmost", self.preferences.always_on_top)

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

        # Approved artwork only; clicking Kyunghee is the only way to open details.
        self.character = tk.Label(hero, bg=self.TRANSPARENT_KEY, bd=0, cursor="hand2")
        self.character.place(relx=0.5, rely=1.0, y=-48, anchor="s")

        # The time itself doubles as the move handle. No extra move button is shown.
        clock = tk.Frame(hero, bg=self.TRANSPARENT_KEY, bd=0, highlightthickness=0, cursor="fleur")
        clock.place(x=6, y=6)
        self.cont = self._label(
            clock,
            "00:00:00",
            size=20,
            weight="bold",
            fg=self.TIME_TEXT,
            bg=self.TRANSPARENT_KEY,
            cursor="fleur",
        )
        self.cont.pack(anchor="w")
        self.main_status = self._label(
            clock,
            "집중 중",
            size=8,
            weight="bold",
            fg=self.STATUS_TEXT,
            bg=self.TRANSPARENT_KEY,
            cursor="fleur",
        )
        self.main_status.pack(anchor="w", pady=(0, 2))
        for widget in (clock, self.cont, self.main_status):
            self._bind_drag_surface(widget)

        # Dialogue remains text-only, but darker rose and a slightly larger
        # Pretendard face improve readability over light desktop backgrounds.
        self.speech = tk.Label(
            hero,
            text=pick("playful"),
            wraplength=self.BUBBLE_WRAP,
            justify="center",
            font=(self.FONT_FAMILY, 10, "bold"),
            fg=self.MESSAGE_TEXT,
            bg=self.TRANSPARENT_KEY,
            bd=0,
            highlightthickness=0,
            padx=2,
            pady=1,
            cursor="hand2",
        )
        self.speech.place(relx=0.5, rely=1.0, y=-6, anchor="s")

        self.character.bind("<Button-1>", lambda _event: self.show_stats())
        self.speech.bind("<Button-1>", self._cycle_message)

    def _update_ui(self):
        super()._update_ui()
        away = self.state.session.is_away
        self.main_status.configure(
            text="자리비움 중" if away else "집중 중",
            fg=core.AMBER if away else self.STATUS_TEXT,
        )


if __name__ == "__main__":
    singleton = SingleInstance()
    if not singleton.acquire():
        raise SystemExit(0)
    CompactDesktopApp().run()
