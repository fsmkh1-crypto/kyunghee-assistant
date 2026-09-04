from pathlib import Path


path = Path("desktop_compact.py")
text = path.read_text(encoding="utf-8")


def replace_once(old: str, new: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"expected one match, found {count}: {old[:120]!r}")
    text = text.replace(old, new, 1)


replace_once(
    "from image_render import resize_rgba_alpha_safe, threshold_alpha\n",
    "from image_render import resize_rgba_alpha_safe, threshold_alpha\n"
    "from image_sets import ImageSetStore, normalize_alignment\n",
)

replace_once(
    "USER_IMAGE_DIR = core.DATA_DIR / \"images\"\n",
    "USER_IMAGE_DIR = core.DATA_DIR / \"images\"\n"
    "USER_IMAGE_SET_DIR = core.DATA_DIR / \"image_sets\"\n",
)

replace_once(
    "        self._image_cache = {}\n        self._presentation_suppressed = False\n",
    "        self._image_cache = {}\n"
    "        self._image_set_store = ImageSetStore(USER_IMAGE_SET_DIR)\n"
    "        self._image_set_choices = {}\n"
    "        self._presentation_suppressed = False\n",
)

replace_once(
    "    def _stored_image_path(self, value: str):\n",
    "    @staticmethod\n"
    "    def _alignment_center(value: str) -> tuple[float, float]:\n"
    "        value = normalize_alignment(value)\n"
    "        return {\n"
    "            \"center\": (0.5, 0.5),\n"
    "            \"top\": (0.5, 0.0),\n"
    "            \"bottom\": (0.5, 1.0),\n"
    "            \"left\": (0.0, 0.5),\n"
    "            \"right\": (1.0, 0.5),\n"
    "            \"top_left\": (0.0, 0.0),\n"
    "            \"top_right\": (1.0, 0.0),\n"
    "            \"bottom_left\": (0.0, 1.0),\n"
    "            \"bottom_right\": (1.0, 1.0),\n"
    "        }[value]\n\n"
    "    def _stored_image_path(self, value: str):\n",
)

replace_once(
    "    def _custom_image(self, role: str):\n"
    "        key = self.ROLE_TO_SETTING.get(role, \"default\")\n"
    "        value = getattr(self.preferences, f\"image_{key}\", \"\")\n"
    "        path = self._stored_image_path(value)\n"
    "        mode = getattr(self.preferences, f\"image_{key}_mode\", \"fit\")\n"
    "        if path and not path.is_file():\n"
    "            core.log.warning(\"custom image missing for %s: %s\", key, path)\n"
    "            return None, mode\n"
    "        return path, mode\n",
    "    def _custom_image(self, role: str):\n"
    "        key = self.ROLE_TO_SETTING.get(role, \"default\")\n"
    "        config = self._image_set_store.get(key)\n"
    "        available = self._image_set_store.list_images(key)\n"
    "        selected = self._image_set_choices.get(role)\n"
    "        if selected not in available:\n"
    "            selected = None\n"
    "        if selected is None and available:\n"
    "            selected = self._image_set_store.choose(key)\n"
    "            if selected is not None:\n"
    "                self._image_set_choices[role] = selected\n"
    "        if selected is not None:\n"
    "            return selected, config.fit_mode, self._alignment_center(config.alignment)\n\n"
    "        value = getattr(self.preferences, f\"image_{key}\", \"\")\n"
    "        path = self._stored_image_path(value)\n"
    "        mode = getattr(self.preferences, f\"image_{key}_mode\", \"fit\")\n"
    "        if path and not path.is_file():\n"
    "            core.log.warning(\"custom image missing for %s: %s\", key, path)\n"
    "            return None, mode, (0.5, 0.5)\n"
    "        return path, mode, (0.5, 0.5)\n",
)

replace_once(
    "        custom, mode = self._custom_image(role)\n"
    "        path = custom or resolve_asset(role)\n",
    "        custom, mode, centering = self._custom_image(role)\n"
    "        path = custom or resolve_asset(role)\n",
)

