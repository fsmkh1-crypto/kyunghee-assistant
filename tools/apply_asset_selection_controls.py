from pathlib import Path


def replace_one(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding='utf-8')
    count = text.count(old)
    if count != 1:
        raise SystemExit(f'{label}: expected 1 match, found {count}')
    path.write_text(text.replace(old, new, 1), encoding='utf-8')


# 1) Settings persistence: one base built-in set plus per-role overrides.
path = Path('settings.py')
replace_one(
    path,
    '''def _fit_mode(value: object) -> str:\n    return str(value) if str(value) in {"fit", "crop"} else "fit"\n\n\ndef _color_or(value: object, default: str) -> str:\n''',
    '''def _fit_mode(value: object) -> str:\n    return str(value) if str(value) in {"fit", "crop"} else "fit"\n\n\ndef _builtin_set_choice(value: object, default: str = "random") -> str:\n    value = str(value).strip().lower()\n    if value == "random":\n        return "random"\n    if value.isdigit() and 1 <= int(value) <= 99:\n        return f"{int(value):02d}"\n    return default\n\n\ndef _builtin_override_choice(value: object) -> str:\n    value = str(value).strip()\n    if not value:\n        return ""\n    if value.isdigit() and 1 <= int(value) <= 99:\n        return f"{int(value):02d}"\n    return ""\n\n\ndef _color_or(value: object, default: str) -> str:\n''',
    'settings helpers',
)
replace_one(
    path,
    '''    image_default: str = ""\n    image_cheer: str = ""\n''',
    '''    builtin_image_set: str = "random"\n    builtin_image_default: str = ""\n    builtin_image_cheer: str = ""\n    builtin_image_rest: str = ""\n    builtin_image_away: str = ""\n    builtin_image_warning: str = ""\n    builtin_image_leave: str = ""\n    builtin_image_stats: str = ""\n    builtin_image_settings: str = ""\n    builtin_image_alert: str = ""\n    builtin_image_profile: str = ""\n\n    image_default: str = ""\n    image_cheer: str = ""\n''',
    'settings dataclass fields',
)
replace_one(
    path,
    '''        if self.personality not in PERSONALITIES:\n            raise ValueError("경희 말투 설정이 올바르지 않습니다.")\n        validate_custom_dialogue(self.custom_dialogue)\n''',
    '''        if self.personality not in PERSONALITIES:\n            raise ValueError("경희 말투 설정이 올바르지 않습니다.")\n        if _builtin_set_choice(self.builtin_image_set, "") != self.builtin_image_set:\n            raise ValueError("기본 내장 이미지 세트 설정이 올바르지 않습니다.")\n        for key in (\n            "default", "cheer", "rest", "away", "warning",\n            "leave", "stats", "settings", "alert", "profile",\n        ):\n            value = getattr(self, f"builtin_image_{key}")\n            if _builtin_override_choice(value) != value:\n                raise ValueError("역할별 내장 이미지 설정이 올바르지 않습니다.")\n        validate_custom_dialogue(self.custom_dialogue)\n''',
    'settings validation',
)
replace_one(
    path,
    '''        message_text_color=_color_or(raw.get("message_text_color"), d.message_text_color),\n        image_default=str(raw.get("image_default", "")),\n''',
    '''        message_text_color=_color_or(raw.get("message_text_color"), d.message_text_color),\n        builtin_image_set=_builtin_set_choice(raw.get("builtin_image_set", d.builtin_image_set), d.builtin_image_set),\n        builtin_image_default=_builtin_override_choice(raw.get("builtin_image_default", "")),\n        builtin_image_cheer=_builtin_override_choice(raw.get("builtin_image_cheer", "")),\n        builtin_image_rest=_builtin_override_choice(raw.get("builtin_image_rest", "")),\n        builtin_image_away=_builtin_override_choice(raw.get("builtin_image_away", "")),\n        builtin_image_warning=_builtin_override_choice(raw.get("builtin_image_warning", "")),\n        builtin_image_leave=_builtin_override_choice(raw.get("builtin_image_leave", "")),\n        builtin_image_stats=_builtin_override_choice(raw.get("builtin_image_stats", "")),\n        builtin_image_settings=_builtin_override_choice(raw.get("builtin_image_settings", "")),\n        builtin_image_alert=_builtin_override_choice(raw.get("builtin_image_alert", "")),\n        builtin_image_profile=_builtin_override_choice(raw.get("builtin_image_profile", "")),\n        image_default=str(raw.get("image_default", "")),\n''',
    'settings loader fields',
)

