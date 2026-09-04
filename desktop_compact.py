from __future__ import annotations

import tkinter as tk
from PIL import ImageTk

import app as core
from app import SingleInstance
from desktop_app import DesktopApp
from messages import pick


class CompactDesktopApp(DesktopApp):
    """Narrow desktop shell that preserves the approved character artwork."""

    COMPACT_SIZE = (330, 430)
    DETAIL_SIZE = (440, 430)
    CHARACTER_MAX = (315, 320)
    BUBBLE_WIDTH = 306
    BUBBLE_WRAP = 278

    MESSAGE_BG = "#E5D3CF"
    MESSAGE_BORDER = "#B98F90"
    MESSAGE_TEXT = "#493637"

    @staticmethod
    def _clean_character_alpha(image):
        """Avoid dark colour-key fringes around anti-aliased PNG edges.

        Windows/Tk colour-key transparency only removes pixels that exactly
        match the transparent key. Semi-transparent PNG edge pixels otherwise
        blend against that dark key and leave a visible grey/black halo. For
        the compact always-on-top view, snap very faint edge pixels to fully
        transparent and the remaining artwork pixels to fully opaque.
        """
        rgba = image.convert("RGBA")
        alpha = rgba.getchannel("A")
        binary_alpha = alpha.point(lambda value: 0 if value < 72 else 255)
        rgba.putalpha(binary_alpha)
        return rgba

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

        # Keep the approved artwork fully contained. The label stays at the
        # rendered image size so transparent empty space is not a click target.
        self.character = tk.Label(hero, bg=self.TRANSPARENT_KEY, bd=0, cursor="hand2")
        self.character.place(relx=0.5, rely=1.0, y=-54, anchor="s")

        clock = tk.Frame(
            hero,
            bg=core.PANEL_2,
            highlightthickness=1,
            highlightbackground=core.BORDER,
            cursor="hand2",
        )
        clock.place(x=8, y=8)
        self.cont = self._label(clock, "00:00:00", size=18, weight="bold", bg=core.PANEL_2, cursor="hand2")
        self.cont.pack(padx=9, pady=(4, 0))
        self.main_status = self._label(
            clock,
            "집중 중 · 상세 보기",
            size=7,
            fg=core.GREEN,
            bg=core.PANEL_2,
            cursor="hand2",
        )
        self.main_status.pack(pady=(0, 4))

        bubble = tk.Frame(
            hero,
            bg=self.MESSAGE_BG,
            highlightthickness=1,
            highlightbackground=self.MESSAGE_BORDER,
            cursor="hand2",
        )
        bubble.place(relx=0.5, rely=1.0, y=-7, anchor="s", width=self.BUBBLE_WIDTH)
        self.speech = tk.Label(
            bubble,
            text=pick("playful"),
            wraplength=self.BUBBLE_WRAP,
            justify="center",
            font=("Malgun Gothic", 9, "bold"),
            fg=self.MESSAGE_TEXT,
            bg=self.MESSAGE_BG,
            padx=8,
            pady=7,
            cursor="hand2",
        )
        self.speech.pack(fill="x")

        for widget in (clock, self.cont, self.main_status):
            widget.bind("<Button-1>", lambda _event: self.show_stats())
        self.character.bind("<Button-1>", lambda _event: self.show_stats())
        for widget in (bubble, self.speech):
            widget.bind("<Button-1>", self._cycle_message)


if __name__ == "__main__":
    singleton = SingleInstance()
    if not singleton.acquire():
        raise SystemExit(0)
    CompactDesktopApp().run()