replace_once(
    "        cache_key = (str(path), stat_key, tuple(max_size), mode, bool(preserve_alpha))\n",
    "        cache_key = (str(path), stat_key, tuple(max_size), mode, tuple(centering), bool(preserve_alpha))\n",
)

replace_once(
    "                centering=(0.5, 0.5),\n",
    "                centering=centering,\n",
)

replace_once(
    "    def apply_preferences(self, preferences) -> None:\n"
    "        self._image_cache.clear()\n",
    "    def apply_preferences(self, preferences) -> None:\n"
    "        self._image_cache.clear()\n"
    "        self._image_set_store.invalidate()\n"
    "        self._image_set_choices.clear()\n",
)

replace_once(
    "    def _set_character(self, role: str):\n"
    "        if role == self.character_role:\n"
    "            return\n"
    "        try:\n",
    "    def _set_character(self, role: str):\n"
    "        if role == self.character_role:\n"
    "            return\n"
    "        self._image_set_choices.pop(role, None)\n"
    "        try:\n",
)

replace_once(
    "    def _choose_image(self, key):\n",
    "    def _validate_image_source(self, source: Path) -> None:\n"
    "        if source.suffix.lower() not in {\".png\", \".jpg\", \".jpeg\", \".webp\"}:\n"
    "            raise ValueError(\"PNG, JPG, JPEG, WebP 이미지만 사용할 수 있습니다.\")\n"
    "        with Image.open(source) as probe:\n"
    "            if probe.width > MAX_CUSTOM_IMAGE_DIMENSION or probe.height > MAX_CUSTOM_IMAGE_DIMENSION:\n"
    "                raise ValueError(\n"
    "                    f\"이미지가 너무 큽니다. 가로·세로 각각 {MAX_CUSTOM_IMAGE_DIMENSION}px 이하를 사용해 주세요.\"\n"
    "                )\n"
    "            probe.verify()\n\n"
    "    def _remove_legacy_image_files(self, key: str) -> None:\n"
    "        if not USER_IMAGE_DIR.is_dir():\n"
    "            return\n"
    "        for old in USER_IMAGE_DIR.glob(f\"{key}.*\"):\n"
    "            try:\n"
    "                old.unlink()\n"
    "            except OSError:\n"
    "                core.log.warning(\"old custom image could not be removed: %s\", old)\n\n"
    "    def _image_set_summary(self, key: str) -> str:\n"
    "        count = len(self._image_set_store.list_images(key))\n"
    "        return f\"{count}장 세트\" if count else \"기본 이미지\"\n\n"
    "    def _choose_image(self, key):\n",
)

replace_once(
    "        source = Path(path)\n"
    "        try:\n"
    "            with Image.open(source) as probe:\n"
    "                if probe.width > MAX_CUSTOM_IMAGE_DIMENSION or probe.height > MAX_CUSTOM_IMAGE_DIMENSION:\n"
    "                    raise ValueError(\n"
    "                        f\"이미지가 너무 큽니다. 가로·세로 각각 {MAX_CUSTOM_IMAGE_DIMENSION}px 이하를 사용해 주세요.\"\n"
    "                    )\n"
    "                probe.verify()\n"
    "            USER_IMAGE_DIR.mkdir(parents=True, exist_ok=True)\n"
    "            for old in USER_IMAGE_DIR.glob(f\"{key}.*\"):\n"
    "                try:\n"
    "                    old.unlink()\n"
    "                except OSError:\n"
    "                    core.log.warning(\"old custom image could not be removed: %s\", old)\n"
    "            suffix = source.suffix.lower()\n"
    "            if suffix not in {\".png\", \".jpg\", \".jpeg\", \".webp\"}:\n"
    "                raise ValueError(\"PNG, JPG, JPEG, WebP 이미지만 사용할 수 있습니다.\")\n"
    "            destination = USER_IMAGE_DIR / f\"{key}{suffix}\"\n",
    "        source = Path(path)\n"
    "        try:\n"
    "            self._validate_image_source(source)\n"
    "            self._image_set_store.clear(key)\n"
    "            USER_IMAGE_DIR.mkdir(parents=True, exist_ok=True)\n"
    "            self._remove_legacy_image_files(key)\n"
    "            suffix = source.suffix.lower()\n"
    "            destination = USER_IMAGE_DIR / f\"{key}{suffix}\"\n",
)

