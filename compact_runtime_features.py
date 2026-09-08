from __future__ import annotations

import random
from pathlib import Path
from types import MethodType
import tkinter as tk
from tkinter import ttk

from PIL import Image, ImageTk

import app as core
import asset_manager
from desktop_app import DesktopApp


_INSTALLED = False


class StableOptionMenu(ttk.Combobox):
    """Readonly combobox with the small OptionMenu API used by the compact UI."""

    def __init__(self, master, variable, value, *values, **kwargs):
        command = kwargs.pop("command", None)
        width = kwargs.pop("width", None)
        options = (value, *values)
        init_kwargs = {
            "textvariable": variable,
            "values": options,
            "state": "readonly",
        }
        if width is not None:
            init_kwargs["width"] = width
        super().__init__(master, **init_kwargs)
        self._selection_command = command
        self.bind("<<ComboboxSelected>>", self._on_selected, add="+")

    def _on_selected(self, _event=None):
        if self._selection_command is not None:
            self._selection_command(self.get())


def _topmost_value(value) -> bool:
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"1", "true", "yes", "on"}:
            return True
        if text in {"0", "false", "no", "off", ""}:
            return False
    return bool(value)


def _install_topmost_guard() -> None:
    original = tk.Wm.wm_attributes
    if getattr(original, "_kyunghee_idempotent_topmost", False):
        return

    def guarded(self, *args):
        if len(args) == 1 and args[0] == "-topmost":
            result = original(self, *args)
            try:
                self._kyunghee_last_topmost = _topmost_value(result)
            except Exception:
                pass
            return result

        if len(args) >= 2 and args[0] == "-topmost":
            requested = _topmost_value(args[1])
            known = getattr(self, "_kyunghee_last_topmost", None)
            if known is None:
                try:
                    known = _topmost_value(original(self, "-topmost"))
                except Exception:
                    known = None
            if known is not None and known == requested:
                return ""
            result = original(self, *args)
            try:
                self._kyunghee_last_topmost = requested
            except Exception:
                pass
            return result

        return original(self, *args)

    guarded._kyunghee_idempotent_topmost = True
    tk.Wm.wm_attributes = guarded
    tk.Wm.attributes = guarded


def _install_stable_option_menu() -> None:
    if tk.OptionMenu is not StableOptionMenu:
        tk.OptionMenu = StableOptionMenu


def _gallery_candidates() -> list[Path]:
    root = Path(asset_manager.ASSET_DIR)
    candidates: list[Path] = []
    for role in asset_manager.VARIANT_FOLDERS:
        folder = root / role
        if not folder.is_dir():
            continue
        candidates.extend(path for path in folder.glob("*.png") if path.is_file())
    return sorted(set(candidates), key=lambda path: str(path).lower())


def _render_gallery_image(app, path: Path) -> bool:
    try:
        max_size = (
            app._scale(app.CHARACTER_MAX[0]),
            app._scale(app.CHARACTER_MAX[1]),
        )
        with Image.open(path) as src:
            image = src.convert("RGBA")
            image.thumbnail(max_size, Image.Resampling.LANCZOS)

        cleaner = getattr(app, "_clean_character_alpha", None)
        if cleaner is not None:
            image = cleaner(image)

        alpha_bbox = image.getchannel("A").getbbox()
        app._character_alpha_bbox = alpha_bbox or (0, 0, image.width, image.height)
        app.character_photo = ImageTk.PhotoImage(image)
        app.character.configure(image=app.character_photo)
        return True
    except Exception:
        core.log.exception("random gallery asset failed: %s", path)
        return False


def _refresh_gallery_controls(app) -> None:
    try:
        app.random_gallery_control.place(x=18, y=14, anchor="nw")
        if app._random_gallery_active:
            app.random_gallery_restore.place(x=53, y=14, anchor="nw")
        else:
            app.random_gallery_restore.place_forget()
    except (AttributeError, tk.TclError):
        pass


def _refresh_timer_layout(app) -> None:
    try:
        app._apply_widget_appearance()
        if getattr(app, "current_page", None) == "timer":
            app._resize_for_page("timer")
    except Exception:
        core.log.exception("compact timer layout refresh failed")


def _show_random_gallery_image(app, _event=None):
    candidates = _gallery_candidates()
    if not candidates:
        return "break"

    previous = getattr(app, "_random_gallery_last_path", None)
    if previous and len(candidates) > 1:
        candidates = [path for path in candidates if str(path) != previous] or candidates

    random.SystemRandom().shuffle(candidates)
    selected = None
    for path in candidates:
        if _render_gallery_image(app, path):
            selected = path
            break
    if selected is None:
        return "break"

    if not app._random_gallery_active:
        app._random_gallery_state_role = getattr(app, "character_role", None) or "default"
    app._random_gallery_active = True
    app._random_gallery_last_path = str(selected)

    _refresh_timer_layout(app)
    _refresh_gallery_controls(app)
    return "break"


