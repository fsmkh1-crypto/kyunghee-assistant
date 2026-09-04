from pathlib import Path
p=Path('desktop_compact.py')
t=p.read_text(encoding='utf-8')
old='''        canvas.bind("<MouseWheel>", _settings_mousewheel)\n        content = tk.Frame(canvas, bg=core.PANEL)\n        window_id = canvas.create_window((0, 0), window=content, anchor="nw")\n        content.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))\n        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(window_id, width=e.width))\n\n        def _bind_settings_wheel(_event):\n            self.root.bind_all("<MouseWheel>", _settings_mousewheel)\n\n        def _unbind_settings_wheel(_event):\n            self.root.unbind_all("<MouseWheel>")\n\n        canvas.bind("<Enter>", _bind_settings_wheel)\n        canvas.bind("<Leave>", _unbind_settings_wheel)\n        content.bind("<Enter>", _bind_settings_wheel)\n        content.bind("<Leave>", _unbind_settings_wheel)\n'''
new='''        canvas.bind("<MouseWheel>", _settings_mousewheel)\n        self.root.bind_all("<MouseWheel>", _settings_mousewheel, add="+")\n        content = tk.Frame(canvas, bg=core.PANEL)\n        window_id = canvas.create_window((0, 0), window=content, anchor="nw")\n        content.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))\n        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(window_id, width=e.width))\n'''
if t.count(old)!=1: raise SystemExit(f'expected one old wheel block, found {t.count(old)}')
t=t.replace(old,new,1)
p.write_text(t,encoding='utf-8')