replace_once(
    "        except Exception as exc:\n"
    "            core.log.exception(\"custom image import failed: %s\", source)\n"
    "            self.settings_status.configure(text=f\"이미지 선택 실패: {exc}\", fg=core.AMBER)\n\n"
    "    def _reset_image(self, key):\n",
    "        except Exception as exc:\n"
    "            core.log.exception(\"custom image import failed: %s\", source)\n"
    "            self.settings_status.configure(text=f\"이미지 선택 실패: {exc}\", fg=core.AMBER)\n\n"
    "    def _choose_image_set(self, key):\n"
    "        paths = filedialog.askopenfilenames(\n"
    "            parent=self.root,\n"
    "            title=f\"{dict(self.IMAGE_ROWS)[key]} 이미지 여러 장 선택\",\n"
    "            filetypes=[(\"이미지\", \"*.png *.jpg *.jpeg *.webp\"), (\"모든 파일\", \"*.*\")],\n"
    "        )\n"
    "        if not paths:\n"
    "            return\n"
    "        sources = [Path(value) for value in paths]\n"
    "        try:\n"
    "            for source in sources:\n"
    "                self._validate_image_source(source)\n"
    "            self._image_set_store.clear(key)\n"
    "            config = self._image_set_store.import_files(key, sources)\n"
    "            self._remove_legacy_image_files(key)\n"
    "            self.image_path_vars[key].set(\"\")\n"
    "            self.image_name_vars[key].set(f\"{len(config.images)}장 세트\")\n"
    "            self._image_cache.clear()\n"
    "            self._image_set_choices.clear()\n"
    "        except Exception as exc:\n"
    "            core.log.exception(\"custom image set import failed\")\n"
    "            self.settings_status.configure(text=f\"이미지 세트 선택 실패: {exc}\", fg=core.AMBER)\n\n"
    "    def _choose_image_folder(self, key):\n"
    "        folder = filedialog.askdirectory(\n"
    "            parent=self.root, title=f\"{dict(self.IMAGE_ROWS)[key]} 이미지 폴더 선택\"\n"
    "        )\n"
    "        if not folder:\n"
    "            return\n"
    "        source_dir = Path(folder)\n"
    "        try:\n"
    "            sources = [\n"
    "                path for path in sorted(source_dir.iterdir(), key=lambda item: item.name.lower())\n"
    "                if path.is_file() and path.suffix.lower() in {\".png\", \".jpg\", \".jpeg\", \".webp\"}\n"
    "            ]\n"
    "            if not sources:\n"
    "                raise ValueError(\"선택한 폴더에 지원되는 이미지가 없습니다.\")\n"
    "            for source in sources:\n"
    "                self._validate_image_source(source)\n"
    "            self._image_set_store.clear(key)\n"
    "            config = self._image_set_store.import_files(key, sources)\n"
    "            self._remove_legacy_image_files(key)\n"
    "            self.image_path_vars[key].set(\"\")\n"
    "            self.image_name_vars[key].set(f\"{len(config.images)}장 세트\")\n"
    "            self._image_cache.clear()\n"
    "            self._image_set_choices.clear()\n"
    "        except Exception as exc:\n"
    "            core.log.exception(\"custom image folder import failed: %s\", source_dir)\n"
    "            self.settings_status.configure(text=f\"이미지 폴더 선택 실패: {exc}\", fg=core.AMBER)\n\n"
    "    def _reset_image(self, key):\n",
)

