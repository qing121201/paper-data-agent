from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
import json
import math
import os
from pathlib import Path
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
from tkinter.scrolledtext import ScrolledText
import webbrowser

from .config import apply_config, llm_ready, load_local_config, save_config
from .core import PaperAgent, PaperIndex
from .library import LibraryManager, PaperLibrary
from .llm import LLMConfig, LLMError, OpenAICompatibleClient
from .markdown_render import inline_segments, parse_markdown_blocks
from .providers import PROVIDER_BY_NAME, PROVIDER_PRESETS, detect_provider
from .skills import SkillCatalog
from .ui_settings import DEFAULT_THEME, load_ui_settings, save_ui_settings
from .workflow import ResearchWorkflowAgent
from .presentation_ui import PresentationPanel


PROJECT_ROOT = Path(__file__).resolve().parent.parent
LIBRARIES_ROOT = PROJECT_ROOT / "libraries"
CONFIG_PATH = PROJECT_ROOT / ".env"
UI_SETTINGS_PATH = PROJECT_ROOT / "config" / "ui.json"


THEMES = {
    "原始浅色": {
        "native": True,
        "bg": "#F0F0F0", "surface": "#F0F0F0", "field": "#FFFFFF",
        "text": "#202020", "muted": "#666666", "border": "#C8C8C8",
        "accent": "#176B9B", "accent_hover": "#12577F",
        "success": "#176B3A", "warning": "#A04400",
    },
    "学术蓝": {
        "bg": "#EAF0F7", "surface": "#F8FBFF", "field": "#FFFFFF",
        "text": "#1D2A3A", "muted": "#607083", "border": "#C5D3E3",
        "accent": "#2867A7", "accent_hover": "#1F548A",
        "success": "#18734B", "warning": "#A35B00",
    },
    "纸张暖色": {
        "bg": "#F2EDE3", "surface": "#FFFDF8", "field": "#FFFEFA",
        "text": "#352F28", "muted": "#776C5E", "border": "#D7CDBC",
        "accent": "#9A5B35", "accent_hover": "#7B4729",
        "success": "#507044", "warning": "#A35C19",
    },
    "深色夜读": {
        "bg": "#171C24", "surface": "#222A35", "field": "#11161D",
        "text": "#E6EDF5", "muted": "#AAB6C4", "border": "#3A4656",
        "accent": "#4D91D9", "accent_hover": "#69A8E8",
        "success": "#67C895", "warning": "#F2B66D",
    },
}


class PaperAgentGUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("论文 Data Agent")
        self.root.geometry("1120x780")
        self.root.minsize(920, 650)
        self.manager = LibraryManager(LIBRARIES_ROOT)
        self.catalog = SkillCatalog()
        self.current_library: PaperLibrary | None = None
        self.library_lookup: dict[str, str] = {}
        self.histories: dict[str, list[dict[str, str]]] = {}
        self.busy = False
        self._table_cells: list[tuple[tk.Frame, tk.Widget, bool]] = []
        self._embedded_widgets: list[tk.Widget] = []
        self.ui_settings = load_ui_settings(UI_SETTINGS_PATH)
        if self.ui_settings.get("theme") not in THEMES:
            self.ui_settings["theme"] = DEFAULT_THEME
        self.theme_name = self.ui_settings["theme"]

        self._configure_style()
        self._build_header()
        self._build_tabs()
        self.root.update_idletasks()
        self._style_text_widgets()
        self._refresh_libraries()
        self._refresh_api_status()

    def _configure_style(self) -> None:
        self.style = ttk.Style()
        self._apply_theme(self.theme_name, persist=False)

    def _apply_theme(self, name: str, persist: bool = True) -> None:
        if name not in THEMES:
            name = DEFAULT_THEME
        palette = THEMES[name]
        self.theme_name = name
        target = "vista" if palette.get("native") and "vista" in self.style.theme_names() else "clam"
        self.style.theme_use(target)
        self.root.configure(background=palette["bg"])
        self.style.configure(".", font=("Microsoft YaHei UI", 9), background=palette["bg"], foreground=palette["text"])
        self.style.configure("TFrame", background=palette["surface"])
        self.style.configure("Header.TFrame", background=palette["surface"])
        self.style.configure("TLabel", background=palette["surface"], foreground=palette["text"])
        self.style.configure("Header.TLabel", background=palette["surface"], foreground=palette["text"])
        self.style.configure("Title.TLabel", background=palette["surface"], foreground=palette["accent"], font=("Microsoft YaHei UI", 20, "bold"))
        self.style.configure("Subtitle.TLabel", background=palette["surface"], foreground=palette["muted"], font=("Microsoft YaHei UI", 10))
        self.style.configure("Heading.TLabel", font=("Microsoft YaHei UI", 11, "bold"))
        self.style.configure("Muted.TLabel", foreground=palette["muted"])
        self.style.configure("Success.TLabel", background=palette["surface"], foreground=palette["success"], font=("Microsoft YaHei UI", 9, "bold"))
        self.style.configure("Warning.TLabel", background=palette["surface"], foreground=palette["warning"], font=("Microsoft YaHei UI", 9, "bold"))
        self.style.configure("TButton", padding=(11, 6), background=palette["surface"], foreground=palette["text"])
        self.style.map("TButton", background=[("active", palette["border"])])
        self.style.configure("Accent.TButton", background=palette["accent"], foreground="#FFFFFF", padding=(12, 7), font=("Microsoft YaHei UI", 9, "bold"))
        self.style.map("Accent.TButton", background=[("active", palette["accent_hover"]), ("pressed", palette["accent_hover"])], foreground=[("disabled", palette["muted"])])
        self.style.configure("TEntry", fieldbackground=palette["field"], foreground=palette["text"], padding=4)
        self.style.configure("TCombobox", fieldbackground=palette["field"], foreground=palette["text"], arrowcolor=palette["text"], padding=4)
        self.style.map("TCombobox", fieldbackground=[("readonly", palette["field"])], foreground=[("readonly", palette["text"])])
        self.style.configure("TLabelframe", background=palette["surface"], bordercolor=palette["border"], relief="solid")
        self.style.configure("TLabelframe.Label", background=palette["surface"], foreground=palette["accent"], font=("Microsoft YaHei UI", 10, "bold"))
        self.style.configure("TNotebook", background=palette["bg"], borderwidth=0)
        self.style.configure(
            "TNotebook.Tab",
            background=palette["bg"],
            foreground=palette["muted"],
            padding=(18, 9),
            font=("Microsoft YaHei UI", 10, "bold"),
        )
        self.style.map(
            "TNotebook.Tab",
            background=[("selected", palette["surface"])],
            foreground=[("selected", palette["accent"])],
            padding=[("selected", (24, 13)), ("!selected", (18, 9))],
        )
        self.style.configure("Treeview", background=palette["field"], fieldbackground=palette["field"], foreground=palette["text"], rowheight=27, bordercolor=palette["border"])
        self.style.configure("Treeview.Heading", background=palette["surface"], foreground=palette["text"], font=("Microsoft YaHei UI", 9, "bold"))
        self.style.map("Treeview", background=[("selected", palette["accent"])], foreground=[("selected", "#FFFFFF")])
        self.style.configure("TCheckbutton", background=palette["surface"], foreground=palette["text"])
        self.style.configure(
            "Chat.Horizontal.TProgressbar",
            troughcolor=palette["border"],
            background=palette["accent"],
            bordercolor=palette["border"],
            lightcolor=palette["accent"],
            darkcolor=palette["accent"],
        )
        if hasattr(self, "theme_var"):
            self.theme_var.set(name)
        if hasattr(self, "chat_log"):
            self._style_text_widgets()
        if persist:
            self.ui_settings["theme"] = name
            save_ui_settings(UI_SETTINGS_PATH, self.ui_settings)

    def _style_text_widgets(self) -> None:
        palette = THEMES[self.theme_name]
        common = {
            "background": palette["field"], "foreground": palette["text"],
            "insertbackground": palette["text"], "selectbackground": palette["accent"],
            "highlightbackground": palette["border"], "highlightcolor": palette["accent"],
        }
        self.chat_log.configure(**common)
        self.chat_input.configure(**common)
        self.help_text.configure(**common)
        self.chat_log.tag_configure("user", foreground=palette["accent"], font=("Microsoft YaHei UI", 10, "bold"))
        self.chat_log.tag_configure("agent", foreground=palette["success"], font=("Microsoft YaHei UI", 10, "bold"))
        self.chat_log.tag_configure("trace", foreground=palette["muted"], font=("Microsoft YaHei UI", 9))
        self.chat_log.tag_configure("md_h1", foreground=palette["accent"], font=("Microsoft YaHei UI", 15, "bold"), spacing1=8, spacing3=4)
        self.chat_log.tag_configure("md_h2", foreground=palette["text"], font=("Microsoft YaHei UI", 12, "bold"), spacing1=7, spacing3=3)
        self.chat_log.tag_configure("md_h3", foreground=palette["text"], font=("Microsoft YaHei UI", 11, "bold"), spacing1=5, spacing3=2)
        self.chat_log.tag_configure("md_bold", foreground=palette["text"], font=("Microsoft YaHei UI", 10, "bold"))
        self.chat_log.tag_configure("md_italic", foreground=palette["text"], font=("Microsoft YaHei UI", 10, "italic"))
        self.chat_log.tag_configure("md_code", foreground=palette["accent"], background=palette["bg"], font=("Consolas", 9))
        self.chat_log.tag_configure("md_quote", foreground=palette["muted"], lmargin1=18, lmargin2=18)
        self.chat_log.tag_configure("md_code_block", foreground=palette["text"], background=palette["bg"], font=("Consolas", 9), lmargin1=12, lmargin2=12, spacing1=5, spacing3=5)
        for frame, label, is_header in self._table_cells:
            frame.configure(background=palette["border"])
            label.configure(
                background=palette["accent"] if is_header else palette["field"],
                foreground="#FFFFFF" if is_header else palette["text"],
            )

    def _theme_changed(self, _event=None) -> None:
        self._apply_theme(self.theme_var.get())

    def _build_header(self) -> None:
        header = ttk.Frame(self.root, padding=(22, 17, 22, 14), style="Header.TFrame")
        header.pack(fill="x")
        ttk.Label(header, text="论文 Data Agent", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(
            header,
            text="导入任意本地论文或公开网址，然后直接向 Agent 提问",
            style="Subtitle.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(3, 0))
        theme_box = ttk.Frame(header, style="Header.TFrame")
        theme_box.grid(row=0, column=1, rowspan=2, padx=(12, 20))
        ttk.Label(theme_box, text="皮肤", style="Header.TLabel").pack(side="left", padx=(0, 6))
        self.theme_var = tk.StringVar(value=self.theme_name)
        theme_combo = ttk.Combobox(theme_box, textvariable=self.theme_var, state="readonly", values=tuple(THEMES), width=10)
        theme_combo.pack(side="left")
        theme_combo.bind("<<ComboboxSelected>>", self._theme_changed)
        self.api_status = ttk.Label(header, text="", style="Warning.TLabel")
        self.api_status.grid(row=0, column=2, rowspan=2, sticky="e")
        ttk.Button(header, text="模型设置", command=self._open_api_dialog, style="Accent.TButton").grid(
            row=0, column=3, rowspan=2, padx=(12, 0)
        )
        header.columnconfigure(0, weight=1)

        bar = ttk.Frame(self.root, padding=(18, 0, 18, 10))
        bar.pack(fill="x")
        ttk.Label(bar, text="当前论文库：", style="Heading.TLabel").pack(side="left")
        self.library_combo = ttk.Combobox(bar, state="readonly", width=42)
        self.library_combo.pack(side="left", padx=(8, 8))
        self.library_combo.bind("<<ComboboxSelected>>", self._select_library)
        ttk.Button(bar, text="新建论文库", command=self._create_library, style="Accent.TButton").pack(side="left", padx=4)
        ttk.Button(bar, text="打开库目录", command=self._open_library_folder).pack(side="left", padx=4)
        self.library_status = ttk.Label(bar, text="尚未选择论文库")
        self.library_status.pack(side="right")

    def _build_tabs(self) -> None:
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=18, pady=(0, 14))
        self.import_tab = ttk.Frame(self.notebook, padding=16)
        self.chat_tab = ttk.Frame(self.notebook, padding=16)
        self.help_tab = ttk.Frame(self.notebook, padding=16)
        self.notebook.add(self.import_tab, text="论文导入")
        self.notebook.add(self.chat_tab, text="与 Agent 对话")
        self.ppt_tab = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(self.ppt_tab, text="PPT 预览与修改")
        self.ppt_panel = PresentationPanel(self, self.ppt_tab)
        self.notebook.bind("<<NotebookTabChanged>>", self._tab_changed)
        self.notebook.add(self.help_tab, text="说明")
        self._build_import_tab()
        self._build_chat_tab()
        self._build_help_tab()

    def _tab_changed(self, event=None):
        if hasattr(self, "ppt_panel") and self.notebook.select() == str(self.ppt_tab):
            self.ppt_panel.refresh()

    def _build_import_tab(self) -> None:
        local = ttk.LabelFrame(self.import_tab, text="从本地文件夹导入", padding=12)
        local.pack(fill="x")
        ttk.Label(local, text="文件夹地址：").grid(row=0, column=0, sticky="w")
        self.folder_var = tk.StringVar()
        ttk.Entry(local, textvariable=self.folder_var).grid(row=0, column=1, sticky="ew", padx=8)
        ttk.Button(local, text="浏览选择", command=self._browse_folder).grid(row=0, column=2, padx=4)
        ttk.Button(local, text="导入并建库", command=self._import_folder, style="Accent.TButton").grid(row=0, column=3, padx=(4, 0))
        ttk.Label(local, text="会递归查找子文件夹中的 PDF；本地原文件不会被复制或修改。").grid(
            row=1, column=1, columnspan=3, sticky="w", pady=(8, 0)
        )
        local.columnconfigure(1, weight=1)

        web = ttk.LabelFrame(self.import_tab, text="从公开论文网址导入", padding=12)
        web.pack(fill="x", pady=(14, 0))
        ttk.Label(web, text="论文网址：").grid(row=0, column=0, sticky="w")
        self.url_var = tk.StringVar()
        ttk.Entry(web, textvariable=self.url_var).grid(row=0, column=1, sticky="ew", padx=8)
        ttk.Button(web, text="读取并加入论文库", command=self._import_url, style="Accent.TButton").grid(row=0, column=2)
        ttk.Label(web, text="支持公开 PDF 直链及包含 PDF 链接的论文页面；不绕过登录、付费墙或验证码。").grid(
            row=1, column=1, columnspan=2, sticky="w", pady=(8, 0)
        )
        web.columnconfigure(1, weight=1)

        listing = ttk.LabelFrame(self.import_tab, text="当前论文库内容", padding=10)
        listing.pack(fill="both", expand=True, pady=(14, 0))
        actions = ttk.Frame(listing)
        actions.pack(side="bottom", fill="x", pady=(8, 0))
        ttk.Button(actions, text="复制论文标题", command=self._copy_selected_title).pack(side="left")
        ttk.Button(actions, text="复制本地路径", command=self._copy_selected_path).pack(side="left", padx=(8, 0))
        ttk.Button(actions, text="复制整行", command=self._copy_selected_row).pack(side="left", padx=(8, 0))
        ttk.Button(actions, text="建立/更新向量索引", command=self._build_vector_index).pack(side="left", padx=(16, 0))
        ttk.Button(actions, text="从论文库移除", command=self._remove_selected_paper).pack(side="right")
        columns = ("title", "type", "path", "source")
        self.paper_tree = ttk.Treeview(listing, columns=columns, show="headings", selectmode="browse")
        self.paper_tree.heading("title", text="论文")
        self.paper_tree.heading("type", text="来源类型")
        self.paper_tree.heading("path", text="本地文件路径")
        self.paper_tree.heading("source", text="原始网址")
        self.paper_tree.column("title", width=300, anchor="w")
        self.paper_tree.column("type", width=80, anchor="center")
        self.paper_tree.column("path", width=390, anchor="w")
        self.paper_tree.column("source", width=300, anchor="w")
        scrollbar = ttk.Scrollbar(listing, orient="vertical", command=self.paper_tree.yview)
        self.paper_tree.configure(yscrollcommand=scrollbar.set)
        self.paper_tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.paper_tree.bind("<Double-1>", self._open_selected_source)
        self.paper_tree.bind("<Control-c>", self._copy_selected_row)
        self.paper_tree.bind("<Button-3>", self._show_paper_menu)
        self.paper_menu = tk.Menu(self.root, tearoff=False)
        self.paper_menu.add_command(label="复制论文标题", command=self._copy_selected_title)
        self.paper_menu.add_command(label="复制本地路径", command=self._copy_selected_path)
        self.paper_menu.add_command(label="复制整行", command=self._copy_selected_row)
        self.paper_menu.add_separator()
        self.paper_menu.add_command(label="从论文库移除", command=self._remove_selected_paper)
        self.import_message = ttk.Label(self.import_tab, text="就绪")
        self.import_message.pack(fill="x", pady=(8, 0))

    def _build_chat_tab(self) -> None:
        top = ttk.Frame(self.chat_tab)
        top.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ttk.Label(top, text="直接描述任务，Agent 会自己选择工具、检索词和科研 Skill。", style="Heading.TLabel").grid(
            row=0, column=0, columnspan=4, sticky="w", pady=(0, 6)
        )
        self.chat_progress_var = tk.DoubleVar(value=0)
        self.chat_progress = ttk.Progressbar(
            top,
            variable=self.chat_progress_var,
            maximum=100,
            length=170,
            mode="determinate",
            style="Chat.Horizontal.TProgressbar",
        )
        self.chat_progress.grid(row=1, column=1, sticky="e", padx=(10, 8))
        self.chat_status = ttk.Label(top, text="就绪", width=22, anchor="e")
        self.chat_status.grid(row=1, column=2, sticky="e", padx=(0, 8))
        self.clear_chat_button = ttk.Button(top, text="清空当前对话", command=self._clear_current_chat)
        self.clear_chat_button.grid(row=1, column=3, sticky="e")
        top.columnconfigure(0, weight=1)
        scenarios = ttk.LabelFrame(self.chat_tab, text="常用科研场景（点击后可继续修改任务）", padding=8)
        scenarios.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        scenario_items = [
            ("搜索并导入", "在线搜索近五年与【研究主题】相关的论文，扩大候选范围，最终成功下载5篇相关且引用较高的公开论文并加入当前论文库。"),
            ("全库脉络", "我想梳理当前论文库的完整研究脉络。请先评估论文数量、主题范围和需要的阅读深度，给出推荐方案并与我确认；确认后再阅读、整理研究问题、方法分支、发展脉络和未解决问题。"),
            ("单篇精读", "精读【论文标题】，生成研究问题、方法、数据、主要结果、局限性和可复用证据卡，并标注PDF页码。"),
            ("写文献综述", "我想围绕【主题】写文献综述。请先和我确认论文范围、时间范围、阅读深度和成稿长度；给出你推荐的阅读方案，确认后再检索证据、阅读全文或核心论文，并写作和审查。"),
            ("组会 PPT", "基于当前论文库制作10页组会PPT，至少包含3张原文图和2张有来源的自绘图，生成后供逐页修改。"),
            ("核验引用", "核验当前论文库中与【结论】有关的论文标题、作者、年份、DOI和原文证据页，列出不确定项。"),
        ]
        for index, (label, prompt) in enumerate(scenario_items):
            ttk.Button(scenarios, text=label, command=lambda value=prompt: self._choose_scenario(value)).grid(
                row=index // 3, column=index % 3, sticky="ew", padx=4, pady=3)
        for column in range(3):
            scenarios.columnconfigure(column, weight=1)
        self.chat_log = ScrolledText(
            self.chat_tab,
            wrap="word",
            state="disabled",
            font=("Microsoft YaHei UI", 10),
            padx=12,
            pady=10,
            height=12,
        )
        self.chat_log.grid(row=2, column=0, sticky="nsew")
        self.chat_log.tag_configure("user", foreground="#1557A0", font=("Microsoft YaHei UI", 10, "bold"))
        self.chat_log.tag_configure("agent", foreground="#176B3A", font=("Microsoft YaHei UI", 10, "bold"))
        self.chat_log.tag_configure("trace", foreground="#666666", font=("Microsoft YaHei UI", 9))

        composer = ttk.Frame(self.chat_tab)
        composer.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        self.chat_input = tk.Text(composer, height=3, wrap="word", font=("Microsoft YaHei UI", 10))
        self.chat_input.pack(side="left", fill="x", expand=True)
        self.chat_input.bind("<Control-Return>", lambda _event: self._send_chat())
        ttk.Button(composer, text="发送\nCtrl+Enter", command=self._send_chat, style="Accent.TButton").pack(
            side="right", fill="y", padx=(10, 0)
        )
        self.chat_tab.columnconfigure(0, weight=1)
        self.chat_tab.rowconfigure(2, weight=1, minsize=180)
        self._append_chat(
            "Agent",
            "欢迎使用论文 Data Agent。请先建立或选择论文库并导入论文，然后直接告诉我你希望完成的任务。",
            "agent",
        )

    def _choose_scenario(self, prompt: str) -> None:
        self.chat_input.delete("1.0", "end")
        self.chat_input.insert("1.0", prompt)
        self.chat_input.focus_set()

    def _build_help_tab(self) -> None:
        self.help_text = ScrolledText(self.help_tab, wrap="word", font=("Microsoft YaHei UI", 10), padx=14, pady=12)
        self.help_text.pack(fill="both", expand=True)
        self.help_text.insert(
            "1.0",
            "使用顺序\n\n"
            "1. 点击“新建论文库”，每个课题建议使用一个独立论文库。\n"
            "2. 在“论文导入”页粘贴本地文件夹地址，或点击“浏览选择”。\n"
            "3. 也可以粘贴公开 PDF 或论文网页网址，程序会下载并缓存公开 PDF。\n"
            "4. 可点击“建立/更新向量索引”，首次下载公开多语言 Embedding 模型，之后使用 BM25+向量混合检索。\n"
            "5. 点击右上角“模型设置”，可直接选择 DeepSeek、Kimi、千问、智谱等预设。\n"
            "6. 进入“与 Agent 对话”，直接描述任务。\n\n"
            "数据位置\n\n"
            f"所有论文库保存在：{LIBRARIES_ROOT}\n"
            "每个论文库独立包含元数据、索引、网页下载缓存和对话记录。\n"
            "本地 PDF 不会被修改；网页 PDF 会缓存到对应论文库。\n\n"
            "能力边界\n\n"
            "程序只读取公开网页，不绕过登录、付费墙、验证码或网站权限。"
            "模型回答应以显示的本地路径、PDF 页码或原始网址为依据。",
        )
        self.help_text.configure(state="disabled")

    def _run_background(self, task, success, label: ttk.Label, working_text: str) -> None:
        if self.busy:
            messagebox.showinfo("请稍候", "当前已有任务正在运行。")
            return
        self.busy = True
        label.configure(text=working_text)

        def runner() -> None:
            try:
                result = task()
            except Exception as exc:
                self.root.after(0, lambda error=exc: self._background_failed(label, error))
            else:
                self.root.after(0, lambda: self._background_done(label, success, result))

        threading.Thread(target=runner, daemon=True).start()

    def _background_failed(self, label: ttk.Label, exc: Exception) -> None:
        self.busy = False
        label.configure(text="失败")
        if label is getattr(self, "chat_status", None):
            self.chat_progress_var.set(0)
        suffix = ""
        if label is getattr(self, "chat_status", None) and self.current_library and (self.current_library.sessions_path / "in_progress.json").is_file():
            suffix = "\n\n当前任务进度已保存。重新启动后输入“继续上次任务”即可接着处理。"
        messagebox.showerror("操作失败", str(exc) + suffix)

    def _background_done(self, label: ttk.Label, success, result) -> None:
        self.busy = False
        if label is getattr(self, "chat_status", None):
            self._set_chat_progress(100, "完成")
        else:
            label.configure(text="完成")
        success(result)

    def _refresh_libraries(self, select_id: str | None = None) -> None:
        infos = self.manager.list()
        self.library_lookup = {f"{item.name}  [{item.library_id}]": item.library_id for item in infos}
        values = list(self.library_lookup)
        self.library_combo["values"] = values
        if not values:
            self.library_combo.set("")
            self.current_library = None
            self._refresh_papers()
            return
        selected_display = next(
            (display for display, library_id in self.library_lookup.items() if library_id == select_id),
            values[0],
        )
        self.library_combo.set(selected_display)
        self._open_library(self.library_lookup[selected_display])

    def _create_library(self) -> None:
        if self.busy:
            messagebox.showinfo("任务进行中", "请等待当前任务完成后再新建论文库。")
            return
        name = simpledialog.askstring("新建论文库", "请输入论文库名称：", parent=self.root)
        if name is None or not name.strip():
            return
        try:
            library = self.manager.create(name)
        except (OSError, ValueError) as exc:
            messagebox.showerror("创建失败", str(exc))
            return
        self._refresh_libraries(library.info.library_id)
        self.notebook.select(self.import_tab)

    def _select_library(self, _event=None) -> None:
        if self.busy:
            if self.current_library:
                self.library_combo.set(next(
                    display for display, library_id in self.library_lookup.items()
                    if library_id == self.current_library.info.library_id
                ))
            return
        library_id = self.library_lookup.get(self.library_combo.get())
        if library_id:
            self._open_library(library_id)

    def _open_library(self, library_id: str) -> None:
        self.current_library = self.manager.open(library_id)
        self.library_status.configure(text=self._library_status_text(self.current_library))
        self._refresh_papers()
        self._restore_session(self.current_library)
        if hasattr(self, "ppt_panel"):
            self.ppt_panel.spec_path = None
            if self.notebook.select() == str(self.ppt_tab):
                self.ppt_panel.refresh()

    def _restore_session(self, library: PaperLibrary) -> None:
        if library.info.library_id not in self.histories:
            latest = library.sessions_path / "latest.json"
            try:
                payload = json.loads(latest.read_text(encoding="utf-8")) if latest.is_file() else {}
                messages = payload.get("messages", [])
                self.histories[library.info.library_id] = messages if isinstance(messages, list) else []
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                self.histories[library.info.library_id] = []
        self._clear_chat_log()
        self._set_chat_progress(0, "就绪")
        for item in self.histories[library.info.library_id][-8:]:
            role = item.get("role")
            self._append_chat("你" if role == "user" else "Agent", str(item.get("content", "")), "user" if role == "user" else "agent")
        checkpoint = library.sessions_path / "in_progress.json"
        if checkpoint.is_file():
            try:
                state = json.loads(checkpoint.read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                return
            if state.get("status") == "interrupted":
                task = str(state.get("query", ""))[:180]
                self._append_chat("恢复提示", f"上次任务在模型调用阶段中断，进度已保存：{task}\n输入“继续上次任务”可继续。", "trace")

    def _set_chat_progress(self, value: int, text: str) -> None:
        value = max(0, min(100, int(value)))
        self.chat_progress_var.set(value)
        self.chat_status.configure(text=text)

    def _queue_chat_progress(self, value: int, text: str) -> None:
        self.root.after(0, lambda: self._set_chat_progress(value, text))

    def _queue_step(self, event: dict) -> None:
        labels = {"running": "正在执行", "complete": "已完成", "failed": "失败"}
        text = f"第 {event['number']} 步：{event['tool']} · {labels.get(event['status'], event['status'])}"
        self.root.after(0, lambda: self.chat_status.configure(text=text))

    def _clear_current_chat(self) -> None:
        library = self._require_library()
        if not library:
            return
        if self.busy:
            messagebox.showinfo("任务进行中", "请等待当前任务完成后再清空对话。")
            return
        confirmed = messagebox.askyesno(
            "清空当前对话",
            "这会清空当前论文库的聊天显示和后续对话上下文。\n\n"
            "论文、索引和已生成文件不会被删除；旧会话会移入 sessions/archive 以便恢复。\n\n"
            "确定继续吗？",
            parent=self.root,
        )
        if not confirmed:
            return
        library.clear_chat_session()
        self.histories[library.info.library_id] = []
        self._clear_chat_log()
        self._set_chat_progress(0, "就绪")
        self._append_chat(
            "Agent",
            "当前对话已清空。论文库内容保持不变，你可以从一个新问题开始。",
            "agent",
        )

    def _refresh_papers(self) -> None:
        for item in self.paper_tree.get_children():
            self.paper_tree.delete(item)
        if not self.current_library:
            self.library_status.configure(text="尚未选择论文库")
            return
        records = self.current_library.records()
        for record in records:
            source = record.source if record.source_type == "web" else ""
            self.paper_tree.insert(
                "", "end", iid=record.paper_id,
                values=(record.title, "网页" if record.source_type == "web" else "本地", record.local_path, source),
            )
        self.library_status.configure(text=self._library_status_text(self.current_library))

    @staticmethod
    def _library_status_text(library: PaperLibrary) -> str:
        vector = library.vector_index_status()
        mode = "BM25 + 本地向量" if vector == "可用" else (
            "BM25（向量需更新）" if vector == "需要更新" else "BM25"
        )
        return f"{library.paper_count()} 篇论文 · {mode}"

    def _browse_folder(self) -> None:
        selected = filedialog.askdirectory(parent=self.root, title="选择包含论文 PDF 的文件夹")
        if selected:
            self.folder_var.set(selected)

    def _require_library(self) -> PaperLibrary | None:
        if not self.current_library:
            messagebox.showinfo("请先新建论文库", "请先点击顶部的“新建论文库”。")
            return None
        return self.current_library

    def _import_folder(self) -> None:
        library = self._require_library()
        if not library:
            return
        folder = Path(self.folder_var.get().strip())
        self._run_background(
            lambda: library.import_folder(folder),
            self._import_complete,
            self.import_message,
            "正在扫描 PDF 并建立索引……",
        )

    def _import_url(self) -> None:
        library = self._require_library()
        if not library:
            return
        url = self.url_var.get().strip()
        if not url:
            messagebox.showinfo("请输入网址", "请粘贴公开论文网址或 PDF 直链。")
            return
        self._run_background(
            lambda: library.import_url(url),
            self._import_complete,
            self.import_message,
            "正在读取公开网页并建立索引……",
        )

    def _build_vector_index(self) -> None:
        library = self._require_library()
        if not library:
            return
        if not library.index_path.is_file():
            messagebox.showinfo("请先导入论文", "当前论文库还没有可建立向量索引的论文。")
            return
        self._run_background(
            library.build_vector_index,
            self._vector_index_complete,
            self.import_message,
            "正在下载/加载本地 Embedding 模型并建立向量索引……",
        )

    def _vector_index_complete(self, result: dict) -> None:
        if self.current_library:
            self.library_status.configure(text=self._library_status_text(self.current_library))
        self.import_message.configure(
            text=f"向量索引可用：{result['chunks']} 个文本块，{result['dimensions']} 维"
        )
        messagebox.showinfo(
            "向量索引完成",
            f"模型：{result['model']}\n文本块：{result['chunks']}\n"
            "之后检索会自动使用 BM25 + 本地向量混合排序。",
        )

    def _import_complete(self, result) -> None:
        self._refresh_papers()
        self.import_message.configure(
            text=f"新增 {result.added} 篇，重复 {result.duplicates} 篇，失败 {result.failed} 篇"
        )
        if result.failures:
            messagebox.showwarning("部分文件失败", "\n".join(result.failures[:12]))
        elif result.added:
            messagebox.showinfo("导入完成", f"已新增 {result.added} 篇论文并更新索引。")

    def _selected_paper_record(self):
        selected = self.paper_tree.selection()
        if not selected or not self.current_library:
            return None
        paper_id = selected[0]
        return next((record for record in self.current_library.records() if record.paper_id == paper_id), None)

    def _copy_text(self, value: str, status: str = "已复制") -> str:
        self.root.clipboard_clear()
        self.root.clipboard_append(value)
        self.root.update_idletasks()
        if hasattr(self, "import_message"):
            self.import_message.configure(text=status)
        return "break"

    def _copy_selected_title(self, _event=None) -> str:
        record = self._selected_paper_record()
        return self._copy_text(record.title, "已复制论文标题") if record else "break"

    def _copy_selected_path(self, _event=None) -> str:
        record = self._selected_paper_record()
        return self._copy_text(record.local_path, "已复制本地路径") if record else "break"

    def _copy_selected_row(self, _event=None) -> str:
        record = self._selected_paper_record()
        if not record:
            return "break"
        source = record.source if record.source_type == "web" else ""
        return self._copy_text(f"{record.title}\t{record.local_path}\t{source}".rstrip(), "已复制论文信息")

    def _show_paper_menu(self, event) -> str:
        row = self.paper_tree.identify_row(event.y)
        if row:
            self.paper_tree.selection_set(row)
            self.paper_tree.focus(row)
            self.paper_menu.tk_popup(event.x_root, event.y_root)
        return "break"

    def _remove_selected_paper(self) -> None:
        record = self._selected_paper_record()
        library = self.current_library
        if not record or not library:
            messagebox.showinfo("请选择论文", "请先在列表中选择一篇论文。")
            return
        if not messagebox.askyesno(
            "从论文库移除",
            f"确定从当前论文库移除《{record.title}》吗？\n\n原始 PDF 文件和网页下载缓存不会被删除。",
            parent=self.root,
        ):
            return
        self._run_background(
            lambda: library.remove_paper(record.paper_id),
            lambda removed: self._paper_removed(removed.title),
            self.import_message,
            "正在更新论文库和索引……",
        )

    def _paper_removed(self, title: str) -> None:
        self._refresh_papers()
        self.import_message.configure(text=f"已从论文库移除《{title}》；PDF 文件仍保留。")

    def _open_selected_source(self, _event=None) -> None:
        record = self._selected_paper_record()
        if not record:
            return
        if Path(record.local_path).exists():
            os.startfile(record.local_path)  # type: ignore[attr-defined]
        elif record.source.startswith(("http://", "https://")):
            webbrowser.open(record.source)

    def _open_library_folder(self) -> None:
        library = self._require_library()
        if library:
            os.startfile(str(library.path))  # type: ignore[attr-defined]

    def _append_chat(self, speaker: str, content: str, tag: str) -> None:
        self.chat_log.configure(state="normal")
        self.chat_log.insert("end", f"{speaker}\n", tag)
        self._insert_markdown(content.strip())
        self.chat_log.insert("end", "\n")
        self.chat_log.configure(state="disabled")
        self.chat_log.see("end")

    def _clear_chat_log(self) -> None:
        for widget in self._embedded_widgets:
            if widget.winfo_exists():
                widget.destroy()
        self._embedded_widgets.clear()
        self.chat_log.configure(state="normal")
        self.chat_log.delete("1.0", "end")
        self.chat_log.configure(state="disabled")
        self._table_cells.clear()

    def _insert_inline(self, text: str) -> None:
        tags = {"bold": "md_bold", "italic": "md_italic", "code": "md_code"}
        for value, style in inline_segments(text):
            self.chat_log.insert("end", value, tags.get(style, ()))

    def _insert_table(self, rows: tuple[tuple[str, ...], ...]) -> None:
        if not rows:
            return
        palette = THEMES[self.theme_name]
        frame = tk.Frame(self.chat_log, background=palette["border"], borderwidth=1)
        self._embedded_widgets.append(frame)
        columns = len(rows[0])
        available = max(650, self.chat_log.winfo_width() - 80)
        cell_width = max(12, min(36, int((available / max(columns, 1)) / 8)))
        table_text = "\n".join("\t".join(row) for row in rows)
        for row_index, row in enumerate(rows):
            for column_index, value in enumerate(row):
                header = row_index == 0
                height = max(1, min(8, math.ceil(max(len(value), 1) / max(cell_width, 1)) + value.count("\n")))
                cell = tk.Text(
                    frame,
                    width=cell_width,
                    height=height,
                    wrap="word",
                    padx=8,
                    pady=6,
                    borderwidth=0,
                    relief="flat",
                    background=palette["accent"] if header else palette["field"],
                    foreground="#FFFFFF" if header else palette["text"],
                    font=("Microsoft YaHei UI", 9, "bold" if header else "normal"),
                    selectbackground=palette["accent_hover"],
                    selectforeground="#FFFFFF",
                    cursor="xterm",
                )
                cell.insert("1.0", value)
                cell.configure(state="disabled")
                cell.grid(row=row_index, column=column_index, sticky="nsew", padx=(0 if column_index == 0 else 1, 0), pady=(0 if row_index == 0 else 1, 0))
                cell.bind("<Button-3>", lambda event, value=value, table=table_text: self._show_table_copy_menu(event, value, table))
                frame.columnconfigure(column_index, weight=1)
                self._table_cells.append((frame, cell, header))
        self.chat_log.window_create("end", window=frame, padx=2, pady=7)
        self.chat_log.insert("end", "\n")

    def _show_table_copy_menu(self, event, cell_text: str, table_text: str) -> str:
        menu = tk.Menu(self.root, tearoff=False)
        menu.add_command(label="复制这个单元格", command=lambda: self._copy_text(cell_text))
        menu.add_command(label="复制整张表格", command=lambda: self._copy_text(table_text))
        menu.tk_popup(event.x_root, event.y_root)
        return "break"

    def _insert_horizontal_rule(self) -> None:
        palette = THEMES[self.theme_name]
        rule = tk.Frame(self.chat_log, background=palette["border"], height=1, width=760)
        self._embedded_widgets.append(rule)
        self.chat_log.window_create("end", window=rule, padx=2, pady=7)
        self.chat_log.insert("end", "\n")

    def _insert_markdown(self, content: str) -> None:
        for block in parse_markdown_blocks(content):
            if block.kind == "table":
                self._insert_table(block.rows)
            elif block.kind == "horizontal_rule":
                self._insert_horizontal_rule()
            elif block.kind == "heading":
                tag = "md_h1" if block.level == 1 else "md_h2" if block.level == 2 else "md_h3"
                self.chat_log.insert("end", block.text + "\n", tag)
            elif block.kind == "bullet":
                self.chat_log.insert("end", "    " * block.level + "• ")
                self._insert_inline(block.text)
                self.chat_log.insert("end", "\n")
            elif block.kind == "quote":
                self.chat_log.insert("end", block.text + "\n", "md_quote")
            elif block.kind == "code_block":
                self.chat_log.insert("end", block.text + "\n", "md_code_block")
            elif block.kind == "paragraph":
                self._insert_inline(block.text)
                self.chat_log.insert("end", "\n")
            else:
                self.chat_log.insert("end", "\n")

    def _send_chat(self) -> str:
        library = self._require_library()
        if not library:
            return "break"
        if self.busy:
            messagebox.showinfo("请稍候", "当前已有任务正在运行。")
            return "break"
        query = self.chat_input.get("1.0", "end").strip()
        config = LLMConfig.from_env()
        if not llm_ready(config):
            messagebox.showinfo("尚未配置模型", "请点击右上角“模型设置”配置 API。")
            return "break"
        if not query:
            return "break"
        self.chat_input.delete("1.0", "end")
        self._append_chat("你", query, "user")
        history = self.histories.setdefault(library.info.library_id, [])

        def task():
            workflow = ResearchWorkflowAgent(
                self.catalog,
                client=OpenAICompatibleClient(config),
                paper_agent=PaperAgent(
                    PaperIndex.load(library.index_path) if library.index_path.is_file() else PaperIndex([]),
                    output_dir=library.path / "outputs",
                    online_importer=lambda query, top_k=5, queries=None, year_from=None:
                        library.search_and_import(query, top_k, queries, year_from).as_markdown(),
                ),
                checkpoint_path=library.sessions_path / "in_progress.json",
            )
            return workflow.chat(
                query=query,
                history=history,
                progress_callback=self._queue_chat_progress,
                step_callback=self._queue_step,
            )

        def success(payload) -> None:
            result, plan = payload
            trace = "\n".join(
                f"{step['number']}. {step['tool']} · {step['skill']} · {step['status']}"
                for step in result.steps
            )
            self._append_chat("执行记录", trace, "trace")
            self._append_chat("Agent", result.answer, "agent")
            history.extend(
                [
                    {"role": "user", "content": query},
                    {"role": "assistant", "content": result.answer},
                ]
            )
            self._save_session(library, history, plan, result.steps)
            self._refresh_papers()
            if plan.tool == "create_presentation":
                self.notebook.select(self.ppt_tab)

        self._set_chat_progress(2, "任务已提交")
        self._run_background(task, success, self.chat_status, "正在启动任务  2%")
        return "break"

    def _save_session(self, library: PaperLibrary, history: list[dict[str, str]], plan, steps=None) -> None:
        session_path = library.sessions_path / "latest.json"
        session_path.write_text(
            json.dumps(
                {
                    "updated_at": datetime.now().isoformat(),
                    "messages": history,
                    "last_plan": asdict(plan),
                    "last_steps": steps or [],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def _refresh_api_status(self) -> None:
        config = LLMConfig.from_env()
        if llm_ready(config):
            provider = detect_provider(config.base_url).name
            self.api_status.configure(text=f"{provider}\n{config.model}", style="Success.TLabel")
        else:
            self.api_status.configure(text="模型未配置", style="Warning.TLabel")

    def _open_api_dialog(self) -> None:
        current = LLMConfig.from_env()
        dialog = tk.Toplevel(self.root)
        dialog.title("模型设置")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(False, False)
        dialog.configure(background=THEMES[self.theme_name]["bg"])
        frame = ttk.Frame(dialog, padding=22)
        frame.pack(fill="both", expand=True)

        selected_preset = detect_provider(current.base_url)
        provider_var = tk.StringVar(value=selected_preset.name)
        base_var = tk.StringVar(value=current.base_url)
        model_var = tk.StringVar(value=current.model or selected_preset.model)
        key_var = tk.StringVar(value=current.api_key)
        initial_style = current.api_style if current.api_style in {"responses", "chat_completions"} else selected_preset.api_style
        style_var = tk.StringVar(value=initial_style)
        output_tokens_var = tk.StringVar(value="自动" if current.max_output_tokens is None else str(current.max_output_tokens))
        save_var = tk.BooleanVar(value=True)
        note_var = tk.StringVar(value=selected_preset.note)
        test_var = tk.StringVar(value="先选择服务商，填入该平台的 API Key；所有字段都可以修改。")

        ttk.Label(frame, text="配置大模型 API", style="Heading.TLabel").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))
        ttk.Label(frame, text="服务商：").grid(row=1, column=0, sticky="e", pady=6)
        provider = ttk.Combobox(frame, textvariable=provider_var, state="readonly", values=tuple(item.name for item in PROVIDER_PRESETS), width=38)
        provider.grid(row=1, column=1, sticky="ew", pady=6)
        ttk.Label(frame, text="Base URL：").grid(row=2, column=0, sticky="e", pady=6)
        ttk.Entry(frame, textvariable=base_var, width=54).grid(row=2, column=1, sticky="ew", pady=6)
        ttk.Label(frame, text="模型 ID：").grid(row=3, column=0, sticky="e", pady=6)
        model_combo = ttk.Combobox(
            frame,
            textvariable=model_var,
            state="normal",
            values=selected_preset.model_options,
        )
        model_combo.grid(row=3, column=1, sticky="ew", pady=6)
        ttk.Label(frame, text="API Key：").grid(row=4, column=0, sticky="e", pady=6)
        ttk.Entry(frame, textvariable=key_var, show="●").grid(row=4, column=1, sticky="ew", pady=6)
        ttk.Label(frame, text="接口协议：").grid(row=5, column=0, sticky="e", pady=6)
        ttk.Combobox(frame, textvariable=style_var, state="readonly", values=("responses", "chat_completions"), width=38).grid(row=5, column=1, sticky="ew", pady=6)
        ttk.Label(frame, text="单次最大输出 token：").grid(row=6, column=0, sticky="e", pady=6)
        ttk.Entry(frame, textvariable=output_tokens_var, width=18).grid(row=6, column=1, sticky="w", pady=6)
        ttk.Label(frame, text="可填 1–393216，留空或填“自动”则由服务商决定。DeepSeek 思考模式自动为 64K；截断时最多自动续写 2 次。", style="Muted.TLabel", wraplength=450).grid(row=7, column=1, sticky="w", pady=(0, 6))
        ttk.Label(frame, textvariable=note_var, style="Muted.TLabel", wraplength=450).grid(row=8, column=1, sticky="w", pady=(2, 8))
        ttk.Checkbutton(frame, text="保存到本机 .env，供下次启动使用", variable=save_var).grid(row=9, column=1, sticky="w", pady=(4, 2))
        ttk.Label(frame, text="密钥只写入本机已忽略的 .env，不会进入论文库、回答或日志。", style="Muted.TLabel").grid(row=10, column=1, sticky="w")
        ttk.Separator(frame).grid(row=11, column=0, columnspan=2, sticky="ew", pady=(14, 10))
        test_label = ttk.Label(frame, textvariable=test_var, style="Muted.TLabel", wraplength=450)
        test_label.grid(row=12, column=0, columnspan=2, sticky="w")

        def provider_changed(_event=None) -> None:
            preset = PROVIDER_BY_NAME[provider_var.get()]
            base_var.set(preset.base_url)
            model_combo.configure(values=preset.model_options)
            model_var.set(preset.model)
            style_var.set(preset.api_style)
            key_var.set("")
            note_var.set(preset.note)
            test_var.set("已载入预设。请填入这个平台自己的 API Key，再测试连接。")

        provider.bind("<<ComboboxSelected>>", provider_changed)

        def read_form() -> LLMConfig:
            raw_output_tokens = output_tokens_var.get().strip().lower()
            if raw_output_tokens in {"", "自动", "auto"}:
                output_tokens = None
            else:
                try:
                    output_tokens = int(raw_output_tokens)
                except ValueError as exc:
                    raise ValueError("单次最大输出 token 请填写整数或“自动”") from exc
                if not 1 <= output_tokens <= 393216:
                    raise ValueError("单次最大输出 token 请填写 1 到 393216，或填写“自动”")
            config = LLMConfig(
                base_url=base_var.get().strip(),
                model=model_var.get().strip(),
                api_key=key_var.get().strip(),
                api_style=style_var.get().strip(),
                timeout_seconds=current.timeout_seconds,
                max_output_tokens=output_tokens,
            )
            config.validate()
            preset = PROVIDER_BY_NAME[provider_var.get()]
            if preset.requires_key and not config.api_key:
                raise ValueError(f"{preset.name} 需要填写 API Key")
            return config

        def test_connection() -> None:
            try:
                config = read_form()
            except ValueError as exc:
                messagebox.showerror("配置有误", str(exc), parent=dialog)
                return
            test_var.set("正在发送一条很短的测试消息……")
            test_button.configure(state="disabled")

            def runner() -> None:
                try:
                    probe = LLMConfig(
                        base_url=config.base_url,
                        model=config.model,
                        api_key=config.api_key,
                        api_style=config.api_style,
                        timeout_seconds=30,
                        max_output_tokens=24,
                    )
                    answer = OpenAICompatibleClient(probe).generate(
                        "你是连接测试助手。", "只回复：连接成功",
                        reasoning_effort="none",
                    )
                except Exception as exc:
                    self.root.after(0, lambda error=exc: finish_test(False, str(error)))
                else:
                    self.root.after(0, lambda: finish_test(True, answer))

            threading.Thread(target=runner, daemon=True).start()

        def finish_test(ok: bool, detail: str) -> None:
            if not dialog.winfo_exists():
                return
            test_button.configure(state="normal")
            if ok:
                test_var.set(f"连接成功，模型回复：{detail[:80]}")
                test_label.configure(style="Success.TLabel")
            else:
                test_var.set(f"连接失败：{detail[:260]}")
                test_label.configure(style="Warning.TLabel")

        def commit() -> None:
            try:
                config = read_form()
                apply_config(config)
                if save_var.get():
                    save_config(CONFIG_PATH, config)
            except (OSError, ValueError) as exc:
                messagebox.showerror("配置失败", str(exc), parent=dialog)
                return
            self._refresh_api_status()
            dialog.destroy()
            messagebox.showinfo("配置完成", "模型配置已生效。现在可以进入“与 Agent 对话”直接提任务。")

        buttons = ttk.Frame(frame)
        buttons.grid(row=13, column=0, columnspan=2, sticky="e", pady=(16, 0))
        ttk.Button(buttons, text="取消", command=dialog.destroy).pack(side="right")
        ttk.Button(buttons, text="保存并使用", command=commit, style="Accent.TButton").pack(side="right", padx=(0, 8))
        test_button = ttk.Button(buttons, text="测试连接", command=test_connection)
        test_button.pack(side="right", padx=(0, 8))
        frame.columnconfigure(1, weight=1)


def main() -> None:
    os.chdir(PROJECT_ROOT)
    load_local_config(CONFIG_PATH)
    root = tk.Tk()
    PaperAgentGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
