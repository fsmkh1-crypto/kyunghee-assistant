"""Model Win32 client/outer sizing even on Linux's undecorated Xvfb display."""
import re
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from assistant_ai.ui_helpers import position_window


class _WindowModel:
    def __init__(self, width=900, height=900, *, frame=(16, 39)):
        self.width, self.height = width, height
        self.x, self.y = 100, 100
        self.frame = frame
        self.minimum = (560, 540)
        self._preferred_size = width, height

    def winfo_exists(self): return True
    def update_idletasks(self): pass
    def winfo_width(self): return self.width
    def winfo_height(self): return self.height
    def winfo_x(self): return self.x
    def winfo_y(self): return self.y
    def winfo_rootx(self): return self.x + self.frame[0] // 2
    def winfo_rooty(self): return self.y + self.frame[1] - self.frame[0] // 2
    def winfo_id(self): return 10
    def winfo_viewable(self): return True
    def deiconify(self): pass
    def transient(self, _parent): pass
    def attributes(self, *_args): return False

    def minsize(self, *values):
        if values:
            self.minimum = values
        return self.minimum

    def geometry(self, value):
        match = re.fullmatch(r"(\d+)x(\d+)(?:([+-]\d+)([+-]\d+))?", value)
        if match is None:
            raise AssertionError(value)
        self.width = max(int(match[1]), self.minimum[0])
        self.height = max(int(match[2]), self.minimum[1])
        if match[3] is not None:
            self.x, self.y = int(match[3]), int(match[4])


class WindowsPositionWindowTests(unittest.TestCase):
    def install_native_model(self, window, *, frame_after_move=None):
        def window_rect(_hwnd, pointer):
            rect = pointer._obj
            rect.left, rect.top = window.x, window.y
            rect.right = window.x + window.width + window.frame[0]
            rect.bottom = window.y + window.height + window.frame[1]
            return True

        def client_rect(_hwnd, pointer):
            rect = pointer._obj
            rect.left, rect.top = 0, 0
            rect.right, rect.bottom = window.width, window.height
            return True

        def move(_hwnd, _after, x, y, cx, cy, flags):
            window.x, window.y = x, y
            # Model the original bug: native dimensions include the frame.
            if not flags & 0x0001:
                window.width = cx - window.frame[0]
                window.height = cy - window.frame[1]
            if frame_after_move is not None:
                window.frame = frame_after_move
            return True

        native = SimpleNamespace(GetAncestor=Mock(return_value=11),
                                 GetWindowRect=Mock(side_effect=window_rect),
                                 GetClientRect=Mock(side_effect=client_rect),
                                 SetWindowPos=Mock(side_effect=move))
        self.enterContext(patch("assistant_ai.ui_helpers.os.name", "nt"))
        self.enterContext(patch("assistant_ai.ui_helpers.ctypes.WinDLL", return_value=native, create=True))
        return native

    def assert_outer_fits(self, window, area):
        self.assertGreaterEqual(window.x, area[0] + 12)
        self.assertGreaterEqual(window.y, area[1] + 12)
        self.assertLessEqual(window.x + window.width + window.frame[0], area[2] - 12)
        self.assertLessEqual(window.y + window.height + window.frame[1], area[3] - 12)

    def test_initial_client_width_remains_900_and_decorated_height_fits(self):
        window, parent = _WindowModel(), _WindowModel(320, 480)
        native = self.install_native_model(window)
        area = (0, 0, 1366, 768)
        result = position_window(window, parent, lambda *_: area)
        self.assertEqual(window.width, 900)
        self.assertEqual(window.height, 705)
        self.assertEqual(result[2:], (900, 705))
        self.assert_outer_fits(window, area)
        for call in native.SetWindowPos.call_args_list:
            self.assertEqual(call.args[4:6], (0, 0))
            self.assertTrue(call.args[6] & 0x0001)  # SWP_NOSIZE

    def test_user_client_size_survives_repeated_windows_positioning(self):
        window, parent = _WindowModel(780, 720), _WindowModel(320, 480)
        self.install_native_model(window)
        area = (0, 0, 1920, 1080)
        positions = []
        for _ in range(5):
            positions.append(position_window(window, parent, lambda *_: area))
            self.assertEqual((window.width, window.height), (780, 720))
            self.assert_outer_fits(window, area)
        self.assertEqual(positions, [positions[0]] * 5)

    def test_frame_is_included_when_fitting_small_and_negative_monitors(self):
        for area, expected in (((0, 0, 640, 480), (600, 417)),
                               ((-1280, -720, 0, 0), (1240, 657))):
            with self.subTest(area=area):
                window, parent = _WindowModel(1600, 1000), _WindowModel(320, 480)
                self.install_native_model(window)
                position_window(window, parent, lambda *_: area)
                self.assertEqual((window.width, window.height), expected)
                self.assert_outer_fits(window, area)
                if area[0] < 0:
                    self.assertLess(window.x, 0)
                    self.assertLess(window.y, 0)

    def test_dpi_frame_change_after_move_gets_one_bounded_correction(self):
        window, parent = _WindowModel(), _WindowModel(320, 480)
        native = self.install_native_model(window, frame_after_move=(32, 78))
        area = (-1366, 0, 0, 768)
        result = position_window(window, parent, lambda *_: area)
        self.assertEqual(result[2:], (900, 666))
        self.assertEqual(native.SetWindowPos.call_count, 2)
        self.assert_outer_fits(window, area)


if __name__ == "__main__":
    unittest.main()