replace_once(
    "    def _reset_image(self, key):\n"
    "        self.image_path_vars[key].set(\"\")\n"
    "        self.image_name_vars[key].set(\"기본 이미지\")\n"
    "        self.image_mode_vars[key].set(\"자동 맞춤\")\n"
    "        self._image_cache.clear()\n"
    "        if USER_IMAGE_DIR.is_dir():\n"
    "            for old in USER_IMAGE_DIR.glob(f\"{key}.*\"):\n"
    "                try:\n"
    "                    old.unlink()\n"
    "                except OSError:\n"
    "                    core.log.warning(\"custom image reset could not remove: %s\", old)\n\n"
    "    def _image_display_name(self, value):\n"
    "        if not value:\n"
    "            return \"기본 이미지\"\n"
    "        path = self._stored_image_path(value)\n"
    "        if path and path.is_file():\n"
    "            return path.name\n"
    "        return f\"⚠ 파일 없음: {Path(value).name}\"\n",
    "    def _reset_image(self, key):\n"
    "        self.image_path_vars[key].set(\"\")\n"
    "        self.image_name_vars[key].set(\"기본 이미지\")\n"
    "        self.image_mode_vars[key].set(\"자동 맞춤\")\n"
    "        if hasattr(self, \"image_alignment_vars\"):\n"
    "            self.image_alignment_vars[key].set(\"가운데\")\n"
    "        self._image_set_store.clear(key)\n"
    "        self._image_set_store.set_options(key, fit_mode=\"fit\", alignment=\"center\")\n"
    "        self._image_set_choices.clear()\n"
    "        self._image_cache.clear()\n"
    "        self._remove_legacy_image_files(key)\n\n"
    "    def _image_display_name(self, key, value):\n"
    "        set_count = len(self._image_set_store.list_images(key))\n"
    "        if set_count:\n"
    "            return f\"{set_count}장 세트\"\n"
    "        if not value:\n"
    "            return \"기본 이미지\"\n"
    "        path = self._stored_image_path(value)\n"
    "        if path and path.is_file():\n"
    "            return path.name\n"
    "        return f\"⚠ 파일 없음: {Path(value).name}\"\n",
)

