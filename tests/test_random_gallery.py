"""Real Tk integration checks; synthetic imports, isolated profile, no network."""
from dataclasses import asdict
import json
import zipfile
import os
from pathlib import Path
import tempfile
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import patch
from PIL import Image, ImageTk

os.environ.setdefault('PYSTRAY_BACKEND', 'dummy')

import app as core
import compact_runtime_features as runtime
from desktop_gallery import GalleryDesktopApp
from desktop_gallery_final import FinalGalleryDesktopApp
from settings import UserSettings
from state import fresh_state


class RandomGalleryTkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            root = tk.Tk()
            root.destroy()
        except tk.TclError:
            raise unittest.SkipTest('A display is needed for real Tk gallery controls')

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='seunga-image-test-')
        self.addCleanup(self.directory.cleanup)
        self.data = Path(self.directory.name)
        self.settings = self.data / 'settings.json'
        self.preferences = UserSettings(welcome_seen=True, break_reminders=False,
                                       workday_reminders=False, builtin_image_set='01')
        self.settings.write_text(json.dumps(asdict(self.preferences)), encoding='utf-8')
        patches = (
            patch('app.DATA_DIR', self.data), patch('app.STATE_FILE', self.data / 'state.json'),
            patch('app.SETTINGS_FILE', self.settings),
            patch('app.load_user_settings', return_value=self.preferences),
            patch('app.load_state', side_effect=lambda _: fresh_state()),
            patch('app.App._start_tray'),
            patch('desktop_compact.USER_IMAGE_DIR', self.data / 'images'),
            patch('desktop_compact.USER_IMAGE_SET_DIR', self.data / 'image_sets'),
            patch.object(GalleryDesktopApp, 'MANUAL_OVERRIDE_FILE', self.data / 'manual_asset_overrides.json'),
            patch.object(GalleryDesktopApp, 'GALLERY_RANDOM_FILE', self.data / 'shuffle.json'),
            patch.object(GalleryDesktopApp, 'IMPORTED_ASSET_DIR', self.data / 'imported_assets'),
            patch('desktop_compact.CompactDesktopApp._start_global_hotkey'),
            patch('desktop_compact.should_suppress_overlay_notifications', return_value=False),
            patch('urllib.request.urlopen', side_effect=AssertionError('No real API in tests')),
        )
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        self.app = FinalGalleryDesktopApp()
        for token in self.app.root.tk.call('after', 'info'):
            self.app.root.after_cancel(token)
        self.app.root.update()
        self.addCleanup(self.close)

    def close(self):
        self.app._assistant_shutdown.set()
        if self.app._assistant_windows:
            self.app._assistant_windows.close()
        for token in self.app.root.tk.call('after', 'info'):
            self.app.root.after_cancel(token)
        self.app.root.destroy()

    def fixture(self, name, color):
        path = self.data / name
        Image.new('RGBA', (80, 120), color).save(path)
        return path

    def test_final_entry_dice_is_visible_temporary_and_pin_is_explicit(self):
        app = self.app
        self.assertTrue(app.random_gallery_control.winfo_ismapped())
        before = app._image_action_state()
        self.assertEqual(str(app.random_gallery_control.cget('takefocus')), '1')
        self.assertGreater(int(app.random_gallery_control.cget('highlightthickness')), 0)
        app.root.focus_force()
        app.random_gallery_control.focus_set()
        app.root.update()
        app.random_gallery_control.event_generate('<Return>')
        self.assertTrue(app._random_gallery_active)
        self.assertEqual(app._image_action_state(), before)
        app._set_character(app.character_role)
        self.assertFalse(app._random_gallery_active)
        runtime._show_random_gallery_image(app)
        app.random_gallery_pin.focus_set()
        app.root.update()
        app.random_gallery_pin.event_generate('<space>')
        self.assertTrue(app._random_gallery_pinned)
        app._set_character('away')
        self.assertTrue(app._random_gallery_active)
        self.assertEqual(app._random_gallery_state_role, 'away')
        app.random_gallery_restore.focus_set()
        app.root.update()
        app.random_gallery_restore.event_generate('<Return>')
        self.assertEqual(app.character_role, 'away')
        self.assertFalse(app._random_gallery_active)
        self.assertFalse(app._random_gallery_pinned)

    def test_role_choice_apply_undo_and_failed_save_preserve_previous_selection(self):
        app = self.app
        red = self.fixture('red.png', 'red')
        blue = self.fixture('blue.png', 'blue')
        app._import_role_images('rest', [red])
        selected = app._manual_override_path('rest')
        previous = app._image_action_state()
        with patch.object(app, '_save_manual_overrides', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                app._import_role_images('rest', [blue])
        self.assertEqual(app._image_action_state(), previous)
        self.assertTrue(selected.exists())
        app._import_role_images('rest', [blue])
        self.assertNotEqual(app._manual_override_path('rest'), selected)
        self.assertEqual(app.undo_image_action()['status'], 'undone')
        self.assertEqual(app._manual_override_path('rest'), selected)
        app._set_character('rest')
        self.assertEqual(app._custom_image('rest')[0], selected)
        app._set_character('away')
        self.assertNotEqual(app._custom_image('away')[0], selected)

    def test_multi_import_undo_preserves_files_and_old_selection(self):
        app = self.app
        red = self.fixture('red.png', 'red')
        blue = self.fixture('blue.png', 'blue')
        before = app._image_action_state()
        app._import_role_images('rest', [red, blue])
        group = app._manual_group_paths('rest')
        self.assertEqual(len(group), 2)
        self.assertIn(app._custom_image('rest')[0], group)
        self.assertEqual(app.undo_image_action()['status'], 'undone')
        self.assertEqual(app._image_action_state(), before)
        self.assertTrue(all(path.exists() for path in group))

    def test_one_role_panel_retired_selectors_and_thumbnail_wheel(self):
        app = self.app
        app._show_page('settings')
        app.root.update()
        visible = {key for key, pair in app._image_role_rows.items() if any(widget.winfo_ismapped() for widget in pair)}
        self.assertLessEqual(visible, {'default'})
        retired = {str(variable) for variable in app.image_builtin_vars.values()}
        for widget in app._all_descendants(app.settings_page):
            if isinstance(widget, ttk.Combobox) and str(widget.cget('textvariable')) in retired:
                self.assertFalse(widget.winfo_ismapped())
        app._open_asset_gallery('rest')
        app.root.update()
        top = next(w for w in app.root.winfo_children() if isinstance(w, tk.Toplevel) and hasattr(w, '_gallery_photos'))
        self.assertTrue(top._seunga_positioned)
        self.assertGreater(len(top._gallery_photos), 0)
        self.assertLess(len(top._gallery_photos), len(app._catalog()))
        wheel_received = []
        app.root.bind_all('<MouseWheel>', lambda _event: wheel_received.append(True), add='+')
        button = next(widget for widget in app._all_descendants(top) if isinstance(widget, tk.Button) and str(widget.cget('image')))
        button.event_generate('<MouseWheel>', delta=-120)
        app.root.update()
        self.assertEqual(wheel_received, [])
        app.root.unbind_all('<MouseWheel>')
        thumbnail_buttons = [widget for widget in app._all_descendants(top) if isinstance(widget, tk.Button) and widget.master.winfo_manager() == 'grid']
        last_button = thumbnail_buttons[-1]
        self.assertGreater(int(last_button.cget('highlightthickness')), 0)
        top.focus_force()
        last_button.focus_set()
        app.root.update()
        canvas = next(widget for widget in app._all_descendants(top) if isinstance(widget, tk.Canvas))
        self.assertGreater(canvas.yview()[0], 0)
        self.assertTrue(str(last_button.cget('image')))
        # A delayed column reflow used to destroy the focused card and reset
        # yview to zero. Run the real resize debounce, including Tk 8.6/Noto.
        old_columns_row = int(last_button.master.grid_info()['row'])
        resize_width = 600 if top.winfo_width() > 700 else 900
        top.geometry(f'{resize_width}x600')
        app.root.update()
        resize_complete = tk.BooleanVar(master=top, value=False)
        top.after(90, lambda: resize_complete.set(True))
        top.wait_variable(resize_complete)
        self.assertTrue(last_button.winfo_exists())
        self.assertEqual(top.focus_get(), last_button)
        self.assertNotEqual(int(last_button.master.grid_info()['row']), old_columns_row)
        self.assertGreater(canvas.yview()[0], 0)
        self.assertTrue(str(last_button.cget('image')))
        before = app._image_action_state()
        last_button.event_generate('<Return>')
        app.root.update()
        self.assertEqual(len(top._comparison_photos), 2)
        self.assertEqual(app._image_action_state(), before)
        next(widget for widget in app._all_descendants(top) if isinstance(widget, tk.Button) and widget.cget('text') == '적용').invoke()
        self.assertNotEqual(app._image_action_state(), before)
        self.assertEqual(app.undo_image_action()['status'], 'undone')
        self.assertEqual(app._image_action_state(), before)
        top.destroy()

    def test_zip_preview_import_apply_and_restart_keep_profile_pack(self):
        app = self.app
        source = self.fixture('role.png', 'purple')
        archive = self.data / 'pack.zip'
        roles = [role for role, _caption in app.IMAGE_ROWS]
        with zipfile.ZipFile(archive, 'w') as zipped:
            for role in roles:
                zipped.write(source, f'pack/{role}_22.png')
        with patch('desktop_gallery.filedialog.askopenfilename', return_value=str(archive)):
            app._open_asset_pack_import()
        app.root.update()
        top = next(w for w in app.root.winfo_children() if isinstance(w, tk.Toplevel) and hasattr(w, '_import_previews'))
        self.assertTrue(top._seunga_positioned)
        self.assertEqual(len(top._import_previews), 10)
        self.assertFalse(list(app.IMPORTED_ASSET_DIR.rglob('*.png')))
        next(w for w in app._all_descendants(top) if isinstance(w, tk.Button) and w.cget('text') == '가져오기').invoke()
        self.assertEqual(len(list(app.IMPORTED_ASSET_DIR.rglob('*.png'))), 10)
        self.assertIn('pack:22', {item['id'] for item in app.image_action_catalog()['sets']})
        next(w for w in app._all_descendants(top) if isinstance(w, tk.Button) and w.cget('text') == '이 세트 적용').invoke()
        self.assertEqual(app._image_action_state()['__base_set__'], 'pack:22')
        self.assertTrue(app._resolve_builtin_asset('away').is_relative_to(app.IMPORTED_ASSET_DIR))
        self.close()
        self.app = FinalGalleryDesktopApp()
        for token in self.app.root.tk.call('after', 'info'):
            self.app.root.after_cancel(token)
        self.assertEqual(self.app._image_action_state()['__base_set__'], 'pack:22')
        self.assertEqual(self.app._resolve_builtin_asset('away').parent.parent, self.app.IMPORTED_ASSET_DIR)

    def test_before_after_proposal_previews_cover_follow_base_and_legacy_custom(self):
        app = self.app
        red = self.fixture('before.png', 'red')
        blue = self.fixture('after.png', 'blue')
        app._import_role_images('rest', [red])
        before = app._manual_override_path('rest')
        app._import_role_images('away', [blue])
        after_ref = app._manual_asset_overrides['away']
        proposal = app.propose_image_action({'kind': 'image', 'role': 'rest', 'ref': after_ref})
        self.assertEqual(app._decode_asset_ref(proposal['before_preview_ref']), before)
        self.assertEqual(app._decode_asset_ref(proposal['after_preview_ref']), app._decode_asset_ref(after_ref))
        self.assertEqual(app._manual_override_path('rest'), before)
        follow = app.propose_image_action({'kind': 'follow', 'role': 'rest'})
        self.assertEqual(app._decode_asset_ref(follow['before_preview_ref']), before)
        self.assertEqual(app._decode_asset_ref(follow['after_preview_ref']), app._resolve_builtin_asset('rest'))
        base = app.propose_image_action({'kind': 'base_set', 'set_id': '02'})
        self.assertIn('새 전체 세트', base['after_preview_label'])
        self.assertIn('수동 지정 유지', base['after_preview_label'])
        # External legacy references get opaque preview IDs; they cannot be
        # proposed as catalog selections by a model or written into a new role.
        app._manual_asset_overrides['rest'] = 'absolute:' + str(red)
        legacy = app.propose_image_action({'kind': 'follow', 'role': 'rest'})
        self.assertTrue(legacy['before_preview_ref'].startswith('preview:'))
        self.assertEqual(app._decode_asset_ref(legacy['before_preview_ref']), red)
        self.assertEqual(app.propose_image_action({'kind': 'image', 'role': 'rest', 'ref': legacy['before_preview_ref']})['status'], 'error')

    def _preview_pack_fixture(self, number):
        for index, (role, _caption) in enumerate(self.app.IMAGE_ROWS):
            path = self.app.IMPORTED_ASSET_DIR / role / f'{role}_{number:02d}.png'
            path.parent.mkdir(parents=True, exist_ok=True)
            Image.new('RGBA', (80, 120), (20 + index * 20, 40, number * 5, 255)).save(path)

    def test_imported_set_preview_navigation_browses_roles_without_applying(self):
        app = self.app
        builtin_before = app._image_action_state()
        app._select_settings_preview('rest')
        self.assertIn('rest_01.png', app.settings_preview_meta.cget('text'))
        app.settings_preview_next.invoke()
        self.assertIn('away_01.png', app.settings_preview_meta.cget('text'))
        self.assertEqual(app._image_action_state(), builtin_before)
        self._preview_pack_fixture(26)
        app._choose_base_set('가져온 세트 26')
        app._select_settings_preview('default')
        self.assertEqual(len(app._settings_preview_sources('default')[0]), 10)
        self.assertEqual(str(app.settings_preview_next.cget('state')), 'normal')
        self.assertIn('default_26.png', app.settings_preview_meta.cget('text'))
        state_before = app._image_action_state()
        preferences_before = asdict(app.preferences)
        file_before = app.MANUAL_OVERRIDE_FILE.read_bytes()
        settings_before = self.settings.read_bytes()
        history_before = list(app._image_actions.history)
        character_before = ImageTk.getimage(app.character_photo).tobytes()
        default_preview = ImageTk.getimage(app.settings_preview_image.image).tobytes()
        app.settings_preview_next.invoke()
        self.assertIn('cheer_26.png', app.settings_preview_meta.cget('text'))
        self.assertNotEqual(ImageTk.getimage(app.settings_preview_image.image).tobytes(), default_preview)
        self.assertIn(dict(app.IMAGE_ROWS)['cheer'], app.settings_preview_title.cget('text'))
        self.assertIn('설정 대상: ' + dict(app.IMAGE_ROWS)['default'], app.settings_preview_meta.cget('text'))
        self.assertIn('선택/저장 변경 없음', app.settings_preview_meta.cget('text'))
        self.assertEqual(app._settings_preview_role, 'default')
        app.settings_preview_prev.invoke()
        self.assertIn('default_26.png', app.settings_preview_meta.cget('text'))
        app.settings_preview_prev.invoke()
        self.assertIn('profile_26.png', app.settings_preview_meta.cget('text'))
        app.settings_preview_next.invoke()
        for _ in range(10):
            app.settings_preview_next.invoke()
        self.assertIn('default_26.png', app.settings_preview_meta.cget('text'))
        self.assertEqual(app._image_action_state(), state_before)
        self.assertEqual(asdict(app.preferences), preferences_before)
        self.assertEqual(app.MANUAL_OVERRIDE_FILE.read_bytes(), file_before)
        self.assertEqual(self.settings.read_bytes(), settings_before)
        self.assertEqual(app._image_actions.history, history_before)
        self.assertEqual(ImageTk.getimage(app.character_photo).tobytes(), character_before)
        app.settings_preview_next.invoke()
        app._select_settings_preview('rest')
        self.assertIn('rest_26.png', app.settings_preview_meta.cget('text'))
        app._select_settings_preview('default')
        self.assertIn('default_26.png', app.settings_preview_meta.cget('text'))
        app.settings_preview_next.invoke()
        self._preview_pack_fixture(27)
        app._choose_base_set('가져온 세트 27')
        self.assertIn('default_27.png', app.settings_preview_meta.cget('text'))

    def test_single_manual_preview_is_explicit_and_multi_image_navigation_is_read_only(self):
        app = self.app
        red = self.fixture('manual-red.png', 'red')
        blue = self.fixture('manual-blue.png', 'blue')
        app._import_role_images('default', [red])
        app._select_settings_preview('default')
        self.assertEqual(str(app.settings_preview_prev.cget('state')), 'disabled')
        self.assertEqual(str(app.settings_preview_next.cget('state')), 'disabled')
        self.assertIn('1장만', app.settings_preview_meta.cget('text'))
        app._import_role_images('default', [red, blue])
        before = app._image_action_state()
        file_before = app.MANUAL_OVERRIDE_FILE.read_bytes()
        first = ImageTk.getimage(app.settings_preview_image.image).tobytes()
        app.settings_preview_next.invoke()
        self.assertNotEqual(ImageTk.getimage(app.settings_preview_image.image).tobytes(), first)
        self.assertIn('2/2', app.settings_preview_meta.cget('text'))
        self.assertEqual(app._image_action_state(), before)
        self.assertEqual(app.MANUAL_OVERRIDE_FILE.read_bytes(), file_before)
        self._preview_pack_fixture(26)
        app._choose_base_set('가져온 세트 26')
        app._follow_selected_set('default')
        self.assertEqual(len(app._settings_preview_sources('default')[0]), 10)
        self.assertIn('default_26.png', app.settings_preview_meta.cget('text'))
        follow_before = app._image_action_state()
        app.settings_preview_next.invoke()
        self.assertIn('cheer_26.png', app.settings_preview_meta.cget('text'))
        self.assertEqual(app._image_action_state(), follow_before)
