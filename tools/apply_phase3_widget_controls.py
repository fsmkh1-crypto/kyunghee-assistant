from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"missing patch target: {label}")
    return text.replace(old, new, 1)


path = Path("desktop_compact.py")
text = path.read_text(encoding="utf-8")

text = replace_once(text,
'''    def _resize_for_page(self, name: str):
        if name == "timer":
            width, height = self.COMPACT_SIZE
        elif name == "settings":
            width, height = self.SETTINGS_SIZE
        else:
            width, height = self.DETAIL_SIZE
''',
'''    def _scale(self, value: int | float) -> int:
        return max(1, round(float(value) * self.preferences.widget_scale / 100.0))

    def _timer_size(self):
        return self._scale(self.COMPACT_SIZE[0]), self._scale(self.COMPACT_SIZE[1])

    def _resize_for_page(self, name: str):
        if name == "timer":
            width, height = self._timer_size()
        elif name == "settings":
            width, height = self.SETTINGS_SIZE
        else:
            width, height = self.DETAIL_SIZE
''', "scale resize")

text = replace_once(text,
'''    def apply_preferences(self, preferences) -> None:
        self._image_cache.clear()
        super().apply_preferences(preferences)
        self._apply_widget_appearance()
        self.character_role = None
        self._set_character("default")
''',
'''    def apply_preferences(self, preferences) -> None:
        self._image_cache.clear()
        super().apply_preferences(preferences)
        self._apply_widget_appearance()
        self.character_role = None
        self._set_character("default")
        self._resize_for_page(self.current_page)
''', "apply preferences resize")

text = replace_once(text,
'''            image = self._load_character_image(role, self.CHARACTER_MAX, preserve_alpha=True)
''',
'''            max_size = (self._scale(self.CHARACTER_MAX[0]), self._scale(self.CHARACTER_MAX[1]))
            image = self._load_character_image(role, max_size, preserve_alpha=True)
''', "scaled character")

text = replace_once(text,
'''        hero = tk.Frame(page, bg=self.TRANSPARENT_KEY, bd=0, highlightthickness=0)
        hero.pack(fill="both", expand=True)

        self.character = tk.Label(hero, bg=self.TRANSPARENT_KEY, bd=0, cursor="hand2")
        self.character.place(relx=0.5, rely=1.0, y=-18, anchor="s")

        p = self.preferences
        clock = tk.Frame(hero, bg=self.TRANSPARENT_KEY, bd=0, highlightthickness=0, cursor="fleur")
        clock.place(x=6, y=6)
''',
'''        hero = tk.Frame(page, bg=self.TRANSPARENT_KEY, bd=0, highlightthickness=0)
        hero.pack(fill="both", expand=True)
        self.hero = hero

        # Always keep a small invisible drag surface, even when time/status are hidden.
        self.drag_strip = tk.Frame(hero, bg=self.TRANSPARENT_KEY, bd=0, highlightthickness=0, cursor="fleur")
        self.drag_strip.place(x=0, y=0, relwidth=1.0, height=18)
        self._bind_drag_surface(self.drag_strip)

        self.character = tk.Label(hero, bg=self.TRANSPARENT_KEY, bd=0, cursor="hand2")
        self.character.place(relx=0.5, rely=1.0, y=-self._scale(18), anchor="s")

        p = self.preferences
        clock = tk.Frame(hero, bg=self.TRANSPARENT_KEY, bd=0, highlightthickness=0, cursor="fleur")
        self.clock = clock
        clock.place(x=self._scale(6), y=self._scale(6))
''', "timer hero controls")