replace_once(
    "        self.image_path_vars = {}\n"
    "        self.image_name_vars = {}\n"
    "        self.image_mode_vars = {}\n"
    "        for key, caption in self.IMAGE_ROWS:\n"
    "            path_value = getattr(p, f\"image_{key}\")\n"
    "            mode_value = getattr(p, f\"image_{key}_mode\")\n"
    "            self.image_path_vars[key] = tk.StringVar(value=path_value)\n"
    "            self.image_name_vars[key] = tk.StringVar(value=self._image_display_name(path_value))\n"
    "            self.image_mode_vars[key] = tk.StringVar(value=\"가운데 크롭\" if mode_value == \"crop\" else \"자동 맞춤\")\n\n"
    "            row = tk.Frame(content, bg=core.PANEL)\n"
    "            row.pack(fill=\"x\", pady=2, **pad)\n"
    "            self._label(row, caption, size=9, bg=core.PANEL).pack(side=\"left\")\n"
    "            name_label = tk.Label(\n"
    "                row, textvariable=self.image_name_vars[key], width=22, anchor=\"w\",\n"
    "                font=(self.FONT_FAMILY, 8, \"normal\"), fg=core.MUTED, bg=core.PANEL,\n"
    "            )\n"
    "            name_label.pack(side=\"left\", padx=(10, 5))\n"
    "            tk.OptionMenu(row, self.image_mode_vars[key], \"자동 맞춤\", \"가운데 크롭\").pack(side=\"left\", padx=4)\n"
    "            self._button(row, \"선택\", lambda k=key: self._choose_image(k)).pack(side=\"left\", padx=4)\n"
    "            self._button(row, \"기본값\", lambda k=key: self._reset_image(k)).pack(side=\"left\")\n",
    "        self.image_path_vars = {}\n"
    "        self.image_name_vars = {}\n"
    "        self.image_mode_vars = {}\n"
    "        self.image_alignment_vars = {}\n"
    "        alignment_labels = {\n"
    "            \"center\": \"가운데\", \"top\": \"위\", \"bottom\": \"아래\",\n"
    "            \"left\": \"왼쪽\", \"right\": \"오른쪽\",\n"
    "            \"top_left\": \"왼쪽 위\", \"top_right\": \"오른쪽 위\",\n"
    "            \"bottom_left\": \"왼쪽 아래\", \"bottom_right\": \"오른쪽 아래\",\n"
    "        }\n"
    "        for key, caption in self.IMAGE_ROWS:\n"
    "            path_value = getattr(p, f\"image_{key}\")\n"
    "            config = self._image_set_store.get(key)\n"
    "            mode_value = config.fit_mode if config.images else getattr(p, f\"image_{key}_mode\")\n"
    "            self.image_path_vars[key] = tk.StringVar(value=path_value)\n"
    "            self.image_name_vars[key] = tk.StringVar(value=self._image_display_name(key, path_value))\n"
    "            self.image_mode_vars[key] = tk.StringVar(value=\"가운데 크롭\" if mode_value == \"crop\" else \"자동 맞춤\")\n"
    "            self.image_alignment_vars[key] = tk.StringVar(value=alignment_labels.get(config.alignment, \"가운데\"))\n\n"
    "            row = tk.Frame(content, bg=core.PANEL)\n"
    "            row.pack(fill=\"x\", pady=(3, 0), **pad)\n"
    "            self._label(row, caption, size=9, bg=core.PANEL).pack(side=\"left\")\n"
    "            name_label = tk.Label(\n"
    "                row, textvariable=self.image_name_vars[key], width=18, anchor=\"w\",\n"
    "                font=(self.FONT_FAMILY, 8, \"normal\"), fg=core.MUTED, bg=core.PANEL,\n"
    "            )\n"
    "            name_label.pack(side=\"left\", padx=(10, 5))\n"
    "            self._button(row, \"한 장\", lambda k=key: self._choose_image(k)).pack(side=\"left\", padx=2)\n"
    "            self._button(row, \"여러 장\", lambda k=key: self._choose_image_set(k)).pack(side=\"left\", padx=2)\n"
    "            self._button(row, \"폴더\", lambda k=key: self._choose_image_folder(k)).pack(side=\"left\", padx=2)\n"
    "            self._button(row, \"기본값\", lambda k=key: self._reset_image(k)).pack(side=\"left\", padx=(2, 0))\n"
    "            options = tk.Frame(content, bg=core.PANEL)\n"
    "            options.pack(fill=\"x\", pady=(0, 3), **pad)\n"
    "            self._label(options, \"표시\", size=8, fg=core.MUTED, bg=core.PANEL).pack(side=\"left\", padx=(70, 3))\n"
    "            tk.OptionMenu(options, self.image_mode_vars[key], \"자동 맞춤\", \"가운데 크롭\").pack(side=\"left\", padx=(0, 5))\n"
    "            self._label(options, \"정렬\", size=8, fg=core.MUTED, bg=core.PANEL).pack(side=\"left\", padx=(5, 3))\n"
    "            tk.OptionMenu(\n"
    "                options, self.image_alignment_vars[key],\n"
    "                \"가운데\", \"위\", \"아래\", \"왼쪽\", \"오른쪽\",\n"
    "                \"왼쪽 위\", \"오른쪽 위\", \"왼쪽 아래\", \"오른쪽 아래\",\n"
    "            ).pack(side=\"left\")\n",
)

replace_once(
    "            candidate.workday_policy()\n"
    "            candidate.validate_widget_style()\n"
    "            previous = self.preferences\n",
    "            candidate.workday_policy()\n"
    "            candidate.validate_widget_style()\n"
    "            alignment_values = {\n"
    "                \"가운데\": \"center\", \"위\": \"top\", \"아래\": \"bottom\",\n"
    "                \"왼쪽\": \"left\", \"오른쪽\": \"right\",\n"
    "                \"왼쪽 위\": \"top_left\", \"오른쪽 위\": \"top_right\",\n"
    "                \"왼쪽 아래\": \"bottom_left\", \"오른쪽 아래\": \"bottom_right\",\n"
    "            }\n"
    "            for key, _caption in self.IMAGE_ROWS:\n"
    "                self._image_set_store.set_options(\n"
    "                    key,\n"
    "                    fit_mode=\"crop\" if self.image_mode_vars[key].get() == \"가운데 크롭\" else \"fit\",\n"
    "                    alignment=alignment_values.get(self.image_alignment_vars[key].get(), \"center\"),\n"
    "                )\n"
    "            self._image_set_choices.clear()\n"
    "            previous = self.preferences\n",
)

path.write_text(text, encoding="utf-8")
print("patched desktop_compact.py for Phase 4 image sets")
