"""Explicit role assignment and review for a new, immutable whole image set."""
from __future__ import annotations

from collections import defaultdict
import hashlib
from io import BytesIO
from pathlib import Path
import re
import tkinter as tk
from tkinter import filedialog, ttk

from PIL import Image, ImageTk

import app as core
from asset_pack_import import CANONICAL_ALIASES
from assistant_ai.ui_helpers import position_window
from image_catalog import MAX_IMAGE_BYTES, require_image


IMAGE_FILETYPES = [("이미지", "*.png *.jpg *.jpeg *.webp"), ("모든 파일", "*.*")]
MAX_SOURCE_FILES = 100


def suggest_role_assignments(paths, roles):
    """Only one unambiguous, recognized filename may suggest a role."""
    roles = set(roles)
    aliases = {Path(name).stem.casefold(): role for name, role in CANONICAL_ALIASES.items()}
    candidates = defaultdict(list)
    for path in paths:
        path = Path(path)
        stem = path.stem.casefold()
        numbered = re.fullmatch(r"([a-z]+)_[0-9]{2}", stem)
        role = stem if stem in roles else aliases.get(stem)
        if role is None and numbered and numbered[1] in roles and not stem.endswith("_00"):
            role = numbered[1]
        if role in roles:
            candidates[role].append(path)
    return {role: matches[0] for role, matches in candidates.items() if len(matches) == 1}


