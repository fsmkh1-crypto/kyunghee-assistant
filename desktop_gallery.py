from __future__ import annotations

import json
import os
from pathlib import Path
import tkinter as tk
from PIL import Image, ImageTk

import app as core
import asset_manager
import desktop_compact as compact
from asset_rotation import (
    SUPPORTED_IMAGE_SUFFIXES,
    next_nonrepeating_ref,
    next_nonrepeating_set,
    unique_complete_sets,
)
from image_render import resize_rgba_alpha_safe


# Keep one coherent built-in set, but collapse only byte-identical whole-set
# duplicates from automatic rotation.  Manual gallery browsing still exposes
# every physical file, including both copies of an exact duplicate.
def _available_unique_sets(asset_dir: Path = asset_manager.ASSET_DIR) -> tuple[int, ...]:
    return unique_complete_sets(Path(asset_dir))


def _select_nonrepeating_session_set(
    asset_dir: Path = asset_manager.ASSET_DIR,
    *,
    rng=None,
) -> int | None:
    key = asset_manager._root_key(asset_dir)
    if key in asset_manager._SESSION_SET_BY_ROOT:
        return asset_manager._SESSION_SET_BY_ROOT[key]
    selected = next_nonrepeating_set(
        Path(asset_dir),
        core.DATA_DIR / 'builtin_set_shuffle.json',
        rng=rng,
    )
    asset_manager._SESSION_SET_BY_ROOT[key] = selected
    return selected


asset_manager.available_complete_sets = _available_unique_sets
asset_manager.select_session_set = _select_nonrepeating_session_set
# desktop_compact imported this symbol directly, so update its local binding too.
compact.available_complete_sets = _available_unique_sets


