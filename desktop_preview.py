from __future__ import annotations

from pathlib import Path
import tkinter as tk
from PIL import Image, ImageTk

ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / "assets"

BG = "#070B1B"
PANEL = "#0E1528"
PANEL_2 = "#121B31"
BORDER = "#27304C"
TEXT = "#F7F4FF"
MUTED = "#9EA8BE"
PURPLE = "#7C4DFF"
PURPLE_2 = "#5D35D6"
PINK = "#FF5CA8"
GREEN = "#4ADE80"


def label(parent, text="", size=10, weight="normal", fg=TEXT, bg=None, **kw):
    return tk.Label(parent, text=text, font=("Malgun Gothic", size, weight), fg=fg,
                    bg=bg or parent.cget("bg"), **kw)


def card(parent, bg=PANEL, **kw):
    return tk.Frame(parent, bg=bg, highlightthickness=1, highlightbackground=BORDER, **kw)


def button(parent, text, primary=False):
    return tk.Button(parent, text=text, font=("Malgun Gothic", 10, "bold"), fg=TEXT,
                     bg=PURPLE if primary else PANEL_2,
                     activeforeground=TEXT, activebackground=PURPLE_2 if primary else BORDER,
                     relief="flat", bd=0, padx=14, pady=10, cursor="hand2")


class Preview:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("경희 타이머 · 데스크톱 UI 프리뷰")
        self.root.geometry("940x610")
        self.root.minsize(900, 580)
        self.root.configure(bg=BG)
        self.photos = []
        self.build()

    def load_asset(self, name: str, max_size: tuple[int, int], bg: str) -> ImageTk.PhotoImage | None:
        path = ASSETS / name
        if not path.exists():
            return None
        with Image.open(path) as src:
            rgba = src.convert("RGBA")
            rgba.thumbnail(max_size, Image.Resampling.LANCZOS)
            canvas = Image.new("RGBA", rgba.size, bg)
            canvas.alpha_composite(rgba)
            result = ImageTk.PhotoImage(canvas.convert("RGB"))
            self.photos.append(result)
            return result

    def build(self):
        header = tk.Frame(self.root, bg=BG, height=58)
        header.pack(fill="x", padx=20, pady=(14, 4))
        header.pack_propagate(False)

        avatar = tk.Label(header, bg=BG, bd=0)
        avatar.pack(side="left", padx=(0, 9))
        photo = self.load_asset("profile_kyunghee.png", (34, 34), BG)
        if photo:
            avatar.configure(image=photo)
        else:
            label(header, "●", size=14, fg=PURPLE).pack(side="left", padx=(0, 6))

        label(header, "경희 타이머", size=12, weight="bold").pack(side="left")
        label(header, "●", size=9, fg=GREEN).pack(side="left", padx=(10, 4))
        label(header, "집중 중", size=9, fg=MUTED).pack(side="left")
        button(header, "설정").pack(side="right")

        body = tk.Frame(self.root, bg=BG)
        body.pack(fill="both", expand=True, padx=20, pady=(4, 18))
        body.grid_columnconfigure(0, weight=10, uniform="main")
        body.grid_columnconfigure(1, weight=11, uniform="main")
        body.grid_rowconfigure(0, weight=1)

        left = card(body)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        left.grid_columnconfigure(0, weight=1)

        top = tk.Frame(left, bg=PANEL)
        top.pack(fill="x", padx=22, pady=(20, 8))
        label(top, "연속 집중 시간", size=10, weight="bold", fg=MUTED, bg=PANEL).pack(anchor="w")
        label(top, "02:47:32", size=32, weight="bold", bg=PANEL).pack(anchor="w", pady=(5, 0))
        label(top, "오늘 목표: 09:00:00", size=9, fg=MUTED, bg=PANEL).pack(anchor="w", pady=(2, 0))

        progress_wrap = tk.Frame(left, bg=PANEL)
        progress_wrap.pack(fill="x", padx=22, pady=(10, 14))
        progress = tk.Canvas(progress_wrap, height=9, bg=PANEL_2, highlightthickness=0, bd=0)
        progress.pack(fill="x")
        progress.create_rectangle(0, 0, 96, 9, fill=PURPLE, outline="")
        label(progress_wrap, "30%", size=9, fg=MUTED, bg=PANEL).pack(anchor="e", pady=(5, 0))

        metrics = tk.Frame(left, bg=PANEL)
        metrics.pack(fill="x", padx=22, pady=(0, 14))
        for i in range(3):
            metrics.grid_columnconfigure(i, weight=1)
        for i, (caption, value) in enumerate((("오늘 실사용", "02:47"), ("총 사용시간", "05:12"), ("남은 시간", "06:12"))):
            m = card(metrics, bg=PANEL_2)
            m.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 4, 0 if i == 2 else 4))
            label(m, caption, size=8, fg=MUTED, bg=PANEL_2).pack(pady=(9, 2))
            label(m, value, size=12, weight="bold", bg=PANEL_2).pack(pady=(0, 9))

        actions = tk.Frame(left, bg=PANEL)
        actions.pack(fill="x", padx=22, pady=(0, 12))
        button(actions, "자리비움 시작", primary=True).pack(side="left", fill="x", expand=True, padx=(0, 5))
        button(actions, "오늘 기록").pack(side="left", fill="x", expand=True, padx=(5, 0))

        footer = card(left, bg=PANEL_2)
        footer.pack(fill="x", padx=22, pady=(0, 20))
        label(footer, "♧  다음 휴식 알림: 01:12:27 후", size=9, fg=MUTED, bg=PANEL_2).pack(side="left", padx=12, pady=10)

        right = card(body)
        right.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        right.grid_rowconfigure(0, weight=1)
        right.grid_columnconfigure(0, weight=1)

        hero = tk.Label(right, bg=PANEL, bd=0, anchor="s")
        hero.grid(row=0, column=0, sticky="nsew", padx=6, pady=(4, 0))
        photo = self.load_asset("main_kyunghee.png", (430, 455), PANEL)
        if photo:
            hero.configure(image=photo)
        else:
            hero.configure(text="main_kyunghee.png\n에셋을 설치하면 여기에 표시됩니다.", fg=MUTED,
                           font=("Malgun Gothic", 10), justify="center")

        bubble = tk.Frame(right, bg="#211644", highlightthickness=1, highlightbackground="#523A8E")
        bubble.grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 16))
        label(bubble, "지금 집중이 정말 좋아 보여요!", size=11, weight="bold", bg="#211644").pack(anchor="w", padx=14, pady=(10, 2))
        label(bubble, "화이팅, 오빠!", size=10, fg="#D8CBFF", bg="#211644").pack(anchor="w", padx=14, pady=(0, 10))

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    Preview().run()
