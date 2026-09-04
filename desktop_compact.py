from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
from PIL import ImageTk

import app as core
from app import SingleInstance
from desktop_app import DesktopApp
from messages import pick


class OutlinedText(tk.Canvas):
    """Text-only widget with a one-pixel outline for transparent Windows surfaces."""

    OFFSETS = (
        (-1, -1), (0, -1), (1, -1),
        (-1, 0),           (1, 0),
        (-1, 1),  (0, 1),  (1, 1),
    )

    def __init__(
        self,
        parent,
        text,
        *,
        family,
        size,
        weight="normal",
        fg,
        outline,
        bg,
        wraplength=0,
        justify="left",
        cursor=None,
    ):
        super().__init__(
            parent,
            bg=bg,
            bd=0,
            highlightthickness=0,
            relief="flat",
            cursor=cursor or "arrow",
        )
        self._font = tkfont.Font(family=family, size=size, weight=weight)
        self._text = text
        self._fg = fg
        self._outline = outline
        self._wraplength = int(wraplength or 0)
        self._justify = justify
        self._outline_items = []
        self._main_item = None
        self._draw_items()
        self._refresh_geometry()

    def _text_position(self):
        pad = 3
        if self._justify == "center":
            width = self._wraplength or max(1, self._font.measure(self._text))
            return pad + width / 2, pad, "n"
        return pad, pad, "nw"

    def _item_kwargs(self, fill):
        x, y, anchor = self._text_position()
        kwargs = {
            "text": self._text,
            "font": self._font,
            "fill": fill,
            "anchor": anchor,
            "justify": self._justify,
        }
        if self._wraplength:
            kwargs["width"] = self._wraplength
        return x, y, kwargs

    def _draw_items(self):
        x, y, kwargs = self._item_kwargs(self._outline)
        for dx, dy in self.OFFSETS:
            item = self.create_text(x + dx, y + dy, **kwargs)
            self._outline_items.append(item)
        x, y, kwargs = self._item_kwargs(self._fg)
        self._main_item = self.create_text(x, y, **kwargs)

    def _refresh_geometry(self):
        self.update_idletasks()
        bbox = self.bbox("all")
        if not bbox:
            tk.Canvas.configure(self, width=1, height=1)
            return
        if self._wraplength:
            width = self._wraplength + 8
        else:
            width = max(1, bbox[2] - bbox[0] + 6)
        height = max(1, bbox[3] - bbox[1] + 6)
        tk.Canvas.configure(self, width=width, height=height)

    def configure(self, cnf=None, **kwargs):
        if cnf:
            kwargs.update(cnf)
        text = kwargs.pop("text", None)
        fg = kwargs.pop("fg", kwargs.pop("foreground", None))
        outline = kwargs.pop("outline", None)
        if text is not None:
            self._text = str(text)
            for item in self._outline_items:
                self.itemconfigure(item, text=self._text)
            self.itemconfigure(self._main_item, text=self._text)
        if fg is not None:
            self._fg = fg
            self.itemconfigure(self._main_item, fill=fg)
        if outline is not None:
            self._outline = outline
            for item in self._outline_items:
                self.itemconfigure(item, fill=outline)
        if kwargs:
            tk.Canvas.configure(self, **kwargs)
        if text is not None:
            self._refresh_geometry()

    config = configure

    def cget(self, key):
        if key == "text":
            return self._text
        if key in ("fg", "foreground"):
            return self._fg
        if key == "outline":
            return self._outline
        return tk.Canvas.cget(self, key)

    __getitem__ = cget