class NamedSetEditor(tk.Toplevel):
    def __init__(self, app, store, paths, *, on_saved, on_apply):
        # Validate before creating a window; failure does not leave an empty editor.
        sources = self._validated_paths(paths)
        super().__init__(app.root, bg=core.PANEL)
        self.withdraw()
        self.app, self.store = app, store
        self.on_saved, self.on_apply = on_saved, on_apply
        self.sources = sources
        self.plan = None
        self.saved_set = None
        self._photos = {}
        self._invalid_roles = set()
        self._loading = True
        self._width = None
        self._region = None
        self._file_values = {}
        self._action_layout = None
        self._preferred_size = (760, 760)
        self.title("낱장으로 새 전체 세트 | 승아 타이머")
        self.geometry("760x760")
        self.minsize(340, 300)
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Escape>", lambda _event: self.destroy())

        # Reserve the footer before packing any content so short/high-DPI
        # work areas always retain the explicit save and close controls.
        footer = tk.Frame(self, bg=core.PANEL)
        footer.pack(side="bottom", fill="x", padx=12, pady=(4, 10))
        self.status = tk.StringVar(master=self, value="파일명 제안을 확인하고 10개 상황을 모두 배정해 주세요.")
        status_frame = tk.Frame(footer, bg=core.PANEL)
        status_frame.pack(fill="x", pady=(0, 5))
        self.status_text = tk.Text(status_frame, height=3, width=1, wrap="word", relief="flat",
                                   font=(app.FONT_FAMILY, 9), bg=core.PANEL, fg=core.TEXT,
                                   highlightthickness=0, padx=4, pady=2)
        status_scroll = tk.Scrollbar(status_frame, command=self.status_text.yview)
        status_scroll.pack(side="right", fill="y")
        self.status_text.pack(side="left", fill="x", expand=True)
        self.status_text.configure(yscrollcommand=status_scroll.set)
        self.status.trace_add("write", self._show_status)
        self._show_status()
        self.status_text.bind("<Tab>", self._move_status_focus)
        self.status_text.bind("<Shift-Tab>", lambda event: self._move_status_focus(event, previous=True))
        self.status_text.bind("<ISO_Left_Tab>", lambda event: self._move_status_focus(event, previous=True))
        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.status_text.bind(sequence, self._scroll_status)
        self.actions = tk.Frame(footer, bg=core.PANEL)
        self.actions.pack(fill="x")
        self.review_button = app._button(self.actions, "미리보기 확인", self.review)
        self.save_button = app._button(self.actions, "새 세트 저장", self.save, primary=True)
        self.apply_button = app._button(self.actions, "이 세트 적용", self.apply, primary=True)
        self.cancel_button = app._button(self.actions, "취소", self.destroy)
        self.actions.bind("<Configure>", self._layout_actions)
        self._layout_actions()

        viewport = tk.Frame(self, bg=core.PANEL)
        viewport.pack(fill="both", expand=True, padx=12, pady=4)
        self.canvas = tk.Canvas(viewport, bg=core.PANEL, highlightthickness=0, width=1, height=1)
        scrollbar = tk.Scrollbar(viewport, command=self.canvas.yview)
        scrollbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.content = tk.Frame(self.canvas, bg=core.PANEL)
        self._content_id = self.canvas.create_window(0, 0, window=self.content, anchor="nw")
        self.canvas.bind("<Configure>", self._fit_content)
        self.content.bind("<Configure>", self._update_region)
        # Name and file controls scroll with the assignments. Keeping this
        # header fixed as well as the footer leaves less than one selector's
        # height on small Windows work areas at 200% display scaling.
        header = tk.Frame(self.content, bg=core.PANEL)
        header.pack(fill="x", pady=(6, 8))
        self.name = tk.StringVar(master=self)
        app._label(header, "세트 이름", size=10, bg=core.PANEL).grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.name_entry = tk.Entry(header, textvariable=self.name, font=(app.FONT_FAMILY, 10),
                                   bg=core.PANEL_2, fg=core.TEXT, insertbackground=core.TEXT)
        self.name_entry.grid(row=0, column=1, sticky="ew")
        header.columnconfigure(1, weight=1)
        self.add_button = app._button(header, "이미지 추가", self.add_images)
        self.add_button.grid(row=1, column=0, sticky="w", pady=(5, 0))
        self.progress = tk.StringVar(master=self)
        self.progress_label = app._label(header, textvariable=self.progress, size=9,
                                         bg=core.PANEL, justify="left")
        self.progress_label.grid(row=1, column=1, sticky="ew", padx=8, pady=(5, 0))
        for widget in (self.name_entry, self.add_button):
            widget.bind("<FocusIn>", lambda _event, target=widget: self.after_idle(self._ensure_visible, target))
        self.rows, self.assignments, self.selectors = {}, {}, {}
        for role, caption in app.IMAGE_ROWS:
            row = tk.Frame(self.content, bg=core.PANEL_2)
            row.pack(fill="x", pady=(0, 8))
            row.columnconfigure(1, weight=1)
            thumbnail = tk.Label(row, bg=core.PANEL_2, fg=core.MUTED, text="미배정", width=10, height=4)
            thumbnail.grid(row=0, column=0, rowspan=3, padx=8, pady=8)
            app._label(row, caption, size=10, bg=core.PANEL_2).grid(row=0, column=1, sticky="w", padx=(0, 8), pady=(6, 2))
            variable = self.assignments[role] = tk.StringVar(master=self)
            selector = self.selectors[role] = ttk.Combobox(row, textvariable=variable, state="readonly", width=1)
            selector.grid(row=1, column=1, sticky="ew", padx=(0, 8))
            path_label = app._label(row, "파일을 선택해 주세요", size=8, bg=core.PANEL_2,
                                    fg=core.MUTED, wraplength=500, justify="left")
            path_label.grid(row=2, column=1, sticky="ew", padx=(0, 8), pady=(3, 6))
            selector.bind("<FocusIn>", lambda _event, widget=selector: self.after_idle(self._ensure_visible, widget))
            # Tk's closed Combobox class binding changes its selected value
            # on wheel events. Scrolling the role list must preserve choices.
            for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                selector.bind(sequence, self._scroll)
            variable.trace_add("write", lambda *_args, key=role: self._assignment_changed(key))
            self.rows[role] = (row, thumbnail, path_label)
        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.bind(sequence, self._scroll, add="+")
        self.name.trace_add("write", self._draft_changed)
        self._populate_choices()
        suggestions = suggest_role_assignments(self.sources, self.assignments)
        for role, source in suggestions.items():
            self.assignments[role].set(self._value_for(source))
        self._loading = False
        for role in self.assignments:
            self._assignment_changed(role)
        position_window(self, app.root, work_area=app._best_work_area)
        self.deiconify()
        self.name_entry.focus_set()

    @staticmethod
    def _validated_paths(paths):
        values = list(dict.fromkeys(Path(path).expanduser().absolute() for path in paths))
        if not values:
            raise ValueError("새 세트에 사용할 이미지를 선택해 주세요.")
        if len(values) > MAX_SOURCE_FILES:
            raise ValueError(f"한 번에 {MAX_SOURCE_FILES}장까지 선택할 수 있어요.")
        for path in values:
            require_image(path)
        return values

    def _populate_choices(self):
        self._file_values = {f"{index:02d} · {path.name}": path for index, path in enumerate(self.sources, 1)}
        for selector in self.selectors.values():
            selector.configure(values=("", *self._file_values))

    def _value_for(self, path):
        return next(value for value, candidate in self._file_values.items() if candidate == path)

    def _assignment_changed(self, role):
        if self._loading:
            return
        _row, thumbnail, path_label = self.rows[role]
        path = self._file_values.get(self.assignments[role].get())
        self._invalid_roles.discard(role)
        if path is None:
            thumbnail.configure(image="", text="미배정", width=10, height=4)
            path_label.configure(text="파일을 선택해 주세요")
            self._photos.pop(role, None)
        else:
            path_label.configure(text=str(path))
            try:
                require_image(path)
                photo = ImageTk.PhotoImage(self.app._thumbnail_image(path, (76, 88)), master=self)
                self._photos[role] = photo
                thumbnail.configure(image=photo, text="", width=76, height=88)
            except (OSError, ValueError):
                self._invalid_roles.add(role)
                self._photos.pop(role, None)
                thumbnail.configure(image="", text="읽기 오류", width=10, height=4)
        self._draft_changed()

    def _draft_changed(self, *_args):
        if self._loading or self.saved_set is not None:
            return
        self.plan = None
        assigned = sum(variable.get() in self._file_values and role not in self._invalid_roles
                       for role, variable in self.assignments.items())
        self.progress.set(f"상황 {assigned}/10 배정 · 선택 이미지 {len(self.sources)}장")
        ready = assigned == len(self.assignments) and bool(self.name.get().strip())
        self.review_button.configure(state="normal" if ready else "disabled")
        self.save_button.configure(state="disabled")
        self.status.set("같은 이미지도 여러 상황에 직접 배정할 수 있어요. 저장 후 적용은 따로 선택합니다.")

    def add_images(self):
        selected = filedialog.askopenfilenames(parent=self, title="새 세트에 사용할 이미지 추가", filetypes=IMAGE_FILETYPES)
        if not selected:
            return
        try:
            sources = self._validated_paths([*self.sources, *selected])
        except (OSError, ValueError) as error:
            self.status.set(str(error))
            return
        self.sources = sources
        self._populate_choices()
        # Keep existing assignments. New files stay available for explicit
        # selection; adding a candidate must never replace a user's decision.
        self._draft_changed()

    def review(self):
        if self.saved_set is not None:
            return
        try:
            assigned = {role: self._file_values[variable.get()] for role, variable in self.assignments.items()}
            plan = self.store.preview(self.name.get(), assigned)
            # A source can have changed while the editor was open. Render the
            # bytes that were just approved by preview, without the gallery's
            # path/mtime thumbnail cache. Save rechecks the same hashes.
            for image in plan.images:
                with image.source.open("rb") as source_file:
                    content = source_file.read(MAX_IMAGE_BYTES + 1)
                if len(content) > MAX_IMAGE_BYTES or hashlib.sha256(content).hexdigest() != image.sha256:
                    raise ValueError("미리보기 중 원본이 바뀌었어요. 다시 확인해 주세요.")
                with Image.open(BytesIO(content)) as source:
                    rgba = source.convert("RGBA")
                    rgba.thumbnail((76, 88), Image.Resampling.LANCZOS)
                canvas = Image.new("RGBA", (76, 88), core.PANEL_2)
                canvas.alpha_composite(rgba, ((76 - rgba.width) // 2, (88 - rgba.height) // 2))
                photo = ImageTk.PhotoImage(canvas.convert("RGB"), master=self)
                self._photos[image.role] = photo
                self.rows[image.role][1].configure(image=photo, text="", width=76, height=88)
                self._invalid_roles.discard(image.role)
            self.plan = plan
        except Exception as error:
            self.plan = None
            self.save_button.configure(state="disabled")
            self.status.set(f"미리보기 확인 실패: {error}")
            return
        self.status.set(f"저장할 이름: {self.plan.name}\n10/10 배정과 위 이미지를 확인했으면 새 세트 저장을 누르세요.")
        self.save_button.configure(state="normal")

    def save(self):
        if self.plan is None or self.saved_set is not None:
            return
        try:
            saved = self.store.save(self.plan)
        except Exception as error:
            self.plan = None
            self.save_button.configure(state="disabled")
            self.status.set(f"저장하지 못했어요: {error}\n배정은 남아 있습니다. 미리보기를 다시 확인해 주세요.")
            return
        # Commit success precedes optional UI refresh; a refresh failure must
        # not make a retry create another set from the same draft.
        self.saved_set = saved
        self.name_entry.configure(state="disabled")
        self.add_button.configure(state="disabled")
        for selector in self.selectors.values():
            selector.configure(state="disabled")
        self.cancel_button.configure(text="닫기")
        self._layout_actions()
        self.status.set(f"‘{saved.name}’ 저장 완료 · 현재 그림은 유지됩니다.\n이 세트 적용을 선택해도 상황별 수동 지정은 유지됩니다.")
        try:
            self.on_saved(saved)
        except Exception:
            self.status.set(f"‘{saved.name}’은 저장됐지만 목록 갱신을 마치지 못했어요. 다시 열면 선택할 수 있습니다.")

    def apply(self):
        if self.saved_set is None:
            return
        try:
            result = self.on_apply(self.saved_set.id)
            if result.get("status") != "applied":
                raise ValueError(result.get("summary", "세트를 적용하지 못했어요."))
            self.status.set(f"‘{self.saved_set.name}’ 적용 완료 · 상황별 수동 지정은 유지됩니다.")
        except Exception as error:
            self.status.set(f"세트는 저장되어 있어요. 적용하지 못했어요: {error}")

    def _layout_actions(self, event=None):
        buttons = ([self.apply_button, self.cancel_button] if self.saved_set is not None
                   else [self.review_button, self.save_button, self.cancel_button])
        width = event.width if event else max(1, self.actions.winfo_width())
        required = max(button.winfo_reqwidth() for button in buttons) + 8
        columns = max(1, min(len(buttons), width // required))
        layout = (self.saved_set is not None, columns)
        if layout == self._action_layout:
            return
        self._action_layout = layout
        for button in (self.review_button, self.save_button, self.apply_button, self.cancel_button):
            button.grid_forget()
        for column in range(3):
            self.actions.columnconfigure(column, weight=1 if column < columns else 0)
        for index, button in enumerate(buttons):
            button.grid(row=index // columns, column=index % columns, sticky="ew", padx=3, pady=2)

    @staticmethod
    def _wrap_label(label, width):
        width = max(1, width - 4)
        if label.winfo_pixels(label.cget("wraplength")) != width:
            label.configure(wraplength=width)

    def _show_status(self, *_args):
        # Keep the full reviewed name selectable, while long names and errors
        # cannot push the assignment viewport or action buttons off screen.
        self.status_text.configure(state="normal")
        self.status_text.delete("1.0", "end")
        self.status_text.insert("1.0", self.status.get())
        self.status_text.configure(state="disabled")
        self.status_text.yview_moveto(0)

    def _scroll_status(self, event):
        units = -1 if getattr(event, "num", 0) == 4 or getattr(event, "delta", 0) > 0 else 1
        self.status_text.yview_scroll(units * 3, "units")
        return "break"

    def _move_status_focus(self, _event=None, *, previous=False):
        target = self.status_text.tk_focusPrev() if previous else self.status_text.tk_focusNext()
        if target is not None:
            target.focus_set()
        return "break"

    def _fit_content(self, event):
        if self._width == event.width:
            return
        self._width = event.width
        self.canvas.itemconfigure(self._content_id, width=max(1, event.width))
        self._wrap_label(self.progress_label, event.width - self.add_button.winfo_reqwidth() - 16)
        for _row, _thumbnail, label in self.rows.values():
            self._wrap_label(label, max(1, event.width - 110))

    def _update_region(self, _event=None):
        region = self.canvas.bbox("all")
        if region != self._region:
            self._region = region
            self.canvas.configure(scrollregion=region)

    def _ensure_visible(self, widget):
        if not widget.winfo_exists() or not self.canvas.winfo_exists():
            return
        y = widget.winfo_rooty() - self.content.winfo_rooty()
        top = self.canvas.canvasy(0)
        height = self.canvas.winfo_height()
        if y < top:
            target = y - 8
        elif y + widget.winfo_height() > top + height:
            target = y + widget.winfo_height() - height + 8
        else:
            return
        self.canvas.yview_moveto(max(0, target) / max(1, self.content.winfo_height()))

    def _scroll(self, event):
        units = -1 if getattr(event, "num", 0) == 4 or getattr(event, "delta", 0) > 0 else 1
        self.canvas.yview_scroll(units * 3, "units")
        return "break"
