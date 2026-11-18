"""No Tk display needed: test final client-area fitting and placement."""
import os
os.environ.setdefault("PYSTRAY_BACKEND", "dummy")
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from PIL import Image
from desktop_compact import CompactDesktopApp


class _Photo:
    def __init__(self, image): self.size = image.size
    def width(self): return self.size[0]
    def height(self): return self.size[1]


class TimerViewportFitTests(unittest.TestCase):
    def make_app(self, source=(1000, 1500)):
        app = object.__new__(CompactDesktopApp)
        app._character_fit_image = Image.new('RGBA', source, (200, 100, 50, 255))
        app.character_photo = _Photo(app._character_fit_image)
        app.character = Mock()
        app._clock_layout_width = lambda: 150
        app._message_bottom_gap = lambda: 10
        app._message_render_height = lambda: 36
        app._scale = lambda value: value
        return app

    def test_image_fits_actual_client_not_unclamped_requested_window(self):
        app = self.make_app()
        with patch('desktop_compact.ImageTk.PhotoImage', _Photo):
            app._fit_character_to_viewport(320, 300)
        self.assertLessEqual(app.character_photo.width(), 320 - 32 - 150 - 6)
        self.assertLessEqual(app.character_photo.height(), 300 - 72 - 42)
        self.assertAlmostEqual(app.character_photo.width() / app.character_photo.height(), 2/3, delta=.01)
        self.assertEqual(app._character_alpha_bbox, (0, 0, *app.character_photo.size))

    def test_larger_viewport_restores_from_retained_source_not_shrunken_thumbnail(self):
        app = self.make_app()
        with patch('desktop_compact.ImageTk.PhotoImage', _Photo):
            app._fit_character_to_viewport(320, 300)
            small = app.character_photo.size
            app._fit_character_to_viewport(900, 900)
        self.assertGreater(app.character_photo.height(), small[1])
        self.assertEqual(app._character_fit_image.size, (1000, 1500))

    def test_position_uses_final_viewport_and_keeps_art_inside_with_wide_speech(self):
        app = self.make_app((100, 180))
        app._timer_viewport = (320, 300)
        app._character_alpha_bbox = (0, 0, 100, 180)
        app._horizontal_union_bounds = lambda: (-200, 600, 150, 6)
        app._timer_size = lambda: (900, 1000)
        _, offset = app._cluster_horizontal_layout()
        left = 320 / 2 + offset - 100 / 2
        self.assertGreaterEqual(left, 0)
        self.assertLessEqual(left + 100, 320)
        self.assertEqual(app._timer_layout_size(), (320, 300))

    def test_resize_reads_committed_hero_size_and_guards_configure_recursion(self):
        app = self.make_app()
        app._timer_size = lambda: (1000, 1000)
        app._clamp_rect = lambda *_args: (0, 0, 640, 480)
        app.root = SimpleNamespace(winfo_x=lambda: 0, winfo_y=lambda: 0,
                                   minsize=Mock(), update_idletasks=Mock())
        app.hero = SimpleNamespace(winfo_width=lambda: 620, winfo_height=lambda: 440)
        app._set_window_rect = lambda *_args: app._resize_for_page('timer')
        app._fit_character_to_viewport = Mock()
        app._apply_widget_appearance = Mock()
        app._resize_for_page('timer')
        self.assertEqual(app._timer_viewport, (620, 440))
        app._fit_character_to_viewport.assert_called_once_with(620, 440)
        app._apply_widget_appearance.assert_called_once_with()
        self.assertFalse(app._fitting_timer_viewport)

    def test_no_source_during_initial_build_is_safe(self):
        app = self.make_app()
        app._character_fit_image = None
        app._fit_character_to_viewport(320, 300)
        app.character.configure.assert_not_called()

    def test_settings_resize_does_not_replace_timer_viewport(self):
        app = self.make_app()
        app._timer_viewport = (320, 300)
        app.root = SimpleNamespace(winfo_x=lambda: 0, winfo_y=lambda: 0, minsize=Mock())
        app._clamp_rect = lambda x, y, w, h: (x, y, w, h)
        app._set_window_rect = Mock()
        app._resize_for_page('settings')
        self.assertEqual(app._timer_viewport, (320, 300))


if __name__ == '__main__':
    unittest.main()
