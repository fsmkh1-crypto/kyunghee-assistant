from pathlib import Path

path = Path("desktop_compact.py")
text = path.read_text(encoding="utf-8")


def replace_once(old: str, new: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"expected one match, found {count}: {old[:160]!r}")
    text = text.replace(old, new, 1)


replace_once(
'''    ROLE_TO_SETTING = {
        "default": "default", "playful": "default",
        "cheer": "cheer", "cute_cheer": "cheer",
        "rest": "rest", "away": "away",
        "worry": "warning", "nag": "warning",
        "praise": "leave", "stats": "stats",
        "settings": "settings", "alert": "alert",
        "master_face": "profile",
    }
''',
'''    ROLE_TO_SETTING = {
        "default": "default", "playful": "default",
        "cheer": "cheer", "cute_cheer": "cheer",
        "rest": "rest", "away": "away",
        "worry": "warning", "nag": "warning",
        "praise": "leave", "stats": "stats",
        "settings": "settings", "alert": "alert",
        "master_face": "profile",
    }
    SETTING_TO_CANONICAL_ROLE = {
        "default": "default",
        "cheer": "cheer",
        "rest": "rest",
        "away": "away",
        "warning": "worry",
        "leave": "praise",
        "stats": "stats",
        "settings": "settings",
        "alert": "alert",
        "profile": "master_face",
    }
'''
)

replace_once(
'''        self._image_cache = {}
        self._image_set_store = ImageSetStore(USER_IMAGE_SET_DIR)
        self._image_set_choices = {}
        self._presentation_suppressed = False
''',
'''        self._image_cache = {}
        self._image_set_store = ImageSetStore(USER_IMAGE_SET_DIR)
        self._image_set_choices = {}
        self._settings_preview_cache = {}
        self._settings_preview_role = "default"
        self._settings_preview_indices = {}
        self._presentation_suppressed = False
'''
)

