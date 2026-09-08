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

    try:
        app._apply_widget_appearance()
        if getattr(app, "current_page", None) == "timer":
            app._resize_for_page("timer")
    except Exception:
        core.log.exception("random gallery layout refresh failed")

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

    try:
        app._apply_widget_appearance()
        if getattr(app, "current_page", None) == "timer":
            app._resize_for_page("timer")
    except Exception:
        core.log.exception("state image restore layout refresh failed")

    _refresh_gallery_controls(app)
    return "break"


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
        return original_set_character(role)

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
        _install_random_gallery(self)

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
