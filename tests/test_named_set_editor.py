"""Offline real-Tk creation, review and re-selection of loose image sets."""
from pathlib import Path
from io import BytesIO
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import patch

from PIL import Image

from named_set_editor import NamedSetEditor, suggest_role_assignments
from image_actions import BASE
from tests import test_random_gallery as gallery_fixture


class FilenameSuggestionTests(unittest.TestCase):
    def test_only_unique_explicit_role_names_are_suggested(self):
        roles = dict(gallery_fixture.GalleryDesktopApp.IMAGE_ROWS)
        paths = [Path(value) for value in (
            'default.png', 'rest_03.jpg', 'profile_kyunghee.webp',
            'holiday_01.png', 'warning_00.png', 'away_123.png',
            'cheer_02.png', 'other/cheer_01.png', 'settings.png', 'other/settings.jpg',
        )]
        self.assertEqual(suggest_role_assignments(paths, roles), {
            'default': paths[0], 'rest': paths[1], 'profile': paths[2],
        })


class NamedSetEditorTkTests(unittest.TestCase):
    # Reuse the isolated final-entry fixture, without inheriting its test cases.
    setUp = gallery_fixture.RandomGalleryTkTests.setUp
    close = gallery_fixture.RandomGalleryTkTests.close
    fixture = gallery_fixture.RandomGalleryTkTests.fixture
    _show_image_settings = gallery_fixture.RandomGalleryTkTests._show_image_settings
    _visible_hit = gallery_fixture.RandomGalleryTkTests._visible_hit
    _click_hit = gallery_fixture.RandomGalleryTkTests._click_hit

    @classmethod
    def setUpClass(cls):
        gallery_fixture.RandomGalleryTkTests.setUpClass()

    def editor(self, paths=None, *, via_button=False):
        paths = paths or [self.fixture('portrait.png', 'purple')]
        with patch('desktop_gallery.filedialog.askopenfilenames', return_value=tuple(map(str, paths))):
            if via_button:
                self._show_image_settings()
                button = next(widget for widget in self.app._all_descendants(self.app.settings_page)
                              if isinstance(widget, tk.Button) and widget.cget('text') == '낱장으로 새 전체 세트')
                self._click_hit(button)
                editor = next(widget for widget in self.app.root.winfo_children() if isinstance(widget, NamedSetEditor))
            else:
                editor = self.app._open_named_set_editor()
        self.assertIsInstance(editor, NamedSetEditor)
        self.app.root.update()
        return editor

    def assign_all(self, editor, name='내 세트 01 · 주말'):
        editor.name.set(name)
        for index, variable in enumerate(editor.assignments.values()):
            variable.set(editor._value_for(editor.sources[index % len(editor.sources)]))

    def test_complete_review_save_apply_reselect_and_restart_preserve_manual_images(self):
        app = self.app
        old = self.fixture('manual.png', 'green')
        app._import_role_images('rest', [old])
        manual = app._custom_image('rest')[0]
        paths = [self.fixture(f'portrait_{index}.png', (index * 20, 30, 100)) for index in range(10)]
        originals = {path: path.read_bytes() for path in paths}
        before = app._image_action_state()
        app._show_page('settings')
        editor = self.editor(paths, via_button=True)
        self.assertTrue(all(not value.get() for value in editor.assignments.values()))
        editor.name.set('내 세트 01 · 주말')
        for index, role in enumerate(editor.assignments):
            if index == 9:
                break
            editor.assignments[role].set(editor._value_for(paths[index]))
        self.assertEqual(editor.review_button.cget('state'), 'disabled')
        self.assertEqual(editor.save_button.cget('state'), 'disabled')
        self.assertIn('9/10', editor.progress.get())
        editor.assignments[role].set(editor._value_for(paths[9]))
        editor.review_button.invoke()
        self.assertIsNotNone(editor.plan)
        self.assertIn('내 세트 01 · 주말', editor.status.get())
        self.assertFalse(app._named_image_sets.sets_dir.exists())
        editor.save_button.invoke()
        saved = editor.saved_set
        self.assertIsNotNone(saved)
        self.assertEqual(app._image_action_state(), before)
        self.assertEqual({path: path.read_bytes() for path in paths}, originals)
        for index, role in enumerate(editor.assignments):
            self.assertEqual(saved.images[role].read_bytes(), originals[paths[index]])
        label = app._named_set_label(saved.name)
        self.assertEqual(app._builtin_base_value(label), saved.id)
        choices = next(widget for widget in app._all_descendants(app.settings_page)
                       if isinstance(widget, ttk.Combobox)
                       and str(widget.cget('textvariable')) == str(app.builtin_image_set_var))
        self.assertIn(label, choices.cget('values'))
        editor.apply_button.invoke()
        self.assertEqual(app._image_action_state()[BASE], saved.id)
        self.assertEqual(app._custom_image('rest')[0], manual)
        self.assertEqual(app._resolve_builtin_asset('worry'), saved.images['warning'])
        self.assertEqual(app._resolve_builtin_asset('master_face'), saved.images['profile'])
        app._set_character('default')
        self.assertIn(saved.name, app.active_image_origin())
        with patch.object(app._named_image_sets, 'get', wraps=app._named_image_sets.get) as get:
            preview, title = app._base_set_preview_sources()
            self.assertEqual(get.call_count, 1)
        self.assertEqual(preview, [saved.images[key] for key, _ in app.IMAGE_ROWS])
        self.assertIn(saved.name, title)
        with patch.object(app._named_image_sets, 'get', wraps=app._named_image_sets.get) as get:
            role_preview, _ = app._role_base_preview_sources('profile')
            self.assertEqual(get.call_count, 1)
        self.assertEqual(role_preview[0], saved.images['profile'])
        self.assertEqual(app._preview_role_for_path(role_preview[0]), dict(app.IMAGE_ROWS)['profile'])
        catalog = app.image_action_catalog()
        self.assertEqual(len([item for item in catalog['images'] if item.get('set_id') == saved.id]), 10)
        editor.destroy()
        self.assertEqual(app._choose_base_set('기본 모델')['status'], 'applied')
        self.assertEqual(app._choose_base_set(label)['status'], 'applied')
        self.close()
        self.app = gallery_fixture.FinalGalleryDesktopApp()
        for token in self.app.root.tk.call('after', 'info'):
            self.app.root.after_cancel(token)
        self.app.root.update()
        self.assertEqual(self.app._image_action_state()[BASE], saved.id)
        self.assertEqual(self.app.builtin_image_set_var.get(), label)
        self.assertEqual(self.app._resolve_builtin_asset('default'), saved.images['default'])
        self.assertEqual(self.app._custom_image('rest')[0], manual)

    def test_cancel_invalid_input_and_settings_toggle_preserve_draft_and_selection(self):
        before = self.app._image_action_state()
        children = self.app.root.winfo_children()
        with patch('desktop_gallery.filedialog.askopenfilenames', return_value=()):
            self.assertIsNone(self.app._open_named_set_editor())
        self.assertEqual(children, self.app.root.winfo_children())
        with patch('desktop_gallery.filedialog.askopenfilenames', return_value=(str(self.data / 'missing.png'),)), \
                patch('desktop_gallery.messagebox.showerror') as error:
            self.assertIsNone(self.app._open_named_set_editor())
            error.assert_called_once()
        self.assertEqual(children, self.app.root.winfo_children())
        editor = self.editor()
        self.assign_all(editor)
        draft = {key: value.get() for key, value in editor.assignments.items()}
        self.app._show_page('settings')
        self.app._show_page('timer')
        self.app.root.update()
        self.assertTrue(editor.winfo_viewable())
        self.assertEqual({key: value.get() for key, value in editor.assignments.items()}, draft)
        editor.cancel_button.invoke()
        self.assertFalse(self.app._named_image_sets.sets_dir.exists())
        self.assertEqual(self.app._image_action_state(), before)

    def test_collision_preview_and_source_change_require_review_without_overwrite(self):
        source = self.fixture('default_01.png', 'red')
        existing = self.app._named_image_sets.create('같은 이름', {key: source for key, _ in self.app.IMAGE_ROWS})
        existing_bytes = {path: path.read_bytes() for path in existing.images.values()}
        editor = self.editor([source])
        self.assign_all(editor, '같은 이름')
        editor.review_button.invoke()
        self.assertEqual(editor.plan.name, '같은 이름 (2)')
        self.assertIn('같은 이름 (2)', editor.status.get())
        Image.new('RGBA', (80, 120), 'blue').save(source)
        editor.save_button.invoke()
        self.assertIsNone(editor.saved_set)
        self.assertIsNone(editor.plan)
        self.assertEqual(len(self.app._named_image_sets.list_sets()), 1)
        self.assertEqual({path: path.read_bytes() for path in existing.images.values()}, existing_bytes)
        editor.review_button.invoke()
        self.assertEqual(editor._photos['default']._PhotoImage__photo.get(38, 44), (0, 0, 255))
        editor.save_button.invoke()
        self.assertEqual(editor.saved_set.name, '같은 이름 (2)')
        self.assertNotEqual(editor.saved_set.id, existing.id)
        self.assertEqual({path: path.read_bytes() for path in existing.images.values()}, existing_bytes)

    def test_edits_invalidate_review_and_duplicate_basenames_remain_distinct(self):
        source = self.fixture('image.png', 'red')
        other = self.data / 'other' / 'image.png'
        other.parent.mkdir()
        Image.new('RGB', (20, 20), 'blue').save(other)
        editor = self.editor([source, other])
        self.assertEqual(len(editor._file_values), 2)
        self.assertNotEqual(editor._value_for(source), editor._value_for(other))
        self.assign_all(editor)
        editor.review_button.invoke()
        self.assertIsNotNone(editor.plan)
        editor.name.set('바꾼 이름')
        self.assertIsNone(editor.plan)
        self.assertEqual(editor.save_button.cget('state'), 'disabled')
        editor.review_button.invoke()
        editor.assignments['default'].set(editor._value_for(other))
        self.assertIsNone(editor.plan)
        self.assertEqual(editor.save_button.cget('state'), 'disabled')
        editor.review_button.invoke()
        extra = self.fixture('rest.png', 'pink')
        draft = {key: value.get() for key, value in editor.assignments.items()}
        with patch('named_set_editor.filedialog.askopenfilenames', return_value=(str(extra),)):
            editor.add_button.invoke()
        self.assertEqual({key: value.get() for key, value in editor.assignments.items()}, draft)
        self.assertIsNone(editor.plan)

    def test_source_growing_after_validation_is_read_with_a_bound_then_rejected(self):
        editor = self.editor()
        self.assign_all(editor)
        assigned = {role: editor.sources[0] for role in editor.assignments}
        plan = editor.store.preview(editor.name.get(), assigned)
        reads = []
        class GrowingSource(BytesIO):
            def read(self, size=-1):
                reads.append(size)
                return super().read(size)
        # The real backend validated a small image. A concurrent replacement
        # must not cause an unbounded second read while rendering that plan.
        with patch.object(editor.store, 'preview', return_value=plan), \
                patch('named_set_editor.MAX_IMAGE_BYTES', 1024), \
                patch.object(Path, 'open', return_value=GrowingSource(b'x' * 4096)):
            editor.review_button.invoke()
        self.assertEqual(reads, [1025])
        self.assertIsNone(editor.plan)
        self.assertIsNone(editor.saved_set)
        self.assertEqual(editor.save_button.cget('state'), 'disabled')
        self.assertFalse(editor.store.sets_dir.exists())

    def test_write_refresh_and_apply_errors_never_repeat_committed_save(self):
        editor = self.editor()
        self.assign_all(editor)
        editor.review_button.invoke()
        before = self.app._image_action_state()
        draft = {key: value.get() for key, value in editor.assignments.items()}
        with patch.object(editor.store, 'save', side_effect=OSError('disk full')):
            editor.save_button.invoke()
        self.assertIsNone(editor.saved_set)
        self.assertEqual({key: value.get() for key, value in editor.assignments.items()}, draft)
        self.assertEqual(self.app._image_action_state(), before)
        editor.review_button.invoke()
        editor.on_saved = lambda _: (_ for _ in ()).throw(RuntimeError('refresh failed'))
        editor.save_button.invoke()
        self.assertIsNotNone(editor.saved_set)
        self.assertIn('저장됐지만', editor.status.get())
        editor.save()
        self.assertEqual(len(editor.store.list_sets()), 1)
        editor.on_apply = lambda _: {'status': 'error', 'summary': 'apply failed'}
        editor.apply_button.invoke()
        self.assertEqual(self.app._image_action_state(), before)
        self.assertEqual(len(editor.store.list_sets()), 1)
        self.assertIn('적용하지 못했어요', editor.status.get())


if __name__ == '__main__':
    unittest.main()
