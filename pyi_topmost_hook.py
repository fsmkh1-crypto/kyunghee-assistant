import tkinter as tk

_original_tk_init = tk.Tk.__init__


def _topmost_tk_init(self, *args, **kwargs):
    _original_tk_init(self, *args, **kwargs)
    try:
        self.attributes("-topmost", True)
    except Exception:
        pass


tk.Tk.__init__ = _topmost_tk_init
