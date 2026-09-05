from __future__ import annotations

from pathlib import Path
import re


def replace_once(text: str, pattern: str, replacement: str, label: str) -> str:
    updated, count = re.subn(pattern, replacement, text, count=1, flags=re.S)
    if count != 1:
        raise SystemExit(f"expected exactly one {label} match, got {count}")
    return updated


def patch_desktop_app() -> None:
    path = Path("desktop_app.py")
    text = path.read_text(encoding="utf-8")

    build_method = '''    def _build_stats_page(self):
        page = self.stats_page
        self._build_header(
            page,
            "상세 정보",
            back_command=lambda: self._show_page("timer"),
            settings_command=lambda: self._show_page("settings"),
        )

        body = tk.Frame(page, bg=core.BG)
        body.pack(fill="both", expand=True, padx=7, pady=(2, 7))
        body.grid_columnconfigure(0, weight=1)
        body.grid_rowconfigure(0, weight=1)

        panel = self._card(body)
        panel.grid(row=0, column=0, sticky="nsew")

        summary = tk.Frame(panel, bg=core.PANEL)
        summary.pack(fill="x", padx=12, pady=(8, 4))
        self.detail_cont = self._label(summary, "00:00:00", size=20, weight="bold", bg=core.PANEL)
        self.detail_cont.pack(side="left")
        self.status = self._label(summary, "현재 사용 중", size=8, weight="bold", fg=core.GREEN, bg=core.PANEL)
        self.status.pack(side="right")

        progress_wrap = tk.Frame(panel, bg=core.PANEL)
        progress_wrap.pack(fill="x", padx=12, pady=(1, 5))
        progress_text = tk.Frame(progress_wrap, bg=core.PANEL)
        progress_text.pack(fill="x")
        self._label(progress_text, "다음 휴식까지", size=8, fg=core.MUTED, bg=core.PANEL).pack(side="left")
        self.remain = self._label(progress_text, "60분", size=8, weight="bold", bg=core.PANEL)
        self.remain.pack(side="right")
        self.progress_canvas = tk.Canvas(progress_wrap, height=6, bg=core.PANEL_2, highlightthickness=0, bd=0)
        self.progress_canvas.pack(fill="x", pady=(3, 0))
        self.progress_bar = self.progress_canvas.create_rectangle(0, 0, 0, 6, fill=core.PURPLE, outline="")
        self.progress_canvas.bind("<Configure>", lambda _e: self._update_progress())

        metrics = tk.Frame(panel, bg=core.PANEL)
        metrics.pack(fill="x", padx=12, pady=(1, 5))
        for i in range(3):
            metrics.grid_columnconfigure(i, weight=1)
        self.today_active = self._metric(metrics, 0, "오늘 실사용")
        self.today_away = self._metric(metrics, 1, "자리비움")
        self.today_ratio = self._metric(metrics, 2, "실사용률")

        self.stats_values = {}
        for key, caption in (
            ("count", "휴식 횟수"),
            ("longest", "최장 연속 사용"),
        ):
            row = tk.Frame(panel, bg=core.PANEL)
            row.pack(fill="x", padx=12, pady=1)
            self._label(row, caption, size=8, fg=core.MUTED, bg=core.PANEL).pack(side="left")
            value = self._label(row, "-", size=9, weight="bold", bg=core.PANEL)
            value.pack(side="right")
            self.stats_values[key] = value

        self._label(panel, "최근 7일", size=8, weight="bold", fg=core.MUTED, bg=core.PANEL).pack(
            anchor="w", padx=12, pady=(5, 1)
        )
        for key, caption in (
            ("week_active", "7일 실사용"),
            ("week_average", "기록일 평균"),
            ("week_best", "최고 집중일"),
        ):
            row = tk.Frame(panel, bg=core.PANEL)
            row.pack(fill="x", padx=12, pady=1)
            self._label(row, caption, size=8, fg=core.MUTED, bg=core.PANEL).pack(side="left")
            value = self._label(row, "-", size=9, weight="bold", bg=core.PANEL)
            value.pack(side="right")
            self.stats_values[key] = value

        self.stats_reaction = self._label(
            panel,
            "",
            size=8,
            fg=core.TEXT,
            bg=core.PANEL_2,
            wraplength=350,
            justify="left",
        )
        self.stats_reaction.pack(fill="x", padx=12, pady=(5, 3), ipadx=7, ipady=4)

        actions = tk.Frame(panel, bg=core.PANEL)
        actions.pack(fill="x", padx=12, pady=(3, 4))
        self.away_btn = self._button(actions, "자리비움 시작", self.toggle_manual_away, primary=True)
        self.away_btn.pack(side="left", fill="x", expand=True, padx=(0, 4))
        self._button(actions, "기본 화면", lambda: self._show_page("timer")).pack(
            side="left", fill="x", expand=True, padx=(4, 0)
        )

        footer = self._card(panel, bg=core.PANEL_2)
        footer.pack(fill="x", padx=12, pady=(0, 8))
        self.next_break = self._label(footer, "다음 휴식 알림: 60분 후", size=8, fg=core.MUTED, bg=core.PANEL_2)
        self.next_break.pack(side="left", padx=8, pady=4)

'''

    update_method = '''    def _update_stats_page(self, refresh_image=True):
        from stats_summary import stats_reaction, summarize_recent

        d = self.state.daily
        self.stats_values["count"].configure(text=f"{d.away_count}회")
        self.stats_values["longest"].configure(text=core.fmt(d.longest_continuous_today))

        recent = summarize_recent(self.state, days=7)
        self.stats_values["week_active"].configure(text=core.fmt(recent.active_seconds))
        average_text = core.fmt(recent.average_active_seconds) if recent.tracked_days else "-"
        self.stats_values["week_average"].configure(text=average_text)
        if recent.best_day:
            try:
                _, month, day = recent.best_day.split("-")
                best_day = f"{int(month)}/{int(day)} · {core.fmt(recent.best_day_active_seconds)}"
            except (ValueError, TypeError):
                best_day = core.fmt(recent.best_day_active_seconds)
        else:
            best_day = "-"
        self.stats_values["week_best"].configure(text=best_day)
        self.stats_reaction.configure(text=stats_reaction(recent))

'''

    text = replace_once(
        text,
        r"    def _build_stats_page\(self\):\n.*?(?=    def _update_stats_page\(self, refresh_image=True\):)",
        build_method,
        "desktop stats build method",
    )
    text = replace_once(
        text,
        r"    def _update_stats_page\(self, refresh_image=True\):\n.*?(?=    def _build_settings_page\(self\):)",
        update_method,
        "desktop stats update method",
    )
    path.write_text(text, encoding="utf-8")