insert_before = '''    def _choose_image(self, key):
'''
preview_methods = '''    def _settings_preview_sources(self, key: str):
        set_images = list(self._image_set_store.list_images(key))
        if set_images:
            return set_images, "세트"
        value = self.image_path_vars[key].get() if hasattr(self, "image_path_vars") else getattr(
            self.preferences, f"image_{key}", ""
        )
        legacy = self._stored_image_path(value)
        if legacy and legacy.is_file():
            return [legacy], "한 장"
        role = self.SETTING_TO_CANONICAL_ROLE.get(key, "default")
        canonical = resolve_asset(role)
        return ([canonical] if canonical else []), "기본 이미지"

    def _settings_preview_style(self, key: str):
        mode_label = self.image_mode_vars[key].get() if hasattr(self, "image_mode_vars") else "자동 맞춤"
        mode = "crop" if mode_label == "가운데 크롭" else "fit"
        alignment_labels = {
            "가운데": "center", "위": "top", "아래": "bottom",
            "왼쪽": "left", "오른쪽": "right",
            "왼쪽 위": "top_left", "오른쪽 위": "top_right",
            "왼쪽 아래": "bottom_left", "오른쪽 아래": "bottom_right",
        }
        alignment_label = self.image_alignment_vars[key].get() if hasattr(self, "image_alignment_vars") else "가운데"
        alignment = alignment_labels.get(alignment_label, "center")
        return mode, alignment

    def _invalidate_settings_preview(self, key=None):
        if key is None:
            self._settings_preview_cache.clear()
            return
        prefix = str(key)
        self._settings_preview_cache = {
            cache_key: image for cache_key, image in self._settings_preview_cache.items()
            if cache_key[0] != prefix
        }

    def _render_settings_preview(self, key=None):
        if not hasattr(self, "settings_preview_image"):
            return
        key = key or self._settings_preview_role
        self._settings_preview_role = key
        sources, source_kind = self._settings_preview_sources(key)
        caption = dict(self.IMAGE_ROWS).get(key, key)
        if not sources:
            self.settings_preview_image.configure(image="", text="이미지 없음")
            self.settings_preview_image.image = None
            self.settings_preview_title.configure(text=caption)
            self.settings_preview_meta.configure(text="미리볼 수 있는 이미지가 없습니다.")
            self.settings_preview_prev.configure(state="disabled")
            self.settings_preview_next.configure(state="disabled")
            return

        index = self._settings_preview_indices.get(key, 0) % len(sources)
        self._settings_preview_indices[key] = index
        source = sources[index]
        mode, alignment = self._settings_preview_style(key)
        try:
            stat = source.stat()
            stat_key = (stat.st_mtime_ns, stat.st_size)
        except OSError:
            stat_key = (0, 0)
        cache_key = (key, str(source), stat_key, mode, alignment)
        preview = self._settings_preview_cache.get(cache_key)
        if preview is None:
            with Image.open(source) as src:
                rendered = resize_rgba_alpha_safe(
                    src,
                    (150, 180),
                    crop=(mode == "crop" and source_kind != "기본 이미지"),
                    centering=self._alignment_center(alignment),
                )
                canvas = Image.new("RGBA", (150, 180), core.PANEL_2)
                x = (150 - rendered.width) // 2
                y = (180 - rendered.height) // 2
                canvas.alpha_composite(rendered, (x, y))
                preview = canvas.convert("RGB")
            self._settings_preview_cache[cache_key] = preview.copy()

        photo = ImageTk.PhotoImage(preview)
        self.settings_preview_image.configure(image=photo, text="")
        self.settings_preview_image.image = photo
        self.settings_preview_title.configure(text=caption)
        if len(sources) > 1:
            meta = f"{source_kind} · {index + 1}/{len(sources)} · {source.name}"
        else:
            meta = f"{source_kind} · {source.name}"
        self.settings_preview_meta.configure(text=meta)
        nav_state = "normal" if len(sources) > 1 else "disabled"
        self.settings_preview_prev.configure(state=nav_state)
        self.settings_preview_next.configure(state=nav_state)

    def _select_settings_preview(self, key: str):
        self._settings_preview_role = key
        self._render_settings_preview(key)

    def _step_settings_preview(self, delta: int):
        key = self._settings_preview_role
        sources, _source_kind = self._settings_preview_sources(key)
        if not sources:
            return
        current = self._settings_preview_indices.get(key, 0)
        self._settings_preview_indices[key] = (current + delta) % len(sources)
        self._render_settings_preview(key)

'''
replace_once(insert_before, preview_methods + insert_before)

for marker in [
'''            self.image_name_vars[key].set(destination.name)
            self._image_cache.clear()
''',
'''            self.image_name_vars[key].set(f"{len(config.images)}장 세트")
            self._image_cache.clear()
            self._image_set_choices.clear()
''',
'''            self.image_name_vars[key].set(f"{len(config.images)}장 세트")
            self._image_cache.clear()
            self._image_set_choices.clear()
''',
]:
    replacement = marker.replace(
        '''            self._image_cache.clear()\n''',
        '''            self._image_cache.clear()\n            self._invalidate_settings_preview(key)\n            self._settings_preview_indices[key] = 0\n            self._select_settings_preview(key)\n'''
    )
    if text.count(marker):
        text = text.replace(marker, replacement, 1)

replace_once(
'''        self._image_set_choices.clear()
        self._image_cache.clear()
        self._remove_legacy_image_files(key)

    def _image_display_name(self, key, value):
''',
'''        self._image_set_choices.clear()
        self._image_cache.clear()
        self._invalidate_settings_preview(key)
        self._settings_preview_indices[key] = 0
        self._remove_legacy_image_files(key)
        self._select_settings_preview(key)

    def _image_display_name(self, key, value):
'''
)

