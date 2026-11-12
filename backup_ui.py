"""Tk settings panel for local profile backups and private-by-default diagnostics."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from app_brand import APP_VERSION

from user_data_backup import (
    BackupError, CATEGORY_LABELS, RestoreRecoveryError, RestoreResult, create_backup, default_data_dir, diagnostic_report,
    export_diagnostics, inspect_backup, preview_source, restore_backup,
)


def open_backup_panel(parent, *, data_dir=None, app_version=APP_VERSION,
                      before_restore=None, on_restore_complete=None, after_restore_failure=None):
    """Open the panel; callbacks run synchronously on the Tk thread.

    before_restore() must return True only after preventing every profile writer
    and flushing current state. A False result leaves the app running unchanged.
    on_restore_complete(RestoreResult) must exit without saving stale state;
    recovery_required=True indicates incomplete rollback requiring manual recovery.
    after_restore_failure() resumes writers after an unsuccessful restore.
    Without all three callbacks, restoration is disabled; exports remain usable.
    No callback may pump Tk events while restoration has exclusive profile access.
    """
    return BackupPanel(parent, data_dir=Path(data_dir) if data_dir else default_data_dir(),
                       app_version=app_version, before_restore=before_restore,
                       on_restore_complete=on_restore_complete, after_restore_failure=after_restore_failure)


class BackupPanel(tk.Toplevel):
    def __init__(self, parent, *, data_dir, app_version, before_restore,
                 on_restore_complete, after_restore_failure):
        super().__init__(parent)
        self.title("승아 · 데이터 백업 및 복원")
        width, height = min(720, self.winfo_screenwidth() - 40), min(690, self.winfo_screenheight() - 60)
        self.geometry(f"{width}x{height}+{max(0, (self.winfo_screenwidth() - width) // 2)}+{max(0, (self.winfo_screenheight() - height) // 2)}")
        self.minsize(580, 540)
        self.transient(parent)
        self.data_dir, self.app_version = data_dir, app_version
        self.before_restore = before_restore
        self.on_restore_complete = on_restore_complete
        self.after_restore_failure = after_restore_failure
        self.restore_enabled = all(callable(c) for c in (before_restore, on_restore_complete, after_restore_failure))
        self.archive = None
        self.archive_preview = None
        self.vars = {c: tk.BooleanVar(self, value=c != "chat") for c in CATEGORY_LABELS}
        footer = ttk.Frame(self, padding=(16, 8))
        footer.pack(side="bottom", fill="x")
        viewport = ttk.Frame(self)
        viewport.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(viewport, highlightthickness=0)
        scrollbar = ttk.Scrollbar(viewport, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        shell = ttk.Frame(self.canvas, padding=16)
        shell_id = self.canvas.create_window((0, 0), window=shell, anchor="nw")
        shell.bind("<Configure>", lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        def fit_width(event):
            self.canvas.itemconfigure(shell_id, width=event.width)
            for container in (shell, footer):
                for child in container.winfo_children():
                    if child.winfo_class() == "TLabel":
                        child.configure(wraplength=max(250, event.width - 34))
        self.canvas.bind("<Configure>", fit_width)
        self.bind("<MouseWheel>", lambda event: self.canvas.yview_scroll(-1 if event.delta > 0 else 1, "units"))
        self.bind("<Button-4>", lambda _e: self.canvas.yview_scroll(-1, "units"))
        self.bind("<Button-5>", lambda _e: self.canvas.yview_scroll(1, "units"))
        ttk.Label(shell, text="내 데이터 백업 · 복원", font=("Malgun Gothic", 15, "bold")).pack(anchor="w")
        ttk.Label(shell, text="백업할 항목을 직접 고르세요. 파일은 이 PC에만 저장되며 자동 전송되지 않아요.", wraplength=650).pack(anchor="w", pady=(6, 12))
        for category, label in CATEGORY_LABELS.items():
            ttk.Checkbutton(shell, text=label, variable=self.vars[category], command=self._selection_changed).pack(anchor="w", pady=3)
        ttk.Label(shell, text="대화·기억은 선택한 경우에만 포함해요. API 키 파일과 로그는 항상 제외하며, 알려진 인증 문자열은 가립니다. 사용자 이미지나 대화에는 개인 정보가 들어 있을 수 있으니 백업 파일을 안전하게 보관해 주세요.", wraplength=650).pack(anchor="w", pady=(8, 10))
        ttk.Label(shell, text="이미지 ZIP 팩 = 캐릭터 이미지 가져오기용\n사용자 데이터 백업 (.seunga-backup.zip) = 선택한 기록·설정·이미지·AI 데이터 복원용", wraplength=650).pack(anchor="w", pady=(0, 12))
        buttons = ttk.Frame(shell)
        buttons.pack(fill="x")
        ttk.Button(buttons, text="백업 미리 보기", command=self._preview_source).pack(side="left", padx=(0, 6))
        ttk.Button(buttons, text="선택 항목 백업 저장…", command=self._save_backup).pack(side="left", padx=(0, 6))
        ttk.Button(buttons, text="복원 파일 선택…", command=self._choose_restore).pack(side="left")
        self.preview = tk.Text(shell, height=10, wrap="word", state="disabled", font=("Malgun Gothic", 10))
        self.preview.pack(fill="both", expand=True, pady=12)
        restore_row = ttk.Frame(footer)
        restore_row.pack(fill="x")
        self.restore_button = ttk.Button(restore_row, text="선택 항목 복원 후 앱 종료", command=self._restore, state="disabled")
        self.restore_button.pack(side="left")
        ttk.Label(footer, text="복원은 선택한 항목을 백업 시점으로 바꿉니다. 이후 추가한 같은 항목의 데이터는 현재 데이터 복구 백업에 보관됩니다. 복원 후 앱을 다시 실행해 주세요.", wraplength=650).pack(anchor="w", pady=(8, 10))
        diagnostic_row = ttk.Frame(footer)
        diagnostic_row.pack(fill="x")
        ttk.Button(diagnostic_row, text="개인 정보 제외 진단 내보내기…", command=self._diagnostics).pack(side="left")
        ttk.Button(diagnostic_row, text="닫기", command=self.destroy).pack(side="right")
        self.status = ttk.Label(footer, text="", wraplength=650)
        self.status.pack(anchor="w", pady=(8, 0))
        self._preview_source()

    def _selected(self):
        return tuple(c for c, value in self.vars.items() if value.get())

    def _write_preview(self, text):
        self.preview.configure(state="normal")
        self.preview.delete("1.0", "end")
        self.preview.insert("1.0", text)
        self.preview.configure(state="disabled")

    @staticmethod
    def _describe(preview):
        lines = [f"파일 {preview.file_count}개 · 약 {preview.total_bytes / (1024 * 1024):.2f} MB"]
        if preview.created_at:
            lines.append(f"백업 생성: {preview.created_at}")
        lines.extend(f"• {CATEGORY_LABELS[c]}: {preview.counts[c]}개" for c in preview.categories)
        empty = [CATEGORY_LABELS[c] for c in preview.categories if not preview.counts[c]]
        if empty:
            lines.append("빈 항목: " + ", ".join(empty))
        return "\n".join(lines)

    def _selection_changed(self):
        self.archive = self.archive_preview = None
        self.restore_button.configure(state="disabled")
        self._preview_source()

    def _preview_source(self):
        try:
            preview = preview_source(self.data_dir, self._selected())
            self._write_preview("현재 데이터 백업 미리 보기\n\n" + self._describe(preview) + "\n\n개인 폴더 바깥의 원본 이미지 경로, 키 파일, 로그, 임시 파일은 포함하지 않습니다.")
            self.status.configure(text="백업 전 미리 보기는 파일 개수와 크기이며, 저장할 때 내용 검증과 키 마스킹을 수행합니다.")
        except (BackupError, OSError) as error:
            self._error(error)

    def _error(self, error):
        text = str(error) if isinstance(error, BackupError) else "파일을 읽거나 저장하지 못했어요. 권한과 남은 저장 공간을 확인해 주세요."
        self.status.configure(text=text)
        messagebox.showerror("데이터 백업 및 복원", text, parent=self)

    def _save_backup(self):
        try:
            preview = preview_source(self.data_dir, self._selected())
            if not messagebox.askokcancel("백업 항목 확인", self._describe(preview) + "\n\n이 항목을 파일로 저장할까요? API 키 파일은 포함되지 않습니다.", parent=self):
                return
            output = filedialog.asksaveasfilename(parent=self, title="사용자 데이터 백업 저장", defaultextension=".zip",
                                                initialfile=datetime.now().strftime("Seunga-%Y%m%d-%H%M.seunga-backup.zip"),
                                                filetypes=[("승아 사용자 데이터 백업", "*.seunga-backup.zip")])
            if not output:
                return
            self.status.configure(text="검증하고 백업을 저장하고 있어요…")
            self.update_idletasks()
            saved = create_backup(self.data_dir, Path(output), self._selected(), app_version=self.app_version)
            self._write_preview("백업 저장 완료\n\n" + self._describe(saved))
            self.status.configure(text="백업을 저장했어요. 선택한 위치에서 확인할 수 있어요.")
        except (BackupError, OSError) as error:
            self._error(error)

    def _choose_restore(self):
        selected = filedialog.askopenfilename(parent=self, title="사용자 데이터 백업 선택", filetypes=[("승아 사용자 데이터 백업", "*.seunga-backup.zip"), ("ZIP 파일", "*.zip")])
        if not selected:
            return
        try:
            self.status.configure(text="백업 내용과 안전성을 검증하고 있어요…")
            self.update_idletasks()
            preview = inspect_backup(Path(selected))
            self.archive, self.archive_preview = Path(selected), preview
            for category, value in self.vars.items():
                value.set(category in preview.categories)
            self._write_preview("복원 미리 보기 · 선택한 파일의 내용\n\n" + self._describe(preview) + "\n\n복원할 항목의 현재 데이터는 자동으로 backups 폴더에 먼저 백업됩니다. 선택한 항목 전체를 백업 시점으로 되돌리며, 빈 항목은 현재 데이터를 비웁니다. 기존 보호 API 키와 이 PC의 키 보관 정책은 유지합니다. 실행 중에만 보관한 키는 종료 후 다시 입력해야 합니다.\n\n일부 항목만 복원하려면 아래 복원 버튼을 누른 뒤 항목을 선택하세요.")
            self.restore_button.configure(state="normal" if self.restore_enabled else "disabled")
            self.status.configure(text="내용 검증을 완료했어요. 복원 버튼을 눌러야 변경됩니다." if self.restore_enabled else "이 실행 화면에서는 안전한 종료 절차가 연결되어 있지 않아 복원이 비활성화되어 있어요.")
        except (BackupError, OSError) as error:
            self.archive = self.archive_preview = None
            self.restore_button.configure(state="disabled")
            self._error(error)

    def _restore(self):
        if not self.archive or not self.archive_preview or not self.restore_enabled:
            return
        dialog = tk.Toplevel(self)
        dialog.title("복원 항목 선택")
        dialog.transient(self)
        frame = ttk.Frame(dialog, padding=16)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="백업 시점으로 되돌릴 항목을 선택하세요.").pack(anchor="w")
        chosen = {}
        for category in self.archive_preview.categories:
            chosen[category] = tk.BooleanVar(dialog, value=True)
            count = self.archive_preview.counts[category]
            ttk.Checkbutton(frame, text=f"{CATEGORY_LABELS[category]} ({count}개{' · 현재 데이터 비움' if count == 0 else ''})", variable=chosen[category]).pack(anchor="w", pady=4)
        def apply():
            categories = tuple(c for c, value in chosen.items() if value.get())
            if not categories:
                return
            if not messagebox.askokcancel("복원 및 종료 확인", "선택한 현재 데이터를 자동 백업한 다음 복원하고 앱을 종료합니다.\n\n" + "\n".join(CATEGORY_LABELS[c] for c in categories) + "\n\n계속할까요?", parent=dialog):
                return
            dialog.destroy()
            try:
                ready = self.before_restore()
            except Exception:
                self._error(BackupError("진행 중인 작업을 안전하게 정리하지 못했어요. 잠시 후 다시 시도해 주세요."))
                return
            if ready is not True:
                self._error(BackupError("AI 요청이나 다른 작업이 진행 중이에요. 작업이 끝난 뒤 다시 복원해 주세요."))
                return
            # Do not call update()/wait_window() or display a modal until finished:
            # those would let old periodic state writers run during the transaction.
            try:
                result = restore_backup(self.archive, self.data_dir, categories, app_is_quiescent=True,
                                        expected_fingerprint=self.archive_preview.fingerprint,
                                        app_version=self.app_version)
            except RestoreRecoveryError as error:
                # Never resume a writer on a partially restored profile.
                self.on_restore_complete(RestoreResult(error.recovery_backup, categories, recovery_required=True))
                return
            except (BackupError, OSError) as error:
                self.after_restore_failure()
                self._error(error)
                return
            self.on_restore_complete(result)
        ttk.Button(frame, text="복원 후 앱 종료", command=apply).pack(anchor="e", pady=(12, 0))
        dialog.grab_set()

    def _diagnostics(self):
        # Preview the allowlisted fields; raw log contents are never exported.
        report = diagnostic_report(self.data_dir, app_version=self.app_version)
        if not messagebox.askokcancel("진단 정보 확인", "포함: 앱 버전, 운영체제 종류, Python 버전, 안전한 설정값, 오류 분류\n\n제외: API 키, 대화·기억 내용, 타이머 기록, 이미지, 원본 로그, 절대 경로·사용자 이름, 날씨 지역, 커스텀 대사\n\n이 파일은 자동 전송되지 않습니다. 내보낼까요?", parent=self):
            return
        output = filedialog.asksaveasfilename(parent=self, title="진단 정보 저장", defaultextension=".json",
                                            initialfile="Seunga-diagnostics.json", filetypes=[("JSON 진단 정보", "*.json")])
        if not output:
            return
        try:
            export_diagnostics(self.data_dir, Path(output), app_version=self.app_version)
            self._write_preview("진단 내보내기 완료\n\n" + f"앱 버전: {report['app_version']}\n시스템: {report['platform']['system']}\nPython: {report['platform']['python']}\n\n개인 내용이나 파일 경로는 포함되지 않습니다.")
            self.status.configure(text="진단 JSON 파일을 저장했어요. 공유는 사용자가 직접 선택합니다.")
        except (BackupError, OSError) as error:
            self._error(error)