# 2) Built-in resolver: preserve old random session behavior while allowing explicit coherent sets and overrides.
path = Path('asset_manager.py')
replace_one(
    path,
    '''def resolve_asset(role: str, asset_dir: Path = ASSET_DIR) -> Path | None:\n    # User-imported image sets are resolved before this function by the desktop\n    # UI. Here, prefer one coherent built-in numbered set, then canonical/legacy.\n    set_number = select_session_set(asset_dir)\n    if set_number is not None:\n        numbered = variant_asset(role, set_number, asset_dir)\n        if numbered is not None:\n            return numbered\n    names = ROLE_FILES.get(role, ROLE_FILES["default"])\n    return first_existing(names, asset_dir)\n''',
    '''def resolve_asset_for_set(role: str, set_number: int, asset_dir: Path = ASSET_DIR) -> Path | None:\n    """Resolve one explicit built-in numbered set, then fall back safely."""\n    numbered = variant_asset(role, set_number, asset_dir)\n    if numbered is not None:\n        return numbered\n    names = ROLE_FILES.get(role, ROLE_FILES["default"])\n    return first_existing(names, asset_dir)\n\n\ndef resolve_asset(role: str, asset_dir: Path = ASSET_DIR) -> Path | None:\n    # User-imported image sets are resolved before this function by the desktop\n    # UI. Here, prefer one coherent built-in numbered set, then canonical/legacy.\n    set_number = select_session_set(asset_dir)\n    if set_number is not None:\n        return resolve_asset_for_set(role, set_number, asset_dir)\n    names = ROLE_FILES.get(role, ROLE_FILES["default"])\n    return first_existing(names, asset_dir)\n\n\ndef resolve_configured_asset(\n    role: str,\n    base_set: str = "random",\n    role_override: str = "",\n    asset_dir: Path = ASSET_DIR,\n) -> Path | None:\n    """Resolve role override > selected base set > process-stable random set."""\n    override_text = str(role_override).strip()\n    if override_text.isdigit() and 1 <= int(override_text) <= 99:\n        return resolve_asset_for_set(role, int(override_text), asset_dir)\n\n    base_text = str(base_set).strip().lower()\n    if base_text != "random" and base_text.isdigit() and 1 <= int(base_text) <= 99:\n        return resolve_asset_for_set(role, int(base_text), asset_dir)\n\n    return resolve_asset(role, asset_dir)\n''',
    'asset resolver',
)