def _restore_state_image(app, _event=None):
    if not getattr(app, "_random_gallery_active", False):
        return "break"

    role = getattr(app, "_random_gallery_state_role", None) or "default"
    app._random_gallery_active = False
    app._random_gallery_last_path = None
    app.character_role = None
    app._random_gallery_original_set_character(role)

    _refresh_timer_layout(app)
    _refresh_gallery_controls(app)
    return "break"


def _install_dynamic_timer_layout(app) -> None:
    """Size the compact timer from the currently visible character silhouette.

    The window remains asset-dependent, but a short/seated/profile asset no longer
    inherits the historical 610px full-body minimum height. The character, status
    group and message keep the existing anchor rules; only the required window
    height is recomputed from the rendered image's visible top edge.
    """
    if app.__class__.__name__ != "CompactDesktopApp":
        return
    if getattr(app, "_dynamic_timer_layout_installed", False):
        return
    if not hasattr(app, "_timer_size"):
        return

    app._dynamic_timer_layout_installed = True
    original_timer_size = app._timer_size
    app._dynamic_timer_original_timer_size = original_timer_size

    def dynamic_timer_size(self):
        width, _historical_height = original_timer_size()

        try:
            _image_width, image_height = self._character_render_size()
            _visible_left, visible_top, _visible_right, _visible_bottom = self._character_visible_bounds()
            bottom_gap = self._character_bottom_gap()

            top_clearance = max(42, self._scale(34))
            visible_extent_to_label_bottom = max(1, image_height - visible_top)
            required_height = top_clearance + bottom_gap + visible_extent_to_label_bottom

            minimum_height = max(300, self._scale(250))
            height = max(minimum_height, round(required_height))
            return width, height
        except Exception:
            core.log.exception("dynamic timer size calculation failed")
            return original_timer_size()

    app._timer_size = MethodType(dynamic_timer_size, app)


def _install_random_gallery(app) -> None:
    if app.__class__.__name__ != "CompactDesktopApp":
        return
    if getattr(app, "_random_gallery_installed", False):
        return
    if not hasattr(app, "hero") or not hasattr(app, "character"):
        return

    app._random_gallery_installed = True
    app._random_gallery_active = False
    app._random_gallery_last_path = None
    app._random_gallery_state_role = getattr(app, "character_role", None) or "default"
    app._random_gallery_original_set_character = app._set_character

    original_set_character = app._set_character

    def random_aware_set_character(self, role: str):
        if getattr(self, "_random_gallery_active", False):
            self._random_gallery_state_role = role
            return

        before = getattr(self, "character_role", None)
        result = original_set_character(role)
        after = getattr(self, "character_role", None)
        if before != after:
            _refresh_timer_layout(self)
        return result

    app._set_character = MethodType(random_aware_set_character, app)

    app.random_gallery_control = tk.Label(
        app.hero,
        text="🎲",
        font=("Segoe UI Emoji", 11, "normal"),
        fg=app.ESCAPE_TEXT,
        bg=app.TRANSPARENT_KEY,
        bd=0,
        highlightthickness=0,
        cursor="hand2",
    )
    app.random_gallery_control.bind(
        "<Button-1>", lambda event: _show_random_gallery_image(app, event)
    )

    app.random_gallery_restore = tk.Label(
        app.hero,
        text="↩",
        font=(app.FONT_FAMILY, 12, "normal"),
        fg=app.ESCAPE_TEXT,
        bg=app.TRANSPARENT_KEY,
        bd=0,
        highlightthickness=0,
        cursor="hand2",
    )
    app.random_gallery_restore.bind(
        "<Button-1>", lambda event: _restore_state_image(app, event)
    )
    _refresh_gallery_controls(app)


def _install_desktop_init_hook() -> None:
    original = DesktopApp.__init__
    if getattr(original, "_kyunghee_compact_features", False):
        return

    def wrapped(self, *args, **kwargs):
        original(self, *args, **kwargs)
        _install_dynamic_timer_layout(self)
        _install_random_gallery(self)
        _refresh_timer_layout(self)

    wrapped._kyunghee_compact_features = True
    DesktopApp.__init__ = wrapped


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _install_topmost_guard()
    _install_stable_option_menu()
    _install_desktop_init_hook()
    _INSTALLED = True