def patch_project_phases() -> None:
    path = Path("PROJECT_PHASES.md")
    text = path.read_text(encoding="utf-8")

    phase6 = '''## Phase 6 — Work/break behavior

### Status: CODE INTEGRATED / MULTI-DAY REAL-WORLD VALIDATION PENDING

Implemented:
- Configurable break interval: 20–180 minutes, default 60.
- Configurable snooze duration: 1–30 minutes, default 5; popup wording follows the configured value.
- “오늘은 그만” suppresses break reminders for the current local day, survives restart, and resets at the next local day rollover.
- Manual away, automatic away, workday/leave reminders, and the 9-hour hard stop remain independent from daily break suppression.
- Fullscreen/presentation mode does not consume a hidden break reminder; a still-due reminder may appear immediately after presentation mode ends.
- Phase 6 regression tests and Windows package/smoke checks pass.

Remaining before full closure:
- Multi-day real-world use to verify day rollover, sleep/lock gaps, suppression reset, and reminder timing under normal work conditions.
- Refine away/workday policy only if a concrete real-use regression appears.
- Optional Pomodoro mode remains deferred.

'''

    phase7 = '''## Phase 7 — Stats

### Status: ACTIVE / 7-DAY HISTORY FOUNDATION INTEGRATED

Implemented:
- State schema 8 archives completed daily records and keeps up to 30 days of history.
- Existing state files migrate safely with empty history; malformed historical entries are ignored.
- Recent-stat helpers produce a calendar-aligned 7-day window with current-day data taking priority.
- The desktop detail screen shows 7-day active time, average active time across recorded days, and the best active day alongside today's metrics.
- A lightweight Kyunghee stats reaction uses the recent summary without introducing levels, scores, or a heavy game system.

Next validation/tuning:
- Verify archived totals over several real day rollovers.
- Adjust compact detail spacing or wording only if real Windows use feels crowded.
- Streak-style summaries remain optional; CSV export stays deferred until actually useful.

Data correctness remains more important than visual complexity.

'''

    text = replace_once(
        text,
        r"## Phase 6 — Work/break behavior\n.*?(?=---\n\n## Phase 7 — Stats)",
        phase6,
        "Phase 6 section",
    )
    text = replace_once(
        text,
        r"## Phase 7 — Stats\n.*?(?=---\n\n## Explicitly deferred / not now)",
        phase7,
        "Phase 7 section",
    )
    text = text.replace(
        "10. Phases 4 and 5 are complete; preserve the image-set/preview and personality systems. Phase 6 is active.",
        "10. Phases 4 and 5 are complete; preserve the image-set/preview and personality systems. Phase 6 code is integrated and under real-world validation; Phase 7 stats work is active.",
    )
    text = text.replace(
        "- Phase 5 personality/fun behavior scope is complete; Phase 6 work/break behavior is now active.",
        "- Phase 5 personality/fun behavior scope is complete. Phase 6 code is integrated and awaiting multi-day real-world validation. Phase 7 recent-stats work is active.",
    )
    path.write_text(text, encoding="utf-8")


def main() -> None:
    patch_desktop_app()
    patch_project_phases()
    print("Phase 7 stats UI and project status patched")


if __name__ == "__main__":
    main()