# 3) Compact desktop UI + runtime priority.
path = Path('desktop_compact.py')
replace_one(
    path,
    'from asset_manager import resolve_asset\n',
    'from asset_manager import available_complete_sets, resolve_configured_asset\n',
    'desktop import',
)
replace_one(
    path,
    '''    def _stored_image_path(self, value: str):\n        if not value:\n            return None\n        path = Path(value).expanduser()\n        if not path.is_absolute():\n            path = USER_IMAGE_DIR / path\n        return path\n\n    def _custom_image(self, role: str):\n''',
    '''    def _stored_image_path(self, value: str):\n        if not value:\n            return None\n        path = Path(value).expanduser()\n        if not path.is_absolute():\n            path = USER_IMAGE_DIR / path\n        return path\n\n    @staticmethod\n    def _builtin_base_label(value: str) -> str:\n        return "랜덤" if str(value) == "random" else str(value)\n\n    @staticmethod\n    def _builtin_base_value(label: str) -> str:\n        return "random" if str(label) == "랜덤" else str(label)\n\n    @staticmethod\n    def _builtin_override_label(value: str) -> str:\n        return "세트 기본값" if not str(value) else str(value)\n\n    @staticmethod\n    def _builtin_override_value(label: str) -> str:\n        return "" if str(label) == "세트 기본값" else str(label)\n\n    def _resolve_builtin_asset(self, role: str, *, controls: bool = False):\n        key = self.ROLE_TO_SETTING.get(role, "default")\n        if controls and hasattr(self, "builtin_image_set_var") and hasattr(self, "image_builtin_vars"):\n            base_set = self._builtin_base_value(self.builtin_image_set_var.get())\n            role_override = self._builtin_override_value(self.image_builtin_vars[key].get())\n        else:\n            base_set = getattr(self.preferences, "builtin_image_set", "random")\n            role_override = getattr(self.preferences, f"builtin_image_{key}", "")\n        return resolve_configured_asset(role, base_set, role_override)\n\n    def _custom_image(self, role: str):\n''',
    'desktop built-in helpers',
)
replace_one(
    path,
    '''        custom, mode, centering = self._custom_image(role)\n        path = custom or resolve_asset(role)\n''',
    '''        custom, mode, centering = self._custom_image(role)\n        path = custom or self._resolve_builtin_asset(role)\n''',
    'runtime priority',
)
replace_one(
    path,
    '''        role = self.SETTING_TO_CANONICAL_ROLE.get(key, "default")\n        canonical = resolve_asset(role)\n        return ([canonical] if canonical else []), "기본 이미지"\n''',
    '''        role = self.SETTING_TO_CANONICAL_ROLE.get(key, "default")\n        built_in = self._resolve_builtin_asset(role, controls=True)\n        return ([built_in] if built_in else []), "내장 이미지"\n''',
    'settings preview resolver',
)
replace_one(
    path,
    '''        if hasattr(self, "image_alignment_vars"):\n            self.image_alignment_vars[key].set("가운데")\n        self._image_set_store.clear(key)\n''',
    '''        if hasattr(self, "image_alignment_vars"):\n            self.image_alignment_vars[key].set("가운데")\n        if hasattr(self, "image_builtin_vars"):\n            self.image_builtin_vars[key].set("세트 기본값")\n        self._image_set_store.clear(key)\n''',
    'reset role override',
)
replace_one(
    path,
    '''        self.image_path_vars = {}\n        self.image_name_vars = {}\n        self.image_mode_vars = {}\n        self.image_alignment_vars = {}\n\n        preview_box = tk.Frame(content, bg=core.PANEL_2, bd=0, highlightthickness=0)\n''',
    '''        built_in_labels = tuple(f"{number:02d}" for number in available_complete_sets())\n        self._builtin_set_labels = built_in_labels\n        built_in_row = tk.Frame(content, bg=core.PANEL)\n        built_in_row.pack(fill="x", pady=(2, 7), **pad)\n        self._label(built_in_row, "기본 내장 세트", size=9, bg=core.PANEL).pack(side="left")\n        self.builtin_image_set_var = tk.StringVar(value=self._builtin_base_label(p.builtin_image_set))\n        tk.OptionMenu(\n            built_in_row, self.builtin_image_set_var, "랜덤", *built_in_labels,\n            command=lambda _value: self._select_settings_preview(self._settings_preview_role),\n        ).pack(side="left", padx=(10, 0))\n        self._label(\n            built_in_row, "역할별 지정이 없으면 이 세트를 사용",\n            size=8, fg=core.MUTED, bg=core.PANEL,\n        ).pack(side="left", padx=(10, 0))\n\n        self.image_path_vars = {}\n        self.image_name_vars = {}\n        self.image_mode_vars = {}\n        self.image_alignment_vars = {}\n        self.image_builtin_vars = {}\n\n        preview_box = tk.Frame(content, bg=core.PANEL_2, bd=0, highlightthickness=0)\n''',
    'base set UI',
)
replace_one(
    path,
    '''            self.image_path_vars[key] = tk.StringVar(value=path_value)\n            self.image_name_vars[key] = tk.StringVar(value=self._image_display_name(key, path_value))\n            self.image_mode_vars[key] = tk.StringVar(value="가운데 크롭" if mode_value == "crop" else "자동 맞춤")\n            self.image_alignment_vars[key] = tk.StringVar(value=alignment_labels.get(config.alignment, "가운데"))\n''',
    '''            self.image_path_vars[key] = tk.StringVar(value=path_value)\n            self.image_name_vars[key] = tk.StringVar(value=self._image_display_name(key, path_value))\n            self.image_mode_vars[key] = tk.StringVar(value="가운데 크롭" if mode_value == "crop" else "자동 맞춤")\n            self.image_alignment_vars[key] = tk.StringVar(value=alignment_labels.get(config.alignment, "가운데"))\n            self.image_builtin_vars[key] = tk.StringVar(\n                value=self._builtin_override_label(getattr(p, f"builtin_image_{key}", ""))\n            )\n''',
    'role override variables',
)
replace_one(
    path,
    '''            options = tk.Frame(content, bg=core.PANEL)\n            options.pack(fill="x", pady=(0, 3), **pad)\n            self._label(options, "표시", size=8, fg=core.MUTED, bg=core.PANEL).pack(side="left", padx=(70, 3))\n            tk.OptionMenu(\n                options, self.image_mode_vars[key], "자동 맞춤", "가운데 크롭",\n                command=lambda _value, k=key: self._select_settings_preview(k),\n            ).pack(side="left", padx=(0, 5))\n''',
    '''            options = tk.Frame(content, bg=core.PANEL)\n            options.pack(fill="x", pady=(0, 3), **pad)\n            self._label(options, "내장", size=8, fg=core.MUTED, bg=core.PANEL).pack(side="left", padx=(70, 3))\n            tk.OptionMenu(\n                options, self.image_builtin_vars[key], "세트 기본값", *self._builtin_set_labels,\n                command=lambda _value, k=key: self._select_settings_preview(k),\n            ).pack(side="left", padx=(0, 5))\n            self._label(options, "표시", size=8, fg=core.MUTED, bg=core.PANEL).pack(side="left", padx=(5, 3))\n            tk.OptionMenu(\n                options, self.image_mode_vars[key], "자동 맞춤", "가운데 크롭",\n                command=lambda _value, k=key: self._select_settings_preview(k),\n            ).pack(side="left", padx=(0, 5))\n''',
    'role override UI',
)
replace_one(
    path,
    '''                message_text_color=validate_hex_color(self.style_color_vars["message"].get()),\n                **{f"image_{k}": self.image_path_vars[k].get() for k, _ in self.IMAGE_ROWS},\n''',
    '''                message_text_color=validate_hex_color(self.style_color_vars["message"].get()),\n                builtin_image_set=self._builtin_base_value(self.builtin_image_set_var.get()),\n                **{\n                    f"builtin_image_{k}": self._builtin_override_value(self.image_builtin_vars[k].get())\n                    for k, _ in self.IMAGE_ROWS\n                },\n                **{f"image_{k}": self.image_path_vars[k].get() for k, _ in self.IMAGE_ROWS},\n''',
    'save built-in choices',
)

