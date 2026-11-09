from __future__ import annotations

import tkinter as tk
from tkinter import messagebox

from app import AMBER, BORDER, MUTED, PANEL, PANEL_2, PURPLE, PURPLE_2, TEXT

from .ui import _Window, _label, _button, _entry, _text, _add_scrollbar, _font, _local_time


MAX_MEMORY_LENGTH = 2000


class _MemoryWindow(_Window):
    """Manage explicit memories without coupling them to conversation storage."""

    def __init__(self, owner):
        super().__init__(owner, "기억 관리", 680, 700)
        self.minsize(510, 500)
        self.entries = []
        self.visible_entries = []
        self._enabled = False
        self._editing_id = None
        self._editor_baseline = ""
        self._refreshing = False
        self._selection = set()

        self.canvas = tk.Canvas(self.body, bg=PANEL, highlightthickness=0, bd=0)
        _add_scrollbar(self.body, self.canvas)
        content = tk.Frame(self.canvas, bg=PANEL)
        self._content = content
        content_id = self.canvas.create_window(0, 0, window=content, anchor="nw")
        content.bind("<Configure>", lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda event: self.canvas.itemconfigure(content_id, width=event.width))
        self.bind("<MouseWheel>", self._scroll, add="+")
        self.bind("<Button-4>", lambda _e: self.canvas.yview_scroll(-3, "units"), add="+")
        self.bind("<Button-5>", lambda _e: self.canvas.yview_scroll(3, "units"), add="+")
        self.bind("<FocusIn>", self._focus_visible, add="+")

        header = tk.Frame(content, bg=PANEL)
        header.pack(fill="x", padx=12, pady=(10, 4))
        _label(header, "승아의 장기 기억", size=15).pack(side="left")
        _button(header, "AI 설정", owner.open_settings).pack(side="right")
        self.privacy = tk.StringVar(master=self)
        self._wrapped(content, variable=self.privacy, color=MUTED).pack(fill="x", padx=12, pady=(0, 6))
        search_row = tk.Frame(content, bg=PANEL)
        search_row.pack(fill="x", padx=12, pady=4)
        _label(search_row, "기억 검색").pack(side="left", padx=(0, 8))
        self.search = tk.StringVar(master=self)
        self.search_entry = _entry(search_row, self.search)
        self.search_entry.pack(side="left", fill="x", expand=True, ipady=3)
        _button(search_row, "지우기", lambda: self.search.set("")).pack(side="right", padx=(6, 0))
        self.counts = tk.StringVar(master=self)
        self._wrapped(content, variable=self.counts, size=9, color=MUTED).pack(fill="x", padx=12, pady=3)

        list_frame = tk.Frame(content, bg=PANEL)
        self.listbox = tk.Listbox(
            list_frame, height=6, selectmode="extended", activestyle="dotbox",
            exportselection=False, font=_font(self), fg=TEXT, bg=PANEL_2,
            selectforeground=TEXT, selectbackground=PURPLE_2, relief="flat",
            highlightthickness=1, highlightbackground=BORDER, highlightcolor=PURPLE,
        )
        _add_scrollbar(list_frame, self.listbox)
        self.listbox.bind("<<ListboxSelect>>", self._show_selected)
        self.listbox.bind("<Double-Button-1>", lambda _event: self._edit())
        self.listbox.bind("<Return>", lambda _event: self._edit())
        self.listbox.bind("<Delete>", lambda _event: self._delete())

        bottom = tk.Frame(content, bg=PANEL)
        bottom.pack(side="bottom", fill="x")
        detail_frame = tk.Frame(bottom, bg=PANEL)
        detail_frame.pack(fill="x", padx=12, pady=(5, 0))
        self.detail = _text(detail_frame, height=3, state="disabled")
        _add_scrollbar(detail_frame, self.detail)
        controls = tk.Frame(bottom, bg=PANEL)
        controls.pack(fill="x", padx=12, pady=5)
        self.edit_button = _button(controls, "수정", self._edit)
        self.edit_button.pack(side="left")
        self.pin_button = _button(controls, "고정", self._pin)
        self.pin_button.pack(side="left", padx=5)
        self.delete_button = _button(controls, "선택 삭제", self._delete)
        self.delete_button.pack(side="left")
        self.clear_button = _button(controls, "전체 삭제", self._clear)
        self.clear_button.pack(side="right")
        self.editor_title = tk.StringVar(master=self, value="새 기억 추가")
        self._wrapped(bottom, variable=self.editor_title).pack(fill="x", padx=12, pady=(5, 3))
        add_frame = tk.Frame(bottom, bg=PANEL)
        add_frame.pack(fill="x", padx=12)
        self.add_text = _text(add_frame, height=3, undo=True)
        _add_scrollbar(add_frame, self.add_text)
        self.add_text.bind("<<Modified>>", self._editor_changed)
        self.add_text.bind("<Control-Return>", self._save_keyboard)
        self.length_status = tk.StringVar(master=self, value="0 / 2,000자")
        _label(bottom, textvariable=self.length_status, size=9, color=MUTED).pack(anchor="w", padx=12, pady=(4, 0))
        editor_buttons = tk.Frame(bottom, bg=PANEL)
        editor_buttons.pack(fill="x", padx=12, pady=5)
        self.new_button = _button(editor_buttons, "새 기억", self._new)
        self.new_button.pack(side="left", padx=7)
        self.discard_button = _button(editor_buttons, "편집 취소", self._discard_editor)
        self.discard_button.pack(side="left")
        self.add_button = _button(editor_buttons, "기억 저장", self._save_editor, primary=True)
        self.add_button.pack(side="right")
        self.status = tk.StringVar(master=self)
        self._wrapped(bottom, variable=self.status, color=AMBER, size=9).pack(fill="x", padx=12, pady=(0, 8))
        self.search.trace_add("write", self._filter)
        list_frame.pack(fill="both", expand=True, padx=12)

    def _scroll(self, event):
        if isinstance(event.widget, (tk.Text, tk.Listbox)) or not event.delta:
            return
        self.canvas.yview_scroll(-3 if event.delta > 0 else 3, "units")
        return "break"

    def _focus_visible(self, event):
        self.after_idle(lambda: self._ensure_visible(event.widget))

    def _ensure_visible(self, widget):
        try:
            if not widget.winfo_exists() or not str(widget).startswith(str(self._content) + "."):
                return
            self.update_idletasks()
            top = widget.winfo_rooty() - self._content.winfo_rooty()
            bottom = top + widget.winfo_height()
            visible_top = self.canvas.canvasy(0)
            visible_bottom = self.canvas.canvasy(self.canvas.winfo_height())
            total = max(1, self._content.winfo_height())
            if top < visible_top:
                self.canvas.yview_moveto(max(0, top - 10) / total)
            elif bottom > visible_bottom:
                self.canvas.yview_moveto(max(0, bottom + 10 - self.canvas.winfo_height()) / total)
        except tk.TclError:
            pass

    def _wrapped(self, parent, text="", *, variable=None, color=TEXT, size=10):
        options = {"textvariable": variable} if variable is not None else {}
        label = _label(parent, text, color=color, size=size, wraplength=450, **options)
        label.bind("<Configure>", lambda event: label.configure(wraplength=max(100, event.width)))
        return label

    def _selected_entries(self):
        return [self.visible_entries[index] for index in self.listbox.curselection() if index < len(self.visible_entries)]

    def _selected(self):
        entries = self._selected_entries()
        return entries[0] if len(entries) == 1 else None

    def refresh(self, *, select_ids=None):
        keep = set(select_ids) if select_ids is not None else {entry.id for entry in self._selected_entries()}
        try:
            self._enabled = self.service.load_settings().memory_enabled
            self.entries = self.service.memory.list_memories()
            counts = self.service.history_counts()
        except Exception:
            self.status.set("기억을 불러오지 못했어요. 입력 중인 내용은 유지했어요.")
            return
        saved_turns = counts.get("conversation_turns", 0)
        if self._enabled:
            message = "기억을 대화에 활용해요. 관련 기억은 OpenAI에 전달될 수 있어요."
        else:
            message = "기억 활용이 꺼져 있어요. 기존 기억의 확인·수정·삭제는 가능해요."
        self.privacy.set(f"{message}\n저장된 대화 {saved_turns:,}개는 별도로 관리해요.")
        self._selection = keep
        self._filter(preserve_ids=keep)
        self._update_editor_controls()
        self.clear_button.configure(state="normal" if self.entries else "disabled")

    def _filter(self, *_args, preserve_ids=None):
        keep = set(preserve_ids) if preserve_ids is not None else {entry.id for entry in self._selected_entries()}
        words = self.search.get().casefold().split()
        self.visible_entries = [entry for entry in self.entries if all(word in entry.text.casefold() for word in words)]
        self._refreshing = True
        try:
            self.listbox.delete(0, "end")
            for index, entry in enumerate(self.visible_entries):
                summary = " ".join(entry.text.split())
                summary = summary[:85] + "…" if len(summary) > 86 else summary
                self.listbox.insert("end", ("★ " if entry.pinned else "") + summary)
                if entry.id in keep:
                    self.listbox.selection_set(index)
                    self.listbox.see(index)
        finally:
            self._refreshing = False
        self._show_selected()

    def _show_selected(self, _event=None):
        if self._refreshing:
            return
        selected = self._selected_entries()
        self._selection = {entry.id for entry in selected}
        self.counts.set(f"전체 {len(self.entries):,}개 · 검색 {len(self.visible_entries):,}개 · 선택 {len(selected):,}개 · 고정 {sum(entry.pinned for entry in self.entries):,}개")
        self.edit_button.configure(state="normal" if len(selected) == 1 else "disabled")
        self.pin_button.configure(state="normal" if selected else "disabled", text="고정 해제" if selected and all(entry.pinned for entry in selected) else "고정")
        self.delete_button.configure(state="normal" if selected else "disabled", text=f"선택 {len(selected)}개 삭제" if selected else "선택 삭제")
        self.detail.configure(state="normal")
        self.detail.delete("1.0", "end")
        if len(selected) == 1:
            entry = selected[0]
            timestamp = _local_time(entry.created_at)
            heading = ("고정 · " if entry.pinned else "") + (f"저장 {timestamp}\n\n" if timestamp else "")
            self.detail.insert("1.0", heading + entry.text)
        elif selected:
            self.detail.insert("1.0", f"기억 {len(selected):,}개를 선택했어요. 수정할 때는 하나만 선택해 주세요.")
        else:
            self.detail.insert("1.0", "검색 결과가 없어요." if self.search.get().strip() and not self.visible_entries else "기억을 선택하면 여기에서 전문을 볼 수 있어요.")
        self.detail.configure(state="disabled")

    @property
    def _editor_dirty(self):
        return self.add_text.get("1.0", "end-1c") != self._editor_baseline

    def _editor_changed(self, _event=None):
        if self.add_text.edit_modified():
            self.add_text.edit_modified(False)
            self._update_editor_controls()

    def _update_editor_controls(self):
        text = self.add_text.get("1.0", "end-1c")
        length = len(text.strip())
        self.length_status.set(f"{length:,} / 2,000자" + (" · 길이를 줄여 주세요" if length > MAX_MEMORY_LENGTH else ""))
        allowed = self._enabled or self._editing_id is not None
        self.add_button.configure(state="normal" if allowed and 0 < length <= MAX_MEMORY_LENGTH else "disabled")
        self.new_button.configure(state="normal" if self._enabled else "disabled")
        self.discard_button.configure(state="normal" if self._editor_dirty or self._editing_id is not None else "disabled")

    def _can_replace_editor(self):
        if not self._editor_dirty:
            return True
        decision = messagebox.askyesnocancel("기억 편집", "입력 중인 기억을 먼저 저장할까요?\n아니요를 누르면 입력 중인 내용을 버려요.", parent=self)
        if decision is None:
            return False
        return self._save_editor() if decision else True

    def _set_editor(self, text="", entry_id=None):
        self._editing_id = entry_id
        self._editor_baseline = text
        self.add_text.delete("1.0", "end")
        self.add_text.insert("1.0", text)
        self.add_text.edit_modified(False)
        self.editor_title.set("선택한 기억 수정 · Ctrl+Enter로 저장" if entry_id is not None else "새 기억 추가 · Ctrl+Enter로 저장")
        self.add_button.configure(text="수정 저장" if entry_id is not None else "기억 저장")
        self._update_editor_controls()

    def _new(self):
        if not self._enabled:
            self.status.set("새 기억을 추가하려면 AI 설정에서 장기 기억 활용을 켜 주세요.")
            return
        if self._can_replace_editor():
            self._set_editor()
            self.add_text.focus_set()

    def _edit(self):
        entry = self._selected()
        if entry is not None and self._can_replace_editor():
            self._set_editor(entry.text, entry.id)
            self.add_text.focus_set()
        return "break"

    def _discard_editor(self):
        self._set_editor()
        self.status.set("편집 중인 내용을 버렸어요.")

    def _save_keyboard(self, _event):
        self._save_editor()
        return "break"

    def _save_editor(self):
        text = self.add_text.get("1.0", "end-1c").strip()
        if not 1 <= len(text) <= MAX_MEMORY_LENGTH:
            self.status.set("기억은 1~2,000자로 입력해 주세요.")
            return False
        editing = self._editing_id is not None
        try:
            if editing:
                entry = self.service.memory.update_memory(self._editing_id, text)
                created = False
            else:
                entry, created = self.service.memory.add_memory_with_result(text)
            if entry is None:
                self.status.set("선택한 기억이 삭제되었어요. 새 기억으로 저장해 주세요." if editing else "AI 설정에서 장기 기억 활용을 켜 주세요.")
                return False
            if editing or created:
                self.service.invalidate_context()
        except ValueError as error:
            self.status.set(str(error))
            return False
        except Exception:
            self.status.set("기억을 저장하지 못했어요. 입력 중인 내용은 유지했어요.")
            return False
        self._set_editor()
        self.search.set("")
        self.refresh(select_ids={entry.id})
        self.status.set("기억을 수정했어요." if editing else "기억을 저장했어요." if created else "같은 기억이 이미 있어 기존 항목을 선택했어요.")
        return True

    def _add(self):
        return self._save_editor()

    def _pin(self):
        entries = self._selected_entries()
        if not entries:
            return
        pinned = not all(entry.pinned for entry in entries)
        changed = 0
        try:
            for entry in entries:
                if self.service.memory.set_memory_pinned(entry.id, pinned) is not None:
                    changed += 1
        except Exception:
            self.status.set("고정 상태를 모두 바꾸지 못했어요. 목록을 확인해 주세요.")
        else:
            self.status.set(f"기억 {changed:,}개를 " + ("고정했어요." if pinned else "고정 해제했어요."))
        finally:
            if changed:
                self.service.invalidate_context()
            self.refresh(select_ids={entry.id for entry in entries})

    def _delete(self):
        entries = self._selected_entries()
        if not entries:
            return "break"
        count = len(entries)
        if not messagebox.askyesno("선택한 기억 삭제", f"선택한 기억 {count:,}개를 지울까요?\n선택하지 않은 기억과 대화 기록은 유지돼요.", parent=self):
            return "break"
        deleted = 0
        try:
            for entry in entries:
                deleted += bool(self.service.delete_memory(entry.id))
        except Exception:
            self.status.set(f"{deleted:,}개를 삭제했어요. 나머지는 삭제하지 못했어요.")
        else:
            self.status.set(f"선택한 기억 {deleted:,}개를 지웠어요.")
        self.refresh()
        if self._editing_id is not None and self._editing_id not in {entry.id for entry in self.entries}:
            self._editing_id = None
            self._editor_baseline = ""
            self.editor_title.set("삭제된 기억의 편집 초안 · 새 기억으로 저장 가능")
            self.add_button.configure(text="새 기억으로 저장")
            self._update_editor_controls()
        return "break"

    def _clear(self):
        count = len(self.entries)
        if not count or not messagebox.askyesno("모든 기억 삭제", f"검색 조건과 관계없이 장기 기억 {count:,}개를 모두 지울까요?\n대화 기록은 지워지지 않아요.", parent=self):
            return
        try:
            self.service.clear_memories()
        except Exception:
            self.status.set("기억을 지우지 못했어요.")
            return
        self._editing_id = None
        self._editor_baseline = ""
        self.editor_title.set("새 기억 추가 · 입력 중인 초안은 유지했어요.")
        self.add_button.configure(text="기억 저장")
        self.refresh()
        self.status.set(f"장기 기억 {count:,}개를 모두 지웠어요. 대화 기록은 유지했어요.")
