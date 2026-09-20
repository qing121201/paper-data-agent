"""In-app slide preview and per-page conversational revision."""

from pathlib import Path
import os
import tkinter as tk
from tkinter import messagebox, ttk

from ..config import llm_ready
from ..llm import LLMConfig, OpenAICompatibleClient
from ..presentation.workspace import load_spec, render_preview, revise_slide


class PresentationPanel:
    def __init__(self, app, parent):
        self.app = app
        self.parent = parent
        self.paths = []
        self.images = []
        self.spec_path = None
        self.page = 0
        self.photo = None
        bar = ttk.Frame(parent)
        bar.pack(fill="x", pady=(0, 8))
        ttk.Label(bar, text="文稿版本").pack(side="left")
        self.versions = ttk.Combobox(bar, state="readonly", width=45)
        self.versions.pack(side="left", padx=8, fill="x", expand=True)
        self.versions.bind("<<ComboboxSelected>>", self.open_selected)
        ttk.Button(bar, text="刷新", command=self.refresh).pack(side="left")
        ttk.Button(bar, text="打开 PPTX", command=self.open_file).pack(side="left", padx=6)
        self.status = ttk.Label(parent, text="选择当前论文库中生成的文稿，即可预览和逐页修改。")
        self.status.pack(fill="x", pady=(0, 6))
        body = ttk.Frame(parent)
        body.pack(fill="both", expand=True)
        self.pages = tk.Listbox(body, width=24, exportselection=False, font=("Microsoft YaHei UI", 9))
        self.pages.pack(side="left", fill="y", padx=(0, 10))
        self.pages.bind("<<ListboxSelect>>", self.choose_page)
        self.preview = tk.Canvas(body, background="#E7EBF0", highlightthickness=0)
        self.preview.pack(side="left", fill="both", expand=True)
        self.preview.bind("<Configure>", lambda event: self.draw())
        self.page_label = ttk.Label(parent, text="尚未选择页面")
        self.page_label.pack(anchor="w", pady=(8, 4))
        edit = ttk.Frame(parent)
        edit.pack(fill="x")
        self.instruction = tk.Text(edit, height=3, wrap="word", font=("Microsoft YaHei UI", 10))
        self.instruction.pack(side="left", fill="x", expand=True)
        ttk.Button(edit, text="修改选中页\n保留旧版本", command=self.revise).pack(side="right", padx=(8, 0))
        ttk.Label(
            parent,
            text="例如：加入本论文的方法原图，左文右图；或换成实验对比图并解释结论。修改会保留旧版本。",
            wraplength=850,
        ).pack(anchor="w", pady=(4, 0))

    def refresh(self, select=None):
        if self.app.busy:
            return
        library = self.app.current_library
        self.paths = sorted(
            (library.path / "outputs").glob("*/presentation_spec.json"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        ) if library else []
        self.versions["values"] = [path.parent.name for path in self.paths]
        if not self.paths:
            self.versions.set("")
            self.spec_path = None
            self.images = []
            self.pages.delete(0, "end")
            self.preview.delete("all")
            self.page_label.configure(text="尚无生成的 PPT")
            return
        chosen = Path(select) if select else self.spec_path
        self.versions.current(self.paths.index(chosen) if chosen in self.paths else 0)
        self.open_selected()

    def open_selected(self, event=None):
        if self.app.busy or self.versions.current() < 0:
            return
        path = self.paths[self.versions.current()]

        def done(images):
            self.spec_path = path
            self.images = images
            spec = load_spec(path)
            titles = [spec.get("title", "封面")] + [item.get("title", "") for item in spec["slides"]]
            self.pages.delete(0, "end")
            for index, title in enumerate(titles, start=1):
                self.pages.insert("end", f"{index}. {title}")
            self.page = min(self.page, len(images) - 1)
            self.pages.selection_set(self.page)
            self.draw()
            self.status.configure(text=f"共 {len(images)} 页。选中一页后，在下方输入修改要求。")

        self.app._run_background(lambda: render_preview(path), done, self.status, "正在生成逐页预览……")

    def choose_page(self, event=None):
        selection = self.pages.curselection()
        if selection:
            self.page = selection[0]
            self.draw()

    def draw(self):
        if not self.images or self.page >= len(self.images):
            return
        from PIL import Image, ImageTk

        width = max(20, self.preview.winfo_width() - 20)
        height = max(20, self.preview.winfo_height() - 20)
        with Image.open(self.images[self.page]) as source:
            image = source.copy()
        image.thumbnail((width, height), Image.Resampling.LANCZOS)
        self.photo = ImageTk.PhotoImage(image)
        self.preview.delete("all")
        self.preview.create_image(
            self.preview.winfo_width() / 2,
            self.preview.winfo_height() / 2,
            image=self.photo,
        )
        self.page_label.configure(text=f"正在查看第 {self.page + 1} / {len(self.images)} 页；修改只作用于这一页")

    def open_file(self):
        if self.spec_path:
            os.startfile(str(self.spec_path.parent / "paper-presentation.pptx"))

    def revise(self):
        if self.app.busy or not self.spec_path:
            return
        instruction = self.instruction.get("1.0", "end").strip()
        if not instruction:
            return
        config = LLMConfig.from_env()
        if not llm_ready(config):
            messagebox.showinfo("模型未配置", "请先在模型设置中配置 API。")
            return
        path, page = self.spec_path, self.page

        def task():
            return revise_slide(path, page, instruction, OpenAICompatibleClient(config))

        def done(new_path):
            self.instruction.delete("1.0", "end")
            self.page = page
            self.refresh(select=new_path)

        self.app._run_background(task, done, self.status, f"正在修改第 {page + 1} 页并保存新版本……")