# 4) Unit coverage.
path = Path('tests/test_asset_manager.py')
replace_one(
    path,
    '''    available_complete_sets,\n    resolve_asset,\n''',
    '''    available_complete_sets,\n    resolve_asset,\n    resolve_configured_asset,\n''',
    'asset test import',
)
replace_one(
    path,
    '''    def test_missing_asset_is_safe(self):\n        with tempfile.TemporaryDirectory() as td:\n            self.assertIsNone(resolve_asset("default", Path(td)))\n\n\nif __name__ == "__main__":\n''',
    '''    def test_configured_set_supports_base_and_role_override(self):\n        with tempfile.TemporaryDirectory() as td:\n            root = Path(td)\n            folders = ("default", "cheer", "rest", "away", "warning", "leave", "stats", "settings", "alert", "profile")\n            for role in folders:\n                folder = root / role\n                folder.mkdir()\n                for number in (3, 5):\n                    (folder / f"{role}_{number:02d}.png").write_bytes(b"x")\n\n            set_session_set(3, root)\n            self.assertEqual(\n                resolve_configured_asset("default", "05", "", root),\n                root / "default" / "default_05.png",\n            )\n            self.assertEqual(\n                resolve_configured_asset("nag", "03", "05", root),\n                root / "warning" / "warning_05.png",\n            )\n            self.assertEqual(\n                resolve_configured_asset("praise", "random", "", root),\n                root / "leave" / "leave_03.png",\n            )\n\n    def test_missing_asset_is_safe(self):\n        with tempfile.TemporaryDirectory() as td:\n            self.assertIsNone(resolve_asset("default", Path(td)))\n\n\nif __name__ == "__main__":\n''',
    'asset selection test',
)

path = Path('tests/test_settings.py')
replace_one(
    path,
    '''            image_default="default.png",\n            personality="warm",\n''',
    '''            image_default="default.png",\n            builtin_image_set="03",\n            builtin_image_warning="05",\n            personality="warm",\n''',
    'settings round trip coverage',
)
replace_one(
    path,
    '''    def test_personality_loads_and_invalid_value_falls_back(self):\n        self.assertEqual(settings_from_dict({"personality": "playful"}).personality, "playful")\n        self.assertEqual(settings_from_dict({"personality": "unknown"}).personality, "balanced")\n\n\nif __name__ == "__main__":\n''',
    '''    def test_personality_loads_and_invalid_value_falls_back(self):\n        self.assertEqual(settings_from_dict({"personality": "playful"}).personality, "playful")\n        self.assertEqual(settings_from_dict({"personality": "unknown"}).personality, "balanced")\n\n    def test_builtin_asset_choices_normalize_safely(self):\n        parsed = settings_from_dict({\n            "builtin_image_set": "3",\n            "builtin_image_default": "5",\n            "builtin_image_warning": "bad",\n        })\n        self.assertEqual(parsed.builtin_image_set, "03")\n        self.assertEqual(parsed.builtin_image_default, "05")\n        self.assertEqual(parsed.builtin_image_warning, "")\n        self.assertEqual(settings_from_dict({"builtin_image_set": "bad"}).builtin_image_set, "random")\n\n\nif __name__ == "__main__":\n''',
    'settings normalization test',
)

print('patched built-in asset set selection, role overrides, and tests')
