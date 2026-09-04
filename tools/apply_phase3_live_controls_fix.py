from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"missing patch target: {label}")
    return text.replace(old, new, 1)


path = Path("desktop_compact.py")
text = path.read_text(encoding="utf-8")

text = replace_once(text,
'''    def _scale(self, value: int | float) -> int:
        return max(1, round(float(value) * self.preferences.widget_scale / 100.0))
''',
'''    def _effective_widget_scale(self) -> int:
        var = getattr(self, "widget_scale_var", None)
        if var is not None:
            try:
                return int(var.get())
            except (tk.TclError, ValueError, TypeError):
                pass
        return self.preferences.widget_scale

    def _scale(self, value: int | float) -> int:
        return max(1, round(float(value) * self._effective_widget_scale() / 100.0))
''', "effective scale")

text = replace_once(text,
'''    def _apply_widget_appearance(self):
        if not hasattr(self, "cont"):
            return
        p = self.preferences
''',
'''    def _effective_display_flag(self, key: str) -> bool:
        vars_map = getattr(self, "display_bool_vars", None)
        if vars_map and key in vars_map:
            try:
                return bool(vars_map[key].get())
            except tk.TclError:
                pass
        return bool(getattr(self.preferences, key))

    def _preview_widget_controls(self, _value=None):
        if not hasattr(self, "cont"):
            return
        self._image_cache.clear()
        self._apply_widget_appearance()
        self.character_role = None
        self._set_character("default")
        # Keep the settings panel usable while previewing. The timer window size
        # is recalculated when the user returns to the timer page.
        if self.current_page == "timer":
            self._resize_for_page("timer")

    def _apply_widget_appearance(self):
        if not hasattr(self, "cont"):
            return
        p = self.preferences
''', "preview helpers")

text = text.replace('''        if p.show_time:\n''', '''        if self._effective_display_flag("show_time"):\n''', 1)
text = text.replace('''        if p.show_status:\n''', '''        if self._effective_display_flag("show_status"):\n''', 1)
text = text.replace('''        if p.show_message:\n''', '''        if self._effective_display_flag("show_message"):\n''', 1)

text = replace_once(text,
'''            command=lambda value: self.widget_scale_value.configure(text=f"{int(float(value))}%"),
''',
'''            command=lambda value: (
                self.widget_scale_value.configure(text=f"{int(float(value))}%"),
                self._preview_widget_controls(value),
            ),
''', "scale live preview")

text = replace_once(text,
'''            tk.Checkbutton(
                content, text=caption, variable=self.display_bool_vars[key],
                font=(self.FONT_FAMILY, 9, "normal"), fg=core.TEXT, bg=core.PANEL,
                activeforeground=core.TEXT, activebackground=core.PANEL,
                selectcolor=core.PANEL_2, highlightthickness=0, bd=0, cursor="hand2",
            ).pack(anchor="w", pady=1, **pad)
''',
'''            tk.Checkbutton(
                content, text=caption, variable=self.display_bool_vars[key],
                command=self._preview_widget_controls,
                font=(self.FONT_FAMILY, 9, "normal"), fg=core.TEXT, bg=core.PANEL,
                activeforeground=core.TEXT, activebackground=core.PANEL,
                selectcolor=core.PANEL_2, highlightthickness=0, bd=0, cursor="hand2",
            ).pack(anchor="w", pady=1, **pad)
''', "visibility live preview")

# When returning to the timer page, use the live scale even before Save is pressed.
text = replace_once(text,
'''    def _save_settings(self):
''',
'''    def _show_page(self, name: str):
        super()._show_page(name)
        if name == "timer":
            self._preview_widget_controls()
            self._resize_for_page("timer")

    def _save_settings(self):
''', "show page live preview")

path.write_text(text, encoding="utf-8")
