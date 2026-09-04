from pathlib import Path

path = Path('desktop_compact.py')
text = path.read_text(encoding='utf-8')

old = '''        canvas.configure(yscrollcommand=scroll.set)\n        scroll.pack(side="right", fill="y")\n        canvas.pack(side="left", fill="both", expand=True)\n        content = tk.Frame(canvas, bg=core.PANEL)\n'''
new = '''        canvas.configure(yscrollcommand=scroll.set)\n        scroll.pack(side="right", fill="y")\n        canvas.pack(side="left", fill="both", expand=True)\n\n        def _settings_mousewheel(event):\n            if self.current_page != "settings":\n                return\n            delta = int(getattr(event, "delta", 0))\n            if not delta:\n                return\n            units = -1 if delta > 0 else 1\n            canvas.yview_scroll(units * 3, "units")\n            return "break"\n\n        canvas.bind("<MouseWheel>", _settings_mousewheel)\n        content = tk.Frame(canvas, bg=core.PANEL)\n'''
if text.count(old) != 1:
    raise SystemExit(f'expected one settings canvas block, found {text.count(old)}')
text = text.replace(old, new, 1)

old2 = '''        content.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))\n        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(window_id, width=e.width))\n'''
new2 = '''        content.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))\n        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(window_id, width=e.width))\n\n        def _bind_settings_wheel(_event):\n            self.root.bind_all("<MouseWheel>", _settings_mousewheel)\n\n        def _unbind_settings_wheel(_event):\n            self.root.unbind_all("<MouseWheel>")\n\n        canvas.bind("<Enter>", _bind_settings_wheel)\n        canvas.bind("<Leave>", _unbind_settings_wheel)\n        content.bind("<Enter>", _bind_settings_wheel)\n        content.bind("<Leave>", _unbind_settings_wheel)\n'''
if text.count(old2) != 1:
    raise SystemExit(f'expected one settings configure block, found {text.count(old2)}')
text = text.replace(old2, new2, 1)

path.write_text(text, encoding='utf-8')