text = replace_once(text,
'''            clock, "00:00:00", family=self.FONT_FAMILY, size=p.time_text_size,
''',
'''            clock, "00:00:00", family=self.FONT_FAMILY, size=self._scale(p.time_text_size),
''', "scaled time font")
text = replace_once(text,
'''            clock, "집중 중", family=self.FONT_FAMILY, size=p.status_text_size,
''',
'''            clock, "집중 중", family=self.FONT_FAMILY, size=self._scale(p.status_text_size),
''', "scaled status font")
text = replace_once(text,
'''            hero, text="×", font=(self.FONT_FAMILY, 12, "normal"),
''',
'''            hero, text="×", font=(self.FONT_FAMILY, self._scale(12), "normal"),
''', "scaled close")
text = replace_once(text,
'''        self.escape_control.place(relx=1.0, x=-8, y=5, anchor="ne")
''',
'''        self.escape_control.place(relx=1.0, x=-self._scale(8), y=self._scale(5), anchor="ne")
''', "close placement")
text = replace_once(text,
'''            hero, pick("playful"), family=self.FONT_FAMILY, size=p.message_text_size,
''',
'''            hero, pick("playful"), family=self.FONT_FAMILY, size=self._scale(p.message_text_size),
''', "scaled message font")
text = replace_once(text,
'''            bg=self.TRANSPARENT_KEY, wraplength=self.BUBBLE_WRAP,
''',
'''            bg=self.TRANSPARENT_KEY, wraplength=self._scale(self.BUBBLE_WRAP),
''', "scaled wrap")
text = replace_once(text,
'''        self.speech.place(relx=0.5, rely=1.0, y=-3, anchor="s")

        self.character.bind("<Button-1>", lambda _event: self.show_stats())
''',
'''        self.speech.place(relx=0.5, rely=1.0, y=-self._scale(3), anchor="s")

        self.character.bind("<Button-1>", lambda _event: self.show_stats())
''', "message placement")

text = replace_once(text,
'''        self.cont.set_style(
            size=p.time_text_size, fg=p.time_text_color,
            outline=_outline_for(p.time_text_color),
        )
        self.main_status.set_style(
            size=p.status_text_size, fg=p.status_text_color,
            outline=_outline_for(p.status_text_color),
        )
        self.speech.set_style(
            size=p.message_text_size, fg=p.message_text_color,
            outline=_outline_for(p.message_text_color),
        )
''',
'''        self.cont.set_style(
            size=self._scale(p.time_text_size), fg=p.time_text_color,
            outline=_outline_for(p.time_text_color),
        )
        self.main_status.set_style(
            size=self._scale(p.status_text_size), fg=p.status_text_color,
            outline=_outline_for(p.status_text_color),
        )
        self.speech.set_style(
            size=self._scale(p.message_text_size), fg=p.message_text_color,
            outline=_outline_for(p.message_text_color),
        )

        if p.show_time:
            if not self.cont.winfo_manager():
                self.cont.pack(anchor="w")
        else:
            self.cont.pack_forget()
        if p.show_status:
            if not self.main_status.winfo_manager():
                self.main_status.pack(anchor="w", pady=(0, 1))
        else:
            self.main_status.pack_forget()
        if p.show_message:
            self.speech.place(relx=0.5, rely=1.0, y=-self._scale(3), anchor="s")
        else:
            self.speech.place_forget()

        self.clock.place(x=self._scale(6), y=self._scale(6))
        self.character.place(relx=0.5, rely=1.0, y=-self._scale(18), anchor="s")
        self.escape_control.configure(font=(self.FONT_FAMILY, self._scale(12), "normal"))
        self.escape_control.place(relx=1.0, x=-self._scale(8), y=self._scale(5), anchor="ne")
''', "appearance visibility")

