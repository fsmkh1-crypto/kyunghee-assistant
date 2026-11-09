from __future__ import annotations

import json
from copy import deepcopy
import os
import shutil
import uuid
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
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
from image_catalog import ImageCatalog, valid_image, require_image
from image_actions import ImageActionController, BASE, FOLLOW
from asset_pack_import import import_numbered_pack, preview_numbered_pack, preview_role_images, adopt_legacy_imports
from asset_rotation import raw_complete_sets
from assistant_ai.ui_helpers import position_window


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
    FOLLOW_SENTINEL = FOLLOW
    IMPORTED_ASSET_DIR = core.DATA_DIR / 'imported_assets'

    def __init__(self):
        self._manual_asset_overrides = self._load_manual_overrides()
        self._gallery_previous: dict[str, str] = {}
        self._gallery_thumb_cache: dict[tuple, Image.Image] = {}
        self._image_preview_refs: dict[str, Path] = {}
        self._image_catalog = ImageCatalog({
            'builtin': asset_manager.ASSET_DIR, 'user': compact.USER_IMAGE_DIR,
            'userset': compact.USER_IMAGE_SET_DIR, 'imported': self.IMPORTED_ASSET_DIR,
        }, dict(self.IMAGE_ROWS))
        self._image_actions = ImageActionController(
            self.image_action_catalog, self._image_action_state, self._commit_image_action_state)
        try:
            self._asset_adoption = adopt_legacy_imports(asset_manager.ASSET_DIR, self.IMPORTED_ASSET_DIR)
        except Exception:
            core.log.exception('legacy image pack adoption failed; originals preserved')
        super().__init__()
        self._adopt_legacy_image_references()

    def _adopt_legacy_image_references(self):
        adoption = getattr(self, '_asset_adoption', {})
        numbers = set(adoption.get('copied', ())) | set(adoption.get('reused', ()))
        if not numbers:
            return
        state = self._image_action_state()
        migrated = dict(state)
        if str(state[BASE]) in numbers:
            migrated[BASE] = 'pack:' + str(state[BASE])
        for key, ref in state.items():
            if not ref.startswith('builtin:'):
                continue
            relative = ref.split(':', 1)[1]
            suffix = Path(relative).stem.rsplit('_', 1)[-1]
            if suffix in numbers and self._image_catalog.decode('imported:' + relative):
                migrated[key] = 'imported:' + relative
        if migrated != state:
            self._commit_image_action_state(migrated)

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
        return self._image_catalog.encode(path)

    def _decode_asset_ref(self, ref: str) -> Path | None:
        if str(ref).startswith('preview:'):
            path = self._image_preview_refs.get(ref)
            return path if path is not None and valid_image(path) else None
        return self._image_catalog.decode(ref, legacy_absolute=True)

    def _preview_ref(self, path: Path | None) -> str | None:
        if path is None or not valid_image(path):
            return None
        try:
            return self._image_catalog.encode(path)
        except ValueError:
            # Legacy external images may be previewed, but the model never gets
            # a filesystem path or an applicable action reference for them.
            for ref, known_path in self._image_preview_refs.items():
                if known_path == path:
                    return ref
            ref = 'preview:' + uuid.uuid4().hex
            self._image_preview_refs[ref] = Path(path)
            if len(self._image_preview_refs) > 512:
                self._image_preview_refs.pop(next(iter(self._image_preview_refs)))
            return ref

    def _manual_override_path(self, key: str) -> Path | None:
        # Missing or corrupt references are ignored without mutating the profile.
        return self._decode_asset_ref(self._manual_asset_overrides.get(key, ''))

    def _image_action_state(self) -> dict:
        state = dict(self._manual_asset_overrides)
        state.setdefault(BASE, getattr(getattr(self, 'preferences', None), 'builtin_image_set', 'random'))
        return state

    def image_action_catalog(self) -> dict:
        images = []
        for item in self._image_catalog.entries():
            value = item.public()
            suffix = item.path.stem.rsplit('_', 1)[-1]
            if suffix.isdigit() and len(suffix) == 2:
                value['set_id'] = ('pack:' if item.origin == 'imported' else '') + suffix
            images.append(value)
        sets = [{'id': 'canonical', 'label': '기본 모델'}, {'id': 'random', 'label': '랜덤 내장 세트'}]
        for origin, root in (('', asset_manager.ASSET_DIR), ('pack:', self.IMPORTED_ASSET_DIR)):
            for number in raw_complete_sets(root):
                if all(valid_image(root / role / f'{role}_{number:02d}.png') for role in asset_manager.VARIANT_FOLDERS):
                    sets.append({'id': f'{origin}{number:02d}', 'label': f"{'가져온' if origin else '내장'} 세트 {number:02d}"})
        role = getattr(self, 'character_role', None) or 'default'
        actual_path = None
        if getattr(self, '_random_gallery_active', False):
            actual_path = Path(self._random_gallery_last_path) if self._random_gallery_last_path else None
        elif hasattr(self, '_image_set_store') and hasattr(self, 'preferences'):
            custom, _mode, _center = self._custom_image(role)
            actual_path = custom or self._resolve_builtin_asset(role)
        actual_ref = None
        if actual_path:
            try:
                actual_ref = self._image_catalog.encode(actual_path)
            except ValueError:
                pass
        state = self._image_action_state()
        public_state = {key: ('legacy-user-image' if value.startswith('absolute:') else value)
                        for key, value in state.items()}
        return {'roles': [{'id': key, 'label': label} for key, label in self.IMAGE_ROWS],
                'sets': sets, 'images': images, 'current_state': public_state,
                'current_role': role, 'timer_role': getattr(self, '_timer_character_role', role),
                'actual_current_ref': actual_ref, 'actual_current_source': self.active_image_origin(),
                'temporary': bool(getattr(self, '_random_gallery_active', False)),
                'pinned': bool(getattr(self, '_random_gallery_pinned', False))}

    def propose_image_action(self, action: dict) -> dict:
        proposal = self._image_actions.propose(action)
        if proposal.get('status') != 'pending':
            return proposal
        action = proposal['action']
        labels = dict(self.IMAGE_ROWS)
        if action['kind'] == 'base_set':
            role = getattr(self, 'character_role', None) or 'default'
            key = self.ROLE_TO_SETTING.get(role, 'default')
            custom, _mode, _center = self._custom_image(role)
            before = custom or self._resolve_builtin_asset(role)
            if getattr(self, '_random_gallery_active', False) and self._random_gallery_last_path:
                before = Path(self._random_gallery_last_path)
            after = self._resolve_image_set_choice(role, action['set_id'])
            before_label = '현재 화면 · ' + self.active_image_origin()
            after_label = f"새 전체 세트 · {labels.get(key, key)} 예시 · 상황별 수동 지정 유지"
        else:
            key = action['role']
            role = self.SETTING_TO_CANONICAL_ROLE.get(key, 'default')
            custom, _mode, _center = self._custom_image(role)
            before = custom or self._resolve_builtin_asset(role)
            after = (self._decode_asset_ref(action['ref']) if action['kind'] == 'image'
                     else self._resolve_builtin_asset(role))
            before_label = f'현재 {labels[key]} 이미지'
            after_label = f"변경 후 {labels[key]} · {'전체 세트 따라가기' if action['kind'] == 'follow' else '수동 선택'}"
        preview = {
            'before_preview_ref': self._preview_ref(before), 'before_preview_label': before_label,
            'after_preview_ref': self._preview_ref(after), 'after_preview_label': after_label,
        }
        preview['preview_ref'] = preview['after_preview_ref']
        proposal.update(preview)
        self._image_actions.proposals[proposal['id']]['result'].update(preview)
        return proposal

    def apply_image_action(self, proposal_id: str) -> dict:
        result = self._image_actions.apply(proposal_id)
        action = result.get('action', {})
        if result.get('status') == 'applied' and result.get('changed') and action.get('role'):
            result['summary'] += ' · ' + self._image_application_summary(action['role'])
            if hasattr(self, 'settings_status'):
                self.settings_status.configure(text=result['summary'], fg=core.GREEN)
        return result

    def cancel_image_action(self, proposal_id: str) -> dict:
        return self._image_actions.cancel(proposal_id)

    def undo_image_action(self) -> dict:
        return self._image_actions.undo()

    def _commit_image_action_state(self, state: dict) -> None:
        previous = self._manual_asset_overrides
        self._manual_asset_overrides = dict(state)
        try:
            self._save_manual_overrides()
        except Exception:
            self._manual_asset_overrides = previous
            raise
        try:
            self._refresh_image_selection()
        except Exception:
            self._manual_asset_overrides = previous
            self._save_manual_overrides()
            try:
                self._refresh_image_selection()
            except Exception:
                core.log.exception('image display rollback refresh failed')
            raise

    def _refresh_image_selection(self):
        self._image_cache.clear()
        self._settings_preview_cache.clear()
        self._image_set_choices.clear()
        if hasattr(self, 'builtin_image_set_var'):
            self.builtin_image_set_var.set(self._builtin_base_label(self._image_action_state()[BASE]))
            # Global image choice applies immediately, independently of other
            # settings drafts. Update only that saved field, keeping other dirt.
            if hasattr(self, '_settings_saved_snapshot'):
                variables = self._settings_variables()
                saved = list(self._settings_saved_snapshot)
                saved[variables.index(self.builtin_image_set_var)] = self.builtin_image_set_var.get()
                self._settings_saved_snapshot = tuple(saved)
                self._settings_changed()
        for key, _caption in self.IMAGE_ROWS:
            if hasattr(self, 'image_name_vars'):
                path = self._manual_override_path(key)
                group = self._manual_group_paths(key)
                self.image_name_vars[key].set(path.name if path else (f'{len(group)}장 사용자 이미지' if group else ('세트 따라가기' if self._manual_asset_overrides.get(key) == FOLLOW else self._image_display_name(key, getattr(self.preferences, f'image_{key}', '')))))
        if getattr(self, 'character_role', None):
            role = self.character_role
            self.character_role = None
            self._set_character(role)
            self._apply_widget_appearance()
        if hasattr(self, 'settings_preview_image'):
            self._render_settings_preview()

    @staticmethod
    def _builtin_base_label(value: str) -> str:
        if str(value).startswith('pack:'):
            return '가져온 세트 ' + str(value).split(':', 1)[1]
        return compact.CompactDesktopApp._builtin_base_label(value)

    @staticmethod
    def _builtin_base_value(label: str) -> str:
        if str(label).startswith('가져온 세트 '):
            return 'pack:' + str(label).rsplit(' ', 1)[1]
        return compact.CompactDesktopApp._builtin_base_value(label)

    def active_image_origin(self) -> str:
        if getattr(self, '_random_gallery_active', False):
            return '주사위 · ' + ('고정됨' if getattr(self, '_random_gallery_pinned', False) else '다음 상황 전까지')
        role = getattr(self, 'character_role', 'default')
        key = self.ROLE_TO_SETTING.get(role, 'default')
        path = self._manual_override_path(key)
        if path:
            return f"{dict(self.IMAGE_ROWS).get(key, key)} · 수동 선택 · {path.name}"
        group = self._manual_group_paths(key)
        if group:
            return f"{dict(self.IMAGE_ROWS).get(key, key)} · 사용자 이미지 {len(group)}장"
        return f"{dict(self.IMAGE_ROWS).get(key, key)} · 전체 세트 {self._builtin_base_label(self._image_action_state()[BASE])}"

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
        if self._manual_asset_overrides.get(key) == FOLLOW:
            return None, 'fit', (0.5, 0.5)
        group = self._manual_group_paths(key)
        if group:
            selected = self._image_set_choices.get(role)
            if selected not in group:
                import random
                selected = random.SystemRandom().choice(group)
                self._image_set_choices[role] = selected
            mode, centering = self._manual_style(key)
            return selected, mode, centering
        manual = self._manual_override_path(key)
        if manual is not None:
            mode, centering = self._manual_style(key)
            return manual, mode, centering
        path, mode, centering = super()._custom_image(role)
        return (path if path is not None and valid_image(path) else None), mode, centering

    def _resolve_builtin_asset(self, role: str, *, controls: bool = False):
        return self._resolve_image_set_choice(role, self._image_action_state()[BASE])

    def _resolve_image_set_choice(self, role: str, base_set: str):
        if str(base_set).startswith('pack:'):
            number = str(base_set).split(':', 1)[1]
            path = asset_manager.variant_asset(role, int(number), self.IMPORTED_ASSET_DIR) if number.isdigit() else None
            return path if path and valid_image(path) else asset_manager.resolve_canonical_asset(role)
        path = asset_manager.resolve_configured_asset(role, base_set, '')
        return path if path and valid_image(path) else asset_manager.resolve_canonical_asset(role)

    def _base_set_preview_sources(self):
        base = self._image_action_state()[BASE]
        sources = [self._resolve_builtin_asset(self.SETTING_TO_CANONICAL_ROLE.get(key, 'default'))
                   for key, _caption in self.IMAGE_ROWS]
        return [path for path in sources if path and valid_image(path)], self._builtin_base_label(base)

    def _role_base_preview_sources(self, key: str):
        # Start on the edited role, then let Previous/Next browse all situations
        # in the selected set. This list is for preview only; it never changes
        # the role selector, manual overrides, or the current timer character.
        rows = list(self.IMAGE_ROWS)
        start = next((index for index, (role_key, _caption) in enumerate(rows) if role_key == key), 0)
        rows = rows[start:] + rows[:start]
        sources = [self._resolve_builtin_asset(self.SETTING_TO_CANONICAL_ROLE.get(role_key, 'default'))
                   for role_key, _caption in rows]
        return ([path for path in sources if path and valid_image(path)],
                '전체 세트 · ' + self._builtin_base_label(self._image_action_state()[BASE]))

    def _settings_preview_sources(self, key: str):
        group = self._manual_group_paths(key)
        if group:
            return list(group), '사용자 이미지'
        if self._manual_asset_overrides.get(key) == FOLLOW:
            return self._role_base_preview_sources(key)
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
        if legacy and valid_image(legacy):
            return [legacy], '사용자 이미지'

        return self._role_base_preview_sources(key)

    def _preview_role_for_path(self, source: Path) -> str | None:
        parent = source.parent.name
        labels = dict(self.IMAGE_ROWS)
        return labels.get(parent)

    def _select_settings_preview(self, key: str):
        if key != getattr(self, '_settings_preview_role', None):
            self._settings_preview_indices[key] = 0
        super()._select_settings_preview(key)

    def _render_settings_preview(self, key=None):
        if not hasattr(self, 'settings_preview_image'):
            return
        key = key or self._settings_preview_role
        self._settings_preview_role = key
        sources, source_kind = self._settings_preview_sources(key)
        # A new base/manual set starts at its edited role instead of carrying
        # a browsing offset from the previous collection into the new preview.
        signatures = getattr(self, '_settings_preview_source_signatures', {})
        signature = tuple(str(path) for path in sources)
        if signatures.get(key) != signature:
            self._settings_preview_indices[key] = 0
            signatures[key] = signature
        self._settings_preview_source_signatures = signatures
        default_caption = dict(self.IMAGE_ROWS).get(key, key)
        self._settings_preview_current_path = None
        if hasattr(self, '_settings_preview_apply_button'):
            self._settings_preview_apply_button.configure(text=f'{default_caption} 이미지로 적용', state='normal' if sources else 'disabled')
        if hasattr(self, '_image_applied_label'):
            role = self.SETTING_TO_CANONICAL_ROLE.get(key, 'default')
            custom, _mode, _center = self._custom_image(role)
            applied = custom or self._resolve_builtin_asset(role)
            origin = '상황별 지정' if custom else '전체 세트 따라가기'
            self._image_applied_label.configure(text=f'적용 중인 {default_caption}: {applied.name if applied else "이미지 없음"} · {origin}')
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
        source = self._settings_preview_current_path = Path(sources[index])
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
        browsing_base = source_kind.startswith('전체 세트 · ')
        title = f'미리보기: {role_caption or default_caption}' if browsing_base else default_caption
        self.settings_preview_title.configure(text=title)
        meta = f'{source_kind} · {index + 1}/{len(sources)} · {source.name}'
        if browsing_base:
            meta = f'설정 대상: {default_caption}\n' + meta
        if len(sources) == 1:
            meta += '\n1장만 등록되어 있어 이전·다음을 사용할 수 없습니다.'
        meta += '\n이전·다음은 둘러보기만 · 선택/저장 변경 없음'
        if hasattr(self, '_settings_preview_apply_button'):
            meta += f'\n이 그림을 쓰려면 ‘{default_caption} 이미지로 적용’을 누르세요.'
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
                if not isinstance(widget, (tk.Menubutton, ttk.Combobox)):
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
                if not parent.pack_slaves():
                    parent.pack_forget()

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
            row = getattr(self, '_image_role_action_rows', {}).get(key) or self._find_role_row(caption)
            if row is None:
                continue
            for child in row.winfo_children():
                if isinstance(child, tk.Button) and child.cget('text') == '기본값':
                    child.configure(text='세트 따라가기')
            gallery_button = self._button(row, '갤러리', lambda k=key: self._open_asset_gallery(k))
            random_button = self._button(row, '랜덤', lambda k=key: self._choose_random_manual(k))
            if key in getattr(self, '_image_role_action_rows', {}):
                gallery_button.grid(row=1, column=1, sticky='ew', padx=2, pady=2)
                random_button.grid(row=1, column=2, sticky='ew', padx=2, pady=2)
            else:
                gallery_button.pack(side='left', padx=2)
                random_button.pack(side='left', padx=2)
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
        self._build_image_detail_controls()
        self._render_settings_preview('default')
        if hasattr(self, '_settings_snapshot'):
            self._settings_saved_snapshot = self._settings_snapshot()

    def _discard_settings(self):
        super()._discard_settings()
        self._refresh_global_set_picker()
        self._render_settings_preview()
        if hasattr(self, '_settings_snapshot'):
            self._settings_saved_snapshot = self._settings_snapshot()
            self._settings_changed()

    def _set_manual_override(self, key: str, ref: str) -> None:
        action = {'kind': 'follow', 'role': key} if ref == FOLLOW else {'kind': 'image', 'role': key, 'ref': ref}
        proposal = self.propose_image_action(action)
        if proposal.get('status') != 'pending':
            raise ValueError(proposal['summary'])
        result = self.apply_image_action(proposal['id'])
        if result.get('status') != 'applied':
            raise ValueError(result['summary'])

    def _image_application_summary(self, key: str) -> str:
        caption = dict(self.IMAGE_ROWS).get(key, key)
        if getattr(self, '_random_gallery_active', False) and getattr(self, '_random_gallery_pinned', False):
            return f'{caption} 이미지로 저장됨 · 주사위 고정 해제 시 해당 상황에서 표시'
        current_key = self.ROLE_TO_SETTING.get(getattr(self, 'character_role', None), 'default')
        if current_key != key:
            return f'{caption}로 저장됨 · {caption} 전환 때 표시'
        return f'{caption} 이미지 적용됨 · 즉시 저장 · 되돌리기 가능'

    def _apply_settings_preview(self):
        key = self._settings_preview_role
        path = getattr(self, '_settings_preview_current_path', None)
        if path is None:
            return
        try:
            require_image(path)
            try:
                self._encode_asset_ref(path)
            except ValueError:
                # Preserve legacy external images by importing a copy before
                # applying an app-owned reference to the selected situation.
                self._import_role_images(key, [path])
            else:
                self._apply_gallery_path(key, path)
            self.settings_status.configure(text=self._image_application_summary(key), fg=core.GREEN)
        except Exception as exc:
            core.log.exception('settings preview image could not be applied')
            self.settings_status.configure(text=f'이미지 적용 실패 · 기존 선택 유지: {exc}', fg=core.AMBER)

    def _apply_gallery_path(self, key: str, path: Path) -> None:
        self._set_manual_override(key, self._encode_asset_ref(path))
        if hasattr(self, 'settings_status'):
            self.settings_status.configure(text=self._image_application_summary(key), fg=core.GREEN)

    def _follow_selected_set(self, key: str) -> None:
        self._set_manual_override(key, FOLLOW)

    def _reset_image(self, key):
        self._follow_selected_set(key)

    def _import_role_images(self, key: str, paths) -> None:
        sources = [require_image(Path(path)) for path in paths]
        before = self._image_action_state()
        created = []
        try:
            compact.USER_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
            for source in sources:
                destination = compact.USER_IMAGE_DIR / f'{key}_{uuid.uuid4().hex}{source.suffix.lower()}'
                created.append(destination)
                shutil.copy2(source, destination)
                require_image(destination)
            refs = [self._encode_asset_ref(path) for path in created]
            after = dict(before)
            after[key] = refs[0] if len(refs) == 1 else 'userset-group:' + json.dumps(refs)
            self._commit_image_action_state(after)
            self._image_actions.history.append((before, dict(after)))
        except Exception:
            for path in created:
                path.unlink(missing_ok=True)
            raise

    def _manual_group_paths(self, key):
        value = self._manual_asset_overrides.get(key, '')
        if not value.startswith('userset-group:'):
            return ()
        try:
            refs = json.loads(value[len('userset-group:'):])
            if not isinstance(refs, list):
                return ()
            return tuple(path for ref in refs if isinstance(ref, str)
                         if (path := self._decode_asset_ref(ref)) is not None)
        except (ValueError, TypeError):
            return ()

    def _choose_image(self, key):
        selected = filedialog.askopenfilename(parent=self.root, title='이미지 선택', filetypes=[('이미지', '*.png *.jpg *.jpeg *.webp')])
        if selected:
            self._import_role_images_safe(key, [selected])

    def _choose_image_set(self, key):
        selected = filedialog.askopenfilenames(parent=self.root, title='여러 이미지 선택', filetypes=[('이미지', '*.png *.jpg *.jpeg *.webp')])
        if selected:
            self._import_role_images_safe(key, selected)

    def _choose_image_folder(self, key):
        selected = filedialog.askdirectory(parent=self.root, title='이미지 폴더 선택')
        if selected:
            sources = sorted(path for path in Path(selected).iterdir() if path.suffix.lower() in SUPPORTED_IMAGE_SUFFIXES)
            self._import_role_images_safe(key, sources)

    def _import_role_images_safe(self, key, sources):
        try:
            if not sources:
                raise ValueError('지원하는 이미지가 없습니다.')
            self._import_role_images(key, sources)
            self.settings_status.configure(text='이미지 가져오기 완료 · ' + self._image_application_summary(key), fg=core.GREEN)
        except Exception as exc:
            core.log.exception('role image import failed; previous selection preserved')
            self.settings_status.configure(text=f'이미지 가져오기 실패: {exc}', fg=core.AMBER)

    def _catalog(self):
        return [(item.role, dict(self.IMAGE_ROWS).get(item.role, '기타'), item.path)
                for item in self._image_catalog.entries()]

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
        result = self.undo_image_action()
        if hasattr(self, 'settings_status'):
            self.settings_status.configure(text=result['summary'])

    def _thumbnail_image(self, path: Path, size=(112, 132)) -> Image.Image:
        try:
            stat = path.stat()
            key = (str(path), stat.st_mtime_ns, stat.st_size, tuple(size))
        except OSError:
            key = (str(path), 0, 0, tuple(size))
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
        if len(self._gallery_thumb_cache) > 120:
            self._gallery_thumb_cache.pop(next(iter(self._gallery_thumb_cache)))
        return result

    def _refresh_global_set_picker(self):
        values = [self._builtin_base_label(item['id']) for item in self.image_action_catalog()['sets']]
        for widget in self._all_descendants(self.settings_page):
            if isinstance(widget, ttk.Combobox) and str(widget.cget('textvariable')) == str(self.builtin_image_set_var):
                widget.configure(values=values)
                widget._selection_command = self._choose_base_set
        self.builtin_image_set_var.set(self._builtin_base_label(self._image_action_state()[BASE]))

    def _choose_base_set(self, label):
        proposal = self.propose_image_action({'kind': 'base_set', 'set_id': self._builtin_base_value(label)})
        if proposal.get('status') == 'pending':
            result = self.apply_image_action(proposal['id'])
        else:
            result = proposal
        if hasattr(self, 'settings_status'):
            self.settings_status.configure(text=result['summary'])

    def _build_image_detail_controls(self):
        section = getattr(self, '_settings_sections', {}).get('images')
        if section is None:
            section = self.settings_preview_image.master.master
        row = tk.Frame(section, bg=core.PANEL)
        row.pack(fill='x', padx=14, pady=5, before=section.winfo_children()[0])
        self._button(row, 'ZIP 세트 가져오기', self._open_asset_pack_import).pack(side='left')
        self._button(row, '직전 이미지 변경 취소', self.undo_image_action).pack(side='left', padx=5)
        self._label(row, '선택 후 적용 버튼 · 되돌리기 가능', size=8, fg=core.MUTED, bg=core.PANEL).pack(side='left', padx=5)
        conflicts = getattr(self, '_asset_adoption', {}).get('conflicts', [])
        if conflicts:
            self._label(section, '기존 세트 ' + ', '.join(conflicts) + '은 다른 내용 때문에 자동 복사하지 않았습니다. 설치 폴더 원본은 보존됩니다.', size=8, fg=core.AMBER, bg=core.PANEL, wraplength=700).pack(fill='x', padx=14)
        rows = getattr(self, '_image_role_rows', {})
        if rows:
            role_row = tk.Frame(section, bg=core.PANEL)
            role_row.pack(fill='x', padx=14, pady=6, after=row)
            self._label(role_row, '상황', size=9, bg=core.PANEL).pack(side='left')
            role_var = self._image_role_var = tk.StringVar(value=dict(self.IMAGE_ROWS)['default'])
            selector = self._image_role_selector = ttk.Combobox(role_row, textvariable=role_var, state='readonly', values=[caption for _, caption in self.IMAGE_ROWS])
            selector.pack(side='left', padx=6)
            details = self._image_role_detail_frame
            details.pack_forget()
            details.pack(fill='x', padx=4, after=role_row)
            def select_role(_event=None):
                key = next((key for key, caption in self.IMAGE_ROWS if caption == role_var.get()), 'default')
                for other, pair in rows.items():
                    for widget in pair:
                        widget.pack_forget()
                        if other == key:
                            widget.pack(fill='x', padx=10, pady=3)
                self._select_settings_preview(key)
            selector.bind('<<ComboboxSelected>>', select_role)
            select_role()
        preview_info = self.settings_preview_title.master
        self._image_applied_label = self._label(preview_info, '', size=9, fg=core.GREEN, bg=core.PANEL_2, wraplength=350, justify='left')
        self._image_applied_label.pack(anchor='w', before=self.settings_preview_title, pady=(0, 8))
        self._settings_preview_apply_button = self._button(preview_info, '평상시 이미지로 적용', self._apply_settings_preview, primary=True)
        self._settings_preview_apply_button.pack(anchor='w', pady=(10, 0))
        self._refresh_global_set_picker()

    def _open_asset_pack_import(self):
        source = filedialog.askopenfilename(parent=self.root, title='10개 역할 이미지 ZIP 가져오기', filetypes=[('이미지 세트 ZIP', '*.zip')])
        if not source:
            return
        try:
            preview = preview_numbered_pack(Path(source), self.IMPORTED_ASSET_DIR)
            preview_images = preview_role_images(Path(source))
            source_stat = Path(source).stat()
            source_signature = (source_stat.st_mtime_ns, source_stat.st_size)
        except Exception as exc:
            messagebox.showerror('이미지 ZIP 확인', str(exc), parent=self.root)
            return
        top = tk.Toplevel(self.root)
        top.title('이미지 ZIP 미리보기')
        top.configure(bg=core.PANEL)
        top.transient(self.root)
        top.geometry('550x540')
        summary = (f'{Path(source).name}\n10개 역할 완전성·이미지 읽기 검사 통과\n'
                   f"세트: {', '.join(preview.sets)} · 추가 {preview.added}장 · 동일 파일 재사용 {preview.identical}장\n"
                   '가져온 세트는 사용자 보관함에 저장됩니다. 기본 그림은 유지됩니다.')
        self._label(top, summary, size=10, bg=core.PANEL, wraplength=470, justify='left').pack(fill='x', padx=18, pady=18)
        previews = tk.Frame(top, bg=core.PANEL)
        previews.pack(fill='x', padx=12)
        top._import_previews = []
        for index, (role, preview_image) in enumerate(preview_images):
            card = tk.Frame(previews, bg=core.PANEL_2, width=96, height=115)
            card.grid(row=index // 5, column=index % 5, padx=3, pady=3)
            card.pack_propagate(False)
            photo = ImageTk.PhotoImage(preview_image)
            top._import_previews.append(photo)
            tk.Label(card, image=photo, bg=core.PANEL_2).pack()
            self._label(card, dict(self.IMAGE_ROWS).get(role, role), size=8, bg=core.PANEL_2).pack()
        result_label = self._label(top, '', size=9, fg=core.GREEN, bg=core.PANEL, wraplength=470)
        result_label.pack(fill='x', padx=18)
        buttons = tk.Frame(top, bg=core.PANEL)
        buttons.pack(side='bottom', fill='x', padx=18, pady=18)
        self._button(buttons, '취소', top.destroy).pack(side='right')
        def perform():
            try:
                current_stat = Path(source).stat()
                if (current_stat.st_mtime_ns, current_stat.st_size) != source_signature:
                    raise ValueError('미리보기 이후 ZIP이 변경되었습니다. 다시 선택해 주세요.')
                result = import_numbered_pack(Path(source), self.IMPORTED_ASSET_DIR)
                self._gallery_thumb_cache.clear()
                self._refresh_global_set_picker()
                self._settings_preview_cache.clear()
                result_label.configure(text=f'가져오기 완료: 추가 {result.added}장 · 재사용 {result.identical}장\n전체 세트 메뉴와 갤러리에 바로 표시됩니다.')
                apply_button.configure(state='disabled')
                if result.sets:
                    self._button(buttons, '이 세트 적용', lambda: self._choose_base_set('가져온 세트 ' + result.sets[0]), primary=True).pack(side='left')
                self.settings_status.configure(text='ZIP 가져오기 완료 · 새 세트를 선택할 수 있습니다.', fg=core.GREEN)
            except Exception as exc:
                result_label.configure(text=f'가져오기 실패 · 기존 파일 유지: {exc}', fg=core.AMBER)
        apply_button = self._button(buttons, '가져오기', perform, primary=True)
        apply_button.pack(side='right', padx=8)
        top.bind('<Escape>', lambda _event: top.destroy())
        position_window(top, self.root, work_area=self._best_work_area)

    def _open_asset_gallery(self, key: str = 'default'):
        entries = self._catalog()
        if key not in dict(self.IMAGE_ROWS):
            key = 'default'
        top = tk.Toplevel(self.root)
        top.title(f'{dict(self.IMAGE_ROWS)[key]} · 이미지 선택')
        top.configure(bg=core.BG)
        width = min(self.GALLERY_SIZE[0], max(480, self.root.winfo_screenwidth() - 80))
        height = min(self.GALLERY_SIZE[1], max(420, self.root.winfo_screenheight() - 100))
        top.geometry(f'{width}x{height}')
        top.minsize(450, 420)
        top.transient(self.root)
        header = tk.Frame(top, bg=core.BG)
        header.pack(fill='x', padx=12, pady=10)
        self._label(header, f'{dict(self.IMAGE_ROWS)[key]} 상황에 적용', size=11, bg=core.BG).pack(side='left')
        status = self._label(top, '이미지를 선택해 미리 본 뒤 적용하세요.', size=9, fg=core.GREEN, bg=core.BG)
        status.pack(fill='x', padx=12)
        controls = tk.Frame(top, bg=core.BG)
        controls.pack(fill='x', padx=12, pady=8)
        filter_var, search_var = tk.StringVar(value='전체'), tk.StringVar()
        picker = ttk.Combobox(controls, textvariable=filter_var, state='readonly', values=['전체', *dict(self.IMAGE_ROWS).values(), '기타'], width=16)
        picker.pack(side='left')
        ttk.Entry(controls, textvariable=search_var, width=20).pack(side='left', padx=8)
        self._label(controls, '파일 이름 검색', size=8, fg=core.MUTED, bg=core.BG).pack(side='left')
        pending = {'proposal': None}
        cards, photos = [], {}
        comparison = tk.Frame(top, bg=core.PANEL)
        comparison_photos = []
        top._comparison_photos = comparison_photos
        top._gallery_photos = photos
        footer = tk.Frame(top, bg=core.BG)
        footer.pack(side='bottom', fill='x', padx=12, pady=10)
        def cancel():
            if pending['proposal']:
                self.cancel_image_action(pending['proposal']['id'])
            top.destroy()
        self._button(footer, '취소', cancel).pack(side='right')
        top.protocol('WM_DELETE_WINDOW', cancel)
        top.bind('<Escape>', lambda _event: cancel())
        def apply():
            proposal = pending['proposal']
            if proposal:
                result = self.apply_image_action(proposal['id'])
                status.configure(text=result['summary'])
                pending['proposal'] = None
                apply_button.configure(state='disabled')
                comparison.pack_forget()
                comparison_photos.clear()
                mark_selected()
        apply_button = self._button(footer, '적용', apply, primary=True)
        apply_button.configure(state='disabled')
        apply_button.pack(side='right', padx=6)
        def undo():
            result = self.undo_image_action()
            status.configure(text=result['summary'])
            comparison.pack_forget()
            comparison_photos.clear()
            mark_selected()
        self._button(footer, '되돌리기', undo).pack(side='left')
        def propose(action):
            if pending['proposal']:
                self.cancel_image_action(pending['proposal']['id'])
            result = self.propose_image_action(action)
            pending['proposal'] = result if result.get('status') == 'pending' else None
            apply_button.configure(state='normal' if pending['proposal'] else 'disabled')
            status.configure(text=result['summary'] + (' · 적용 전' if pending['proposal'] else ''))
            for child in comparison.winfo_children():
                child.destroy()
            comparison_photos.clear()
            if pending['proposal']:
                for prefix in ('before', 'after'):
                    side = tk.Frame(comparison, bg=core.PANEL)
                    side.pack(side='left', fill='x', expand=True, padx=6, pady=4)
                    path = self._decode_asset_ref(result.get(prefix + '_preview_ref') or '')
                    if path is not None:
                        photo = ImageTk.PhotoImage(self._thumbnail_image(path, size=(72, 84)))
                        comparison_photos.append(photo)
                        tk.Label(side, image=photo, bg=core.PANEL).pack(side='left')
                    self._label(side, result.get(prefix + '_preview_label', ''), size=8, bg=core.PANEL, wraplength=180).pack(side='left', padx=5)
                comparison.pack(side='bottom', fill='x', padx=12, before=outer)
            else:
                comparison.pack_forget()
            mark_selected()
        self._button(footer, '세트 따라가기', lambda: propose({'kind': 'follow', 'role': key})).pack(side='left', padx=6)
        def random_proposal():
            ref = next_nonrepeating_ref(self._catalog_refs(), self.GALLERY_RANDOM_FILE)
            if ref:
                propose({'kind': 'image', 'role': key, 'ref': ref})
        self._button(footer, '랜덤 미리보기', random_proposal).pack(side='left')
        outer = tk.Frame(top, bg=core.BG)
        outer.pack(fill='both', expand=True, padx=10)
        canvas = tk.Canvas(outer, bg=core.PANEL, highlightthickness=0)
        scroll = ttk.Scrollbar(outer, orient='vertical')
        scroll.pack(side='right', fill='y')
        canvas.pack(side='left', fill='both', expand=True)
        body = tk.Frame(canvas, bg=core.PANEL)
        window_id = canvas.create_window((0, 0), window=body, anchor='nw')
        layout = {'columns': 0, 'job': None, 'filter': None}
        def mark_selected():
            selected = self._manual_asset_overrides.get(key)
            if self._decode_asset_ref(selected or '') is None:
                role = self.SETTING_TO_CANONICAL_ROLE.get(key, 'default')
                custom, _mode, _center = self._custom_image(role)
                current_path = custom or self._resolve_builtin_asset(role)
                selected = self._encode_asset_ref(current_path) if current_path and valid_image(current_path) else None
            preview = (pending['proposal'] or {}).get('preview_ref')
            for card, _button, _path, ref in cards:
                card.configure(highlightbackground=core.GREEN if ref == preview else (core.AMBER if ref == selected else core.BORDER), highlightthickness=2 if ref in {selected, preview} else 1)
        def load_visible():
            if not top.winfo_exists():
                return
            low, high = canvas.canvasy(0) - 170, canvas.canvasy(canvas.winfo_height()) + 170
            for card, button, path, ref in cards:
                visible = card.winfo_y() + card.winfo_height() >= low and card.winfo_y() <= high
                if visible and ref not in photos:
                    try:
                        photos[ref] = ImageTk.PhotoImage(self._thumbnail_image(path))
                        button.configure(image=photos[ref], text='', width=112, height=132)
                    except Exception:
                        button.configure(text='읽기 실패', state='disabled')
                elif not visible and ref in photos:
                    button.configure(image='', text='…', width=14, height=8)
                    photos.pop(ref, None)
        def view(*args):
            canvas.yview(*args)
            top.after_idle(load_visible)
        scroll.configure(command=view)
        canvas.configure(yscrollcommand=scroll.set)
        def ensure_visible(card):
            body.update_idletasks()
            total = max(1, body.winfo_height())
            card_top, card_bottom = card.winfo_y(), card.winfo_y() + card.winfo_height()
            visible_top = canvas.canvasy(0)
            if card_top < visible_top:
                canvas.yview_moveto(card_top / total)
            elif card_bottom > visible_top + canvas.winfo_height():
                canvas.yview_moveto(max(0, card_bottom - canvas.winfo_height()) / total)
            load_visible()
        def rebuild(*_args):
            if layout['job']:
                top.after_cancel(layout['job'])
                layout['job'] = None
            columns = max(1, canvas.winfo_width() // 145)
            old_columns = layout['columns']
            wanted, query = filter_var.get(), search_var.get().strip().casefold()
            same_filter = layout['filter'] == (wanted, query)
            scroll_position = canvas.yview()[0] if same_filter else 0
            focused = top.focus_get()
            focused_card = next((card for card, button, _path, _ref in cards if button == focused), None)
            layout.update(columns=columns, filter=(wanted, query))
            if same_filter:
                # Resize only reflows existing cards. Destroying/recreating them
                # loses keyboard focus and can reset a user's scroll after the
                # delayed Configure callback, especially with warm image caches.
                for index, (card, _button, _path, _ref) in enumerate(cards):
                    card.grid_configure(row=index // columns, column=index % columns)
            else:
                focused_card = None
                for child in body.winfo_children():
                    child.destroy()
                cards.clear()
                photos.clear()
                visible = [entry for entry in entries if (wanted == '전체' or entry[1] == wanted) and query in entry[2].name.casefold()]
                for index, (_group, caption, path) in enumerate(visible):
                    ref = self._encode_asset_ref(path)
                    card = tk.Frame(body, bg=core.PANEL_2, highlightthickness=1, highlightbackground=core.BORDER, width=132, height=185)
                    card.grid(row=index // columns, column=index % columns, sticky='n', padx=5, pady=5)
                    card.pack_propagate(False)
                    button = tk.Button(card, text='…', width=14, height=8, bg=core.PANEL_2, bd=0,
                                       takefocus=True, highlightthickness=2, highlightbackground=core.PANEL_2, highlightcolor=core.GREEN,
                                       command=lambda r=ref: propose({'kind': 'image', 'role': key, 'ref': r}))
                    button.bind('<FocusIn>', lambda _event, c=card: ensure_visible(c))
                    for sequence in ('<Return>', '<space>'):
                        button.bind(sequence, lambda _event, b=button: (b.invoke(), 'break')[1])
                    button.pack(padx=4, pady=4)
                    label = path.name if len(path.name) < 20 else path.name[:17] + '…'
                    self._label(card, label, size=7, bg=core.PANEL_2).pack()
                    self._label(card, caption, size=7, fg=core.MUTED, bg=core.PANEL_2).pack()
                    cards.append((card, button, path, ref))
            for column in range(max(old_columns, columns)):
                body.grid_columnconfigure(column, weight=1 if column < columns else 0)
            body.update_idletasks()
            canvas.configure(scrollregion=canvas.bbox('all'))
            if focused_card is not None:
                ensure_visible(focused_card)
            else:
                canvas.yview_moveto(scroll_position)
            mark_selected()
            load_visible()
        def configure(event):
            canvas.itemconfigure(window_id, width=event.width)
            if max(1, event.width // 145) != layout['columns']:
                if layout['job']:
                    top.after_cancel(layout['job'])
                layout['job'] = top.after(60, rebuild)
            top.after_idle(load_visible)
        canvas.bind('<Configure>', configure)
        body.bind('<Configure>', lambda _event: canvas.configure(scrollregion=canvas.bbox('all')))
        def wheel(event):
            delta = int(getattr(event, 'delta', 0))
            amount = (-1 if delta > 0 else 1) * 3 if delta else (-3 if getattr(event, 'num', 0) == 4 else 3)
            view('scroll', amount, 'units')
            return 'break'
        # Toplevel bindtag runs for thumbnail descendants before bind_all, so
        # settings behind the gallery never consumes this wheel event.
        for sequence in ('<MouseWheel>', '<Button-4>', '<Button-5>'):
            top.bind(sequence, wheel)
        filter_var.trace_add('write', rebuild)
        search_var.trace_add('write', rebuild)
        top.after_idle(rebuild)
        position_window(top, self.root, work_area=self._best_work_area)


if __name__ == '__main__':
    if os.name != 'nt':
        raise SystemExit('Windows only')
    compact.enable_per_monitor_dpi_awareness()
    singleton = compact.SingleInstance()
    if not singleton.acquire():
        raise SystemExit(0)
    GalleryDesktopApp().run()