class CompactDesktopApp(DesktopApp):
    """Narrow frameless desktop widget using the approved Kyunghee artwork."""

    COMPACT_SIZE = (300, 430)
    DETAIL_SIZE = (410, 430)
    CHARACTER_MAX = (346, 384)
    BUBBLE_WRAP = 270

    FONT_FAMILY = "Pretendard"
    TIME_TEXT = "#13A45C"
    TIME_OUTLINE = "#07552F"
    STATUS_TEXT = "#11854B"
    STATUS_OUTLINE = "#064A2A"
    MESSAGE_TEXT = "#E05A88"
    MESSAGE_OUTLINE = "#7B304B"
    ESCAPE_TEXT = "#6B7280"

    def __init__(self):
        super().__init__()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", self.preferences.always_on_top)
        self.root.bind("<Escape>", self._emergency_hide)
        self._drag_origin = None

    def _label(self, parent, text="", size=10, weight="normal", fg=core.TEXT, bg=None, **kwargs):
        return tk.Label(
            parent,
            text=text,
            font=(self.FONT_FAMILY, size, "normal"),
            fg=fg,
            bg=bg or parent.cget("bg"),
            **kwargs,
        )

    def _button(self, parent, text, command, primary=False, width=None):
        button = super()._button(parent, text, command, primary=primary, width=width)
        button.configure(font=(self.FONT_FAMILY, 9, "normal"))
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

    def _emergency_hide(self, _event=None):
        """Immediately get the frameless widget out of the way; tray can restore it."""
        self.root.attributes("-topmost", False)
        self.root.withdraw()

    def apply_preferences(self, preferences) -> None:
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

        # Keep the larger artwork, but lower it so the timer no longer sits over Kyunghee's face.
        self.character = tk.Label(hero, bg=self.TRANSPARENT_KEY, bd=0, cursor="hand2")
        self.character.place(relx=0.5, rely=1.0, y=-18, anchor="s")

        clock = tk.Frame(hero, bg=self.TRANSPARENT_KEY, bd=0, highlightthickness=0, cursor="fleur")
        clock.place(x=6, y=6)
        self.cont = OutlinedText(
            clock,
            "00:00:00",
            family=self.FONT_FAMILY,
            size=16,
            weight="normal",
            fg=self.TIME_TEXT,
            outline=self.TIME_OUTLINE,
            bg=self.TRANSPARENT_KEY,
            cursor="fleur",
        )
        self.cont.pack(anchor="w")
        self.main_status = OutlinedText(
            clock,
            "집중 중",
            family=self.FONT_FAMILY,
            size=8,
            weight="normal",
            fg=self.STATUS_TEXT,
            outline=self.STATUS_OUTLINE,
            bg=self.TRANSPARENT_KEY,
            cursor="fleur",
        )
        self.main_status.pack(anchor="w", pady=(0, 1))
        for widget in (clock, self.cont, self.main_status):
            self._bind_drag_surface(widget)

        # Emergency escape remains text-only to preserve the transparent widget look.
        self.escape_control = tk.Label(
            hero,
            text="×",
            font=(self.FONT_FAMILY, 12, "normal"),
            fg=self.ESCAPE_TEXT,
            bg=self.TRANSPARENT_KEY,
            bd=0,
            highlightthickness=0,
            cursor="hand2",
        )
        self.escape_control.place(relx=1.0, x=-8, y=5, anchor="ne")
        self.escape_control.bind("<Button-1>", self._emergency_hide)

        self.speech = OutlinedText(
            hero,
            pick("playful"),
            family=self.FONT_FAMILY,
            size=10,
            weight="normal",
            fg=self.MESSAGE_TEXT,
            outline=self.MESSAGE_OUTLINE,
            bg=self.TRANSPARENT_KEY,
            wraplength=self.BUBBLE_WRAP,
            justify="center",
            cursor="hand2",
        )
        self.speech.place(relx=0.5, rely=1.0, y=-3, anchor="s")

        self.character.bind("<Button-1>", lambda _event: self.show_stats())
        self.speech.bind("<Button-1>", self._cycle_message)

    def _update_ui(self):
        super()._update_ui()
        away = self.state.session.is_away
        self.main_status.configure(
            text="자리비움 중" if away else "집중 중",
            fg=core.AMBER if away else self.STATUS_TEXT,
            outline="#7A4A00" if away else self.STATUS_OUTLINE,
        )


if __name__ == "__main__":
    singleton = SingleInstance()
    if not singleton.acquire():
        raise SystemExit(0)
    CompactDesktopApp().run()