class GalleryDesktopApp(compact.CompactDesktopApp):
    """Compact timer with one global set selector and per-role image gallery."""

    SETTINGS_SIZE = (900, 820)
    GALLERY_SIZE = (1040, 780)
    PREVIEW_SIZE = (210, 250)
    MANUAL_OVERRIDE_FILE = core.DATA_DIR / 'manual_asset_overrides.json'
    GALLERY_RANDOM_FILE = core.DATA_DIR / 'gallery_random_shuffle.json'
    FOLLOW_SENTINEL = '__follow_selected_set__'

    def __init__(self):
        self._manual_asset_overrides = self._load_manual_overrides()
        self._gallery_previous: dict[str, str] = {}
        self._gallery_thumb_cache: dict[tuple[str, int, int], Image.Image] = {}
        super().__init__()

    @staticmethod
    def _safe_json_dict(path: Path) -> dict[str, str]:
        try:
            raw = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return {}
        if not isinstance(raw, dict):
            return {}
        return {
            str(key): str(value)
            for key, value in raw.items()
            if isinstance(key, str) and isinstance(value, str) and value
        }

    def _load_manual_overrides(self) -> dict[str, str]:
        return self._safe_json_dict(self.MANUAL_OVERRIDE_FILE)

    def _save_manual_overrides(self) -> None:
        path = self.MANUAL_OVERRIDE_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(f'{path.name}.{os.getpid()}.tmp')
        try:
            temp.write_text(
                json.dumps(self._manual_asset_overrides, ensure_ascii=False, indent=2),
                encoding='utf-8',
            )
            os.replace(temp, path)
        finally:
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass

    @staticmethod
    def _is_under(path: Path, root: Path) -> bool:
        try:
            path.resolve().relative_to(root.resolve())
            return True
        except (OSError, ValueError):
            return False

    def _encode_asset_ref(self, path: Path) -> str:
        path = Path(path)
        if self._is_under(path, asset_manager.ASSET_DIR):
            return 'builtin:' + path.resolve().relative_to(asset_manager.ASSET_DIR.resolve()).as_posix()
        if self._is_under(path, compact.USER_IMAGE_DIR):
            return 'user:' + path.resolve().relative_to(compact.USER_IMAGE_DIR.resolve()).as_posix()
        if self._is_under(path, compact.USER_IMAGE_SET_DIR):
            return 'userset:' + path.resolve().relative_to(compact.USER_IMAGE_SET_DIR.resolve()).as_posix()
        return 'absolute:' + str(path.resolve())

    def _decode_asset_ref(self, ref: str) -> Path | None:
        ref = str(ref or '')
        prefixes = (
            ('builtin:', asset_manager.ASSET_DIR),
            ('user:', compact.USER_IMAGE_DIR),
            ('userset:', compact.USER_IMAGE_SET_DIR),
        )
        for prefix, root in prefixes:
            if ref.startswith(prefix):
                candidate = (Path(root) / ref[len(prefix):]).resolve()
                if self._is_under(candidate, Path(root)) and candidate.is_file():
                    return candidate
                return None
        if ref.startswith('absolute:'):
            candidate = Path(ref[len('absolute:'):]).expanduser()
            return candidate if candidate.is_file() else None
        return None

    def _manual_override_path(self, key: str) -> Path | None:
        ref = self._manual_asset_overrides.get(key, '')
        path = self._decode_asset_ref(ref)
        if ref and path is None:
            self._manual_asset_overrides.pop(key, None)
            self._save_manual_overrides()
        return path

    def _manual_style(self, key: str):
        if hasattr(self, 'image_mode_vars') and key in self.image_mode_vars:
            mode = 'crop' if self.image_mode_vars[key].get() == '가운데 크롭' else 'fit'
        else:
            mode = getattr(self.preferences, f'image_{key}_mode', 'fit')
        if hasattr(self, 'image_alignment_vars') and key in self.image_alignment_vars:
            labels = {
                '가운데': 'center', '위': 'top', '아래': 'bottom',
                '왼쪽': 'left', '오른쪽': 'right',
                '왼쪽 위': 'top_left', '오른쪽 위': 'top_right',
                '왼쪽 아래': 'bottom_left', '오른쪽 아래': 'bottom_right',
            }
            alignment = labels.get(self.image_alignment_vars[key].get(), 'center')
        else:
            alignment = self._image_set_store.get(key).alignment
        return mode, self._alignment_center(alignment)

    def _custom_image(self, role: str):
        key = self.ROLE_TO_SETTING.get(role, 'default')
        manual = self._manual_override_path(key)
        if manual is not None:
            mode, centering = self._manual_style(key)
            return manual, mode, centering
        return super()._custom_image(role)

    def _resolve_builtin_asset(self, role: str, *, controls: bool = False):
        # Per-role built-in set overrides are intentionally retired.  A role is
        # either following the one global set selector or manually choosing one
        # concrete file from the gallery.
        if controls and hasattr(self, 'builtin_image_set_var'):
            base_set = self._builtin_base_value(self.builtin_image_set_var.get())
        else:
            base_set = getattr(self.preferences, 'builtin_image_set', 'random')
        return asset_manager.resolve_configured_asset(role, base_set, '')

    def _base_set_preview_sources(self):
        if hasattr(self, 'builtin_image_set_var'):
            base = self._builtin_base_value(self.builtin_image_set_var.get())
        else:
            base = getattr(self.preferences, 'builtin_image_set', 'random')

        if base == 'random':
            number = asset_manager.select_session_set()
        elif str(base).isdigit():
            number = int(base)
        else:
            number = None

        sources: list[Path] = []
        if number is not None:
            for key, _caption in self.IMAGE_ROWS:
                role = self.SETTING_TO_CANONICAL_ROLE.get(key, 'default')
                path = asset_manager.variant_asset(role, number)
                if path is not None:
                    sources.append(path)
            return sources, f'세트 {number:02d}'

        for key, _caption in self.IMAGE_ROWS:
            role = self.SETTING_TO_CANONICAL_ROLE.get(key, 'default')
            path = asset_manager.resolve_canonical_asset(role)
            if path is not None:
                sources.append(path)
        return sources, '기본 모델'

    def _settings_preview_sources(self, key: str):
        manual = self._manual_override_path(key)
        if manual is not None:
            return [manual], '수동 선택'

        # Preserve existing user-imported one/multi-image support as another
        # form of manual override.
        set_images = list(self._image_set_store.list_images(key))
        if set_images:
            return set_images, '사용자 이미지'
        value = self.image_path_vars[key].get() if hasattr(self, 'image_path_vars') else getattr(
            self.preferences, f'image_{key}', ''
        )
        legacy = self._stored_image_path(value)
        if legacy and legacy.is_file():
            return [legacy], '사용자 이미지'

        return self._base_set_preview_sources()

    def _preview_role_for_path(self, source: Path) -> str | None:
        parent = source.parent.name
        labels = dict(self.IMAGE_ROWS)
        return labels.get(parent)

    def _render_settings_preview(self, key=None):
        if not hasattr(self, 'settings_preview_image'):
            return
        key = key or self._settings_preview_role
        self._settings_preview_role = key
        sources, source_kind = self._settings_preview_sources(key)
        default_caption = dict(self.IMAGE_ROWS).get(key, key)
        if not sources:
            self.settings_preview_image.configure(image='', text='이미지 없음')
            self.settings_preview_image.image = None
            self.settings_preview_title.configure(text=default_caption)
            self.settings_preview_meta.configure(text='미리볼 수 있는 이미지가 없습니다.')
            self.settings_preview_prev.configure(state='disabled')
            self.settings_preview_next.configure(state='disabled')
            return

        index = self._settings_preview_indices.get(key, 0) % len(sources)
        self._settings_preview_indices[key] = index
        source = Path(sources[index])
        mode, alignment = self._settings_preview_style(key)
        try:
            stat = source.stat()
            stat_key = (stat.st_mtime_ns, stat.st_size)
        except OSError:
            stat_key = (0, 0)
        cache_key = ('gallery-preview', key, str(source), stat_key, mode, alignment, self.PREVIEW_SIZE)
        preview = self._settings_preview_cache.get(cache_key)
        if preview is None:
            with Image.open(source) as src:
                rendered = resize_rgba_alpha_safe(
                    src,
                    self.PREVIEW_SIZE,
                    crop=(mode == 'crop' and source_kind in {'수동 선택', '사용자 이미지'}),
                    centering=self._alignment_center(alignment),
                )
                canvas = Image.new('RGBA', self.PREVIEW_SIZE, core.PANEL_2)
                x = (self.PREVIEW_SIZE[0] - rendered.width) // 2
                y = (self.PREVIEW_SIZE[1] - rendered.height) // 2
                canvas.alpha_composite(rendered, (x, y))
                preview = canvas.convert('RGB')
            self._settings_preview_cache[cache_key] = preview.copy()

        photo = ImageTk.PhotoImage(preview)
        self.settings_preview_image.configure(image=photo, text='', width=self.PREVIEW_SIZE[0], height=self.PREVIEW_SIZE[1])
        self.settings_preview_image.image = photo
        role_caption = self._preview_role_for_path(source)
        if source_kind.startswith('세트 ') and role_caption:
            title = f'{source_kind} · {role_caption}'
        else:
            title = default_caption
        self.settings_preview_title.configure(text=title)
        if len(sources) > 1:
            meta = f'{source_kind} · {index + 1}/{len(sources)} · {source.name}'
        else:
            meta = f'{source_kind} · {source.name}'
        self.settings_preview_meta.configure(text=meta)
        nav_state = 'normal' if len(sources) > 1 else 'disabled'
        self.settings_preview_prev.configure(state=nav_state)
        self.settings_preview_next.configure(state=nav_state)

    def _all_descendants(self, widget):
        for child in widget.winfo_children():
            yield child
            yield from self._all_descendants(child)

    def _hide_role_set_selectors(self):
        for key, var in getattr(self, 'image_builtin_vars', {}).items():
            var.set('세트 기본값')
            for widget in self._all_descendants(self.settings_page):
                if not isinstance(widget, tk.Menubutton):
                    continue
                try:
                    if str(widget.cget('textvariable')) != str(var):
                        continue
                except tk.TclError:
                    continue
                parent = widget.master
                widget.pack_forget()
                for sibling in parent.winfo_children():
                    if isinstance(sibling, tk.Label) and sibling.cget('text') == '내장':
                        sibling.pack_forget()

    def _find_role_row(self, caption: str):
        for widget in self._all_descendants(self.settings_page):
            if not isinstance(widget, tk.Frame):
                continue
            direct = widget.winfo_children()
            has_caption = any(
                isinstance(child, tk.Label) and child.cget('text') == caption
                for child in direct
            )
            has_file_button = any(
                isinstance(child, tk.Button) and child.cget('text') == '한 장'
                for child in direct
            )
            if has_caption and has_file_button:
                return widget
        return None

    def _decorate_image_rows(self):
        for key, caption in self.IMAGE_ROWS:
            row = self._find_role_row(caption)
            if row is None:
                continue
            for child in row.winfo_children():
                if isinstance(child, tk.Button) and child.cget('text') == '기본값':
                    child.configure(text='세트 따라가기')
            self._button(row, '갤러리', lambda k=key: self._open_asset_gallery(k)).pack(side='left', padx=2)
            self._button(row, '랜덤', lambda k=key: self._choose_random_manual(k)).pack(side='left', padx=2)
            manual = self._manual_override_path(key)
            if manual is not None:
                self.image_name_vars[key].set(manual.name)

    def _retitle_set_help(self):
        for widget in self._all_descendants(self.settings_page):
            if not isinstance(widget, tk.Label):
                continue
            text = str(widget.cget('text'))
            if text == '기본 내장 세트':
                widget.configure(text='전체 이미지 세트')
            elif text == '역할별 지정이 없으면 이 세트를 사용':
                widget.configure(text='수동 지정이 없으면 이 세트를 사용 · 랜덤 세트는 한 바퀴 전 중복 없음')

    def _build_settings_page(self):
        super()._build_settings_page()
        self._hide_role_set_selectors()
        self._decorate_image_rows()
        self._retitle_set_help()
        self._render_settings_preview('default')

    def _set_manual_override(self, key: str, ref: str) -> None:
        current = self._manual_asset_overrides.get(key, self.FOLLOW_SENTINEL)
        self._gallery_previous[key] = current
        if ref == self.FOLLOW_SENTINEL:
            self._manual_asset_overrides.pop(key, None)
        else:
            self._manual_asset_overrides[key] = ref
        self._save_manual_overrides()
        path = self._manual_override_path(key)
        if hasattr(self, 'image_name_vars') and key in self.image_name_vars:
            self.image_name_vars[key].set(path.name if path else '세트 따라가기')
        if hasattr(self, 'image_builtin_vars') and key in self.image_builtin_vars:
            self.image_builtin_vars[key].set('세트 기본값')
        self._image_cache.clear()
        self._invalidate_settings_preview(key)
        self._settings_preview_indices[key] = 0
        self._select_settings_preview(key)
        current_role = getattr(self, 'character_role', None)
        if current_role and self.ROLE_TO_SETTING.get(current_role, 'default') == key:
            self.character_role = None
            self._set_character(current_role)
            self._apply_widget_appearance()

    def _apply_gallery_path(self, key: str, path: Path) -> None:
        self._set_manual_override(key, self._encode_asset_ref(path))
        if hasattr(self, 'settings_status'):
            self.settings_status.configure(
                text=f'{dict(self.IMAGE_ROWS).get(key, key)} 이미지 변경: {path.name}',
                fg=core.GREEN,
            )

    def _follow_selected_set(self, key: str) -> None:
        self._manual_asset_overrides.pop(key, None)
        self._save_manual_overrides()
        super()._reset_image(key)
        if hasattr(self, 'image_name_vars'):
            self.image_name_vars[key].set('세트 따라가기')

    def _reset_image(self, key):
        self._manual_asset_overrides.pop(key, None)
        self._save_manual_overrides()
        super()._reset_image(key)
        if hasattr(self, 'image_name_vars'):
            self.image_name_vars[key].set('세트 따라가기')

    def _choose_image(self, key):
        before = self.image_path_vars[key].get()
        super()._choose_image(key)
        if self.image_path_vars[key].get() != before:
            self._manual_asset_overrides.pop(key, None)
            self._save_manual_overrides()

    def _choose_image_set(self, key):
        before = tuple(self._image_set_store.list_images(key))
        super()._choose_image_set(key)
        after = tuple(self._image_set_store.list_images(key))
        if after != before:
            self._manual_asset_overrides.pop(key, None)
            self._save_manual_overrides()

    def _choose_image_folder(self, key):
        before = tuple(self._image_set_store.list_images(key))
        super()._choose_image_folder(key)
        after = tuple(self._image_set_store.list_images(key))
        if after != before:
            self._manual_asset_overrides.pop(key, None)
            self._save_manual_overrides()

    def _catalog(self):
        labels = dict(self.IMAGE_ROWS)
        order = [key for key, _caption in self.IMAGE_ROWS]
        entries: list[tuple[str, str, Path]] = []
        seen: set[str] = set()

        def add(group_key: str, path: Path):
            try:
                resolved = str(path.resolve())
            except OSError:
                resolved = str(path)
            if resolved in seen or not path.is_file() or path.suffix.lower() not in SUPPORTED_IMAGE_SUFFIXES:
                return
            seen.add(resolved)
            entries.append((group_key, labels.get(group_key, '기타'), path))

        for key in order:
            folder = asset_manager.ASSET_DIR / key
            if folder.is_dir():
                for path in sorted(folder.iterdir(), key=lambda p: p.name.lower()):
                    add(key, path)

        # Existing user images are also valid manual choices and remain grouped
        # by their original situation whenever that can be inferred.
        if compact.USER_IMAGE_DIR.is_dir():
            for path in sorted(compact.USER_IMAGE_DIR.iterdir(), key=lambda p: p.name.lower()):
                group = path.stem if path.stem in labels else 'other'
                add(group, path)
        roles_root = compact.USER_IMAGE_SET_DIR / 'roles'
        if roles_root.is_dir():
            for role_dir in sorted((p for p in roles_root.iterdir() if p.is_dir()), key=lambda p: p.name.lower()):
                group = role_dir.name if role_dir.name in labels else 'other'
                for path in sorted(role_dir.iterdir(), key=lambda p: p.name.lower()):
                    add(group, path)
        return entries

    def _catalog_refs(self):
        return [self._encode_asset_ref(path) for _group, _label, path in self._catalog()]

    def _choose_random_manual(self, key: str):
        refs = self._catalog_refs()
        if not refs:
            return
        current = self._manual_asset_overrides.get(key)
        selected = next_nonrepeating_ref(refs, self.GALLERY_RANDOM_FILE)
        if selected == current and len(refs) > 1:
            selected = next_nonrepeating_ref(refs, self.GALLERY_RANDOM_FILE)
        path = self._decode_asset_ref(selected or '')
        if path is not None:
            self._apply_gallery_path(key, path)

    def _undo_gallery_choice(self, key: str):
        previous = self._gallery_previous.get(key)
        if previous is None:
            return
        self._set_manual_override(key, previous)

    def _thumbnail_image(self, path: Path, size=(112, 132)) -> Image.Image:
        try:
            stat = path.stat()
            key = (str(path), stat.st_mtime_ns, stat.st_size)
        except OSError:
            key = (str(path), 0, 0)
        cached = self._gallery_thumb_cache.get(key)
        if cached is not None:
            return cached.copy()
        with Image.open(path) as src:
            rgba = src.convert('RGBA')
            rgba.thumbnail(size, Image.Resampling.LANCZOS)
            canvas = Image.new('RGBA', size, core.PANEL_2)
            canvas.alpha_composite(rgba, ((size[0] - rgba.width) // 2, (size[1] - rgba.height) // 2))
            result = canvas.convert('RGB')
        self._gallery_thumb_cache[key] = result.copy()
        return result

    def _open_asset_gallery(self, key: str):
        entries = self._catalog()
        if not entries:
            if hasattr(self, 'settings_status'):
                self.settings_status.configure(text='선택 가능한 이미지가 없습니다.', fg=core.AMBER)
            return

        top = tk.Toplevel(self.root)
        top.title(f'{dict(self.IMAGE_ROWS).get(key, key)} · 이미지 갤러리')
        top.configure(bg=core.BG)
        width = min(self.GALLERY_SIZE[0], max(720, self.root.winfo_screenwidth() - 80))
        height = min(self.GALLERY_SIZE[1], max(560, self.root.winfo_screenheight() - 100))
        x = max(0, self.root.winfo_x() - max(0, width - self.root.winfo_width()) // 2)
        y = max(0, self.root.winfo_y() - 20)
        top.geometry(f'{width}x{height}+{x}+{y}')
        top.minsize(720, 560)
        top.transient(self.root)
        try:
            top.attributes('-topmost', bool(self.preferences.always_on_top))
        except tk.TclError:
            pass

        header = tk.Frame(top, bg=core.BG)
        header.pack(fill='x', padx=14, pady=(12, 7))
        self._label(header, f'{dict(self.IMAGE_ROWS).get(key, key)} 이미지 선택', size=12, bg=core.BG).pack(side='left')
        self._button(header, '랜덤', lambda: self._choose_random_manual(key), primary=True).pack(side='right', padx=(6, 0))
        self._button(header, '직전으로', lambda: self._undo_gallery_choice(key)).pack(side='right', padx=(6, 0))
        self._button(header, '세트 따라가기', lambda: self._follow_selected_set(key)).pack(side='right')

        filter_row = tk.Frame(top, bg=core.BG)
        filter_row.pack(fill='x', padx=14, pady=(0, 8))
        self._label(filter_row, '표시', size=9, fg=core.MUTED, bg=core.BG).pack(side='left')
        role_labels = [caption for _key, caption in self.IMAGE_ROWS]
        filter_var = tk.StringVar(value='전체')
        filter_menu = tk.OptionMenu(filter_row, filter_var, '전체', *role_labels, '기타')
        filter_menu.pack(side='left', padx=(8, 0))
        status = self._label(filter_row, '', size=9, fg=core.GREEN, bg=core.BG)
        status.pack(side='right')

        outer = tk.Frame(top, bg=core.BG)
        outer.pack(fill='both', expand=True, padx=12, pady=(0, 12))
        canvas = tk.Canvas(outer, bg=core.PANEL, highlightthickness=0, bd=0)
        scroll = tk.Scrollbar(outer, orient='vertical', command=canvas.yview)
        canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        canvas.pack(side='left', fill='both', expand=True)
        body = tk.Frame(canvas, bg=core.PANEL)
        window_id = canvas.create_window((0, 0), window=body, anchor='nw')
        body.bind('<Configure>', lambda _e: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>', lambda e: canvas.itemconfigure(window_id, width=e.width))

        photos: list[ImageTk.PhotoImage] = []
        top._gallery_photos = photos
        labels = dict(self.IMAGE_ROWS)
        reverse_labels = {caption: role for role, caption in self.IMAGE_ROWS}

        def set_status(path: Path):
            status.configure(text=f'선택됨: {path.name}')

        def choose(path: Path):
            self._apply_gallery_path(key, path)
            set_status(path)

        def rebuild(*_args):
            for child in body.winfo_children():
                child.destroy()
            photos.clear()
            wanted = filter_var.get()
            if wanted == '전체':
                visible = entries
            elif wanted == '기타':
                visible = [item for item in entries if item[0] == 'other']
            else:
                role = reverse_labels.get(wanted)
                visible = [item for item in entries if item[0] == role]

            grouped: dict[str, list[Path]] = {}
            for group_key, _group_label, path in visible:
                grouped.setdefault(group_key, []).append(path)

            row_index = 0
            group_order = [role for role, _caption in self.IMAGE_ROWS] + ['other']
            for group_key in group_order:
                paths = grouped.get(group_key)
                if not paths:
                    continue
                title = labels.get(group_key, '기타')
                self._label(body, f'{title} · {len(paths)}장', size=10, bg=core.PANEL).grid(
                    row=row_index, column=0, columnspan=6, sticky='w', padx=10, pady=(12, 5)
                )
                row_index += 1
                for idx, path in enumerate(paths):
                    r = row_index + idx // 6
                    c = idx % 6
                    card = tk.Frame(body, bg=core.PANEL_2, bd=0, highlightthickness=1, highlightbackground=core.BORDER)
                    card.grid(row=r, column=c, padx=5, pady=5, sticky='n')
                    try:
                        photo = ImageTk.PhotoImage(self._thumbnail_image(path))
                    except Exception:
                        core.log.exception('gallery thumbnail failed: %s', path)
                        continue
                    photos.append(photo)
                    button = tk.Button(
                        card, image=photo, command=lambda p=path: choose(p),
                        bg=core.PANEL_2, activebackground=core.BORDER,
                        bd=0, highlightthickness=0, cursor='hand2', padx=0, pady=0,
                    )
                    button.pack(padx=4, pady=(4, 2))
                    name = path.name if len(path.name) <= 20 else path.name[:17] + '…'
                    self._label(card, name, size=7, fg=core.MUTED, bg=core.PANEL_2).pack(padx=4, pady=(0, 5))
                row_index += (len(paths) + 5) // 6
            for col in range(6):
                body.grid_columnconfigure(col, weight=1)
            canvas.yview_moveto(0)

        filter_var.trace_add('write', rebuild)

        def wheel(event):
            delta = int(getattr(event, 'delta', 0))
            if delta:
                canvas.yview_scroll((-1 if delta > 0 else 1) * 3, 'units')
            return 'break'

        canvas.bind('<MouseWheel>', wheel)
        body.bind('<MouseWheel>', wheel)
        rebuild()
        manual = self._manual_override_path(key)
        if manual is not None:
            set_status(manual)


if __name__ == '__main__':
    if os.name != 'nt':
        raise SystemExit('Windows only')
    compact.enable_per_monitor_dpi_awareness()
    singleton = compact.SingleInstance()
    if not singleton.acquire():
        raise SystemExit(0)
    GalleryDesktopApp().run()