replace_once(
'''        self.image_path_vars = {}
        self.image_name_vars = {}
        self.image_mode_vars = {}
        self.image_alignment_vars = {}
        alignment_labels = {
''',
'''        self.image_path_vars = {}
        self.image_name_vars = {}
        self.image_mode_vars = {}
        self.image_alignment_vars = {}

        preview_box = tk.Frame(content, bg=core.PANEL_2, bd=0, highlightthickness=0)
        preview_box.pack(fill="x", padx=14, pady=(2, 9), ipady=8)
        self.settings_preview_image = tk.Label(
            preview_box, width=150, height=180, bg=core.PANEL_2,
            fg=core.MUTED, text="미리보기", compound="center", bd=0,
            font=(self.FONT_FAMILY, 9, "normal"),
        )
        self.settings_preview_image.pack(side="left", padx=(8, 12), pady=8)
        preview_info = tk.Frame(preview_box, bg=core.PANEL_2)
        preview_info.pack(side="left", fill="both", expand=True, padx=(0, 8), pady=10)
        self.settings_preview_title = self._label(preview_info, "평상시", size=10, bg=core.PANEL_2)
        self.settings_preview_title.pack(anchor="w")
        self.settings_preview_meta = self._label(
            preview_info, "", size=8, fg=core.MUTED, bg=core.PANEL_2, wraplength=350, justify="left"
        )
        self.settings_preview_meta.pack(anchor="w", pady=(4, 8))
        preview_nav = tk.Frame(preview_info, bg=core.PANEL_2)
        preview_nav.pack(anchor="w")
        self.settings_preview_prev = self._button(preview_nav, "이전", lambda: self._step_settings_preview(-1))
        self.settings_preview_prev.pack(side="left", padx=(0, 5))
        self.settings_preview_next = self._button(preview_nav, "다음", lambda: self._step_settings_preview(1))
        self.settings_preview_next.pack(side="left")

        alignment_labels = {
'''
)

replace_once(
'''            tk.OptionMenu(options, self.image_mode_vars[key], "자동 맞춤", "가운데 크롭").pack(side="left", padx=(0, 5))
            self._label(options, "정렬", size=8, fg=core.MUTED, bg=core.PANEL).pack(side="left", padx=(5, 3))
            tk.OptionMenu(
                options, self.image_alignment_vars[key],
                "가운데", "위", "아래", "왼쪽", "오른쪽",
                "왼쪽 위", "오른쪽 위", "왼쪽 아래", "오른쪽 아래",
            ).pack(side="left")

        self._label(content, "퇴근 시간", size=11, bg=core.PANEL).pack(anchor="w", pady=(16, 4), **pad)
''',
'''            tk.OptionMenu(
                options, self.image_mode_vars[key], "자동 맞춤", "가운데 크롭",
                command=lambda _value, k=key: self._select_settings_preview(k),
            ).pack(side="left", padx=(0, 5))
            self._label(options, "정렬", size=8, fg=core.MUTED, bg=core.PANEL).pack(side="left", padx=(5, 3))
            tk.OptionMenu(
                options, self.image_alignment_vars[key],
                "가운데", "위", "아래", "왼쪽", "오른쪽",
                "왼쪽 위", "오른쪽 위", "왼쪽 아래", "오른쪽 아래",
                command=lambda _value, k=key: self._select_settings_preview(k),
            ).pack(side="left")
            self._button(options, "미리보기", lambda k=key: self._select_settings_preview(k)).pack(side="left", padx=(7, 0))

        self._render_settings_preview("default")

        self._label(content, "퇴근 시간", size=11, bg=core.PANEL).pack(anchor="w", pady=(16, 4), **pad)
'''
)

replace_once(
'''    def apply_preferences(self, preferences) -> None:
        self._image_cache.clear()
        self._image_set_store.invalidate()
''',
'''    def apply_preferences(self, preferences) -> None:
        self._image_cache.clear()
        self._settings_preview_cache.clear()
        self._image_set_store.invalidate()
'''
)

path.write_text(text, encoding="utf-8")