text = replace_once(text,
'''        self._label(content, "위젯 글자", size=11, bg=core.PANEL).pack(anchor="w", pady=(14, 4), **pad)
''',
'''        self._label(content, "위젯 표시", size=11, bg=core.PANEL).pack(anchor="w", pady=(14, 4), **pad)
        scale_row = tk.Frame(content, bg=core.PANEL)
        scale_row.pack(fill="x", pady=(0, 5), **pad)
        self._label(scale_row, "전체 크기", size=9, bg=core.PANEL).pack(side="left")
        self.widget_scale_var = tk.IntVar(value=p.widget_scale)
        self.widget_scale_value = self._label(scale_row, f"{p.widget_scale}%", size=9, fg=core.MUTED, bg=core.PANEL)
        self.widget_scale_value.pack(side="right")
        scale = tk.Scale(
            content, from_=80, to=140, orient="horizontal", resolution=5,
            variable=self.widget_scale_var, showvalue=False, length=360,
            fg=core.TEXT, bg=core.PANEL, troughcolor=core.PANEL_2,
            highlightthickness=0, bd=0,
            command=lambda value: self.widget_scale_value.configure(text=f"{int(float(value))}%"),
        )
        scale.pack(anchor="w", pady=(0, 4), **pad)
        self.display_bool_vars = {
            "show_time": tk.BooleanVar(value=p.show_time),
            "show_status": tk.BooleanVar(value=p.show_status),
            "show_message": tk.BooleanVar(value=p.show_message),
        }
        for key, caption in (
            ("show_time", "시간 표시"),
            ("show_status", "상태 표시"),
            ("show_message", "메시지 표시"),
        ):
            tk.Checkbutton(
                content, text=caption, variable=self.display_bool_vars[key],
                font=(self.FONT_FAMILY, 9, "normal"), fg=core.TEXT, bg=core.PANEL,
                activeforeground=core.TEXT, activebackground=core.PANEL,
                selectcolor=core.PANEL_2, highlightthickness=0, bd=0, cursor="hand2",
            ).pack(anchor="w", pady=1, **pad)
        self._label(
            content,
            "시간과 상태를 모두 꺼도 위쪽 투명 드래그 영역으로 창을 이동할 수 있습니다.",
            size=8, fg=core.MUTED, bg=core.PANEL,
        ).pack(anchor="w", pady=(2, 4), **pad)

        self._label(content, "위젯 글자", size=11, bg=core.PANEL).pack(anchor="w", pady=(14, 4), **pad)
''', "settings display section")

text = replace_once(text,
'''                window_x=self.preferences.window_x,
                window_y=self.preferences.window_y,
                time_text_size=int(self.style_size_vars["time"].get()),
''',
'''                window_x=self.preferences.window_x,
                window_y=self.preferences.window_y,
                widget_scale=int(self.widget_scale_var.get()),
                show_time=self.display_bool_vars["show_time"].get(),
                show_status=self.display_bool_vars["show_status"].get(),
                show_message=self.display_bool_vars["show_message"].get(),
                time_text_size=int(self.style_size_vars["time"].get()),
''', "save display prefs")

# Ensure initial visibility is applied after widgets are built.
text = replace_once(text,
'''        self.character.bind("<Button-1>", lambda _event: self.show_stats())
        self.speech.bind("<Button-1>", self._cycle_message)
''',
'''        self.character.bind("<Button-1>", lambda _event: self.show_stats())
        self.speech.bind("<Button-1>", self._cycle_message)
        self._apply_widget_appearance()
''', "initial appearance")

path.write_text(text, encoding="utf-8")

# Update tests for schema 4 and new preferences.
test_path = Path("tests/test_settings.py")
test = test_path.read_text(encoding="utf-8")
test = test.replace('["schema_version"], 3)', '["schema_version"], 4)')
if 'test_widget_display_preferences_round_trip' not in test:
    marker = '\n\nif __name__ == "__main__":\n'
    addition = '''\n    def test_widget_display_preferences_round_trip(self):\n        parsed = settings_from_dict({\n            "widget_scale": 125,\n            "show_time": False,\n            "show_status": True,\n            "show_message": False,\n        })\n        self.assertEqual(parsed.widget_scale, 125)\n        self.assertFalse(parsed.show_time)\n        self.assertTrue(parsed.show_status)\n        self.assertFalse(parsed.show_message)\n\n    def test_bad_widget_scale_falls_back(self):\n        parsed = settings_from_dict({"widget_scale": 500})\n        self.assertEqual(parsed.widget_scale, UserSettings().widget_scale)\n'''
    if marker not in test:
        raise SystemExit("missing test insertion marker")
    test = test.replace(marker, addition + marker, 1)
test_path.write_text(test, encoding="utf-8")
