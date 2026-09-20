from __future__ import annotations

import os
from pathlib import Path
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from .config import load_local_config
from .library import LibraryManager, PaperLibrary
from .skills import SkillCatalog
from .ui_settings import DEFAULT_THEME, load_ui_settings
from .ui.chat_page import ChatPageMixin
from .ui.home_page import HomePageMixin
from .ui.library_page import LibraryPageMixin
from .ui.model_settings import ModelSettingsMixin
from .ui.theme import THEMES, ThemeMixin
from .presentation_ui import PresentationPanel
from .discovery import (
    DiscoveryPaper, DiscoveryService, DiscoveryStore,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent
LIBRARIES_ROOT = PROJECT_ROOT / "libraries"
CONFIG_PATH = PROJECT_ROOT / ".env"
UI_SETTINGS_PATH = PROJECT_ROOT / "config" / "ui.json"
DISCOVERY_SETTINGS_PATH = PROJECT_ROOT / "config" / "discovery.json"
DISCOVERY_CACHE_PATH = PROJECT_ROOT / "config" / "discovery_cache.json"


class PaperAgentGUI(ThemeMixin, HomePageMixin, LibraryPageMixin, ChatPageMixin, ModelSettingsMixin):
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("论文 Data Agent")
        self.root.geometry("1180x860")
        self.root.minsize(960, 600)
        self.manager = LibraryManager(LIBRARIES_ROOT)
        self.catalog = SkillCatalog()
        self.current_library: PaperLibrary | None = None
        self.library_lookup: dict[str, str] = {}
        self.histories: dict[str, list[dict[str, str]]] = {}
        self.busy = False
        self.discovery_busy = False
        self._pending_discovery_refresh: tuple[str, str, bool] | None = None
        self.discovery_store = DiscoveryStore(DISCOVERY_SETTINGS_PATH, DISCOVERY_CACHE_PATH)
        self.discovery_service = DiscoveryService(PROJECT_ROOT / "output" / "discovery")
        self.discovery_subscriptions = self.discovery_store.load_subscriptions()
        self.discovery_papers: dict[str, DiscoveryPaper] = {}
        self._table_cells: list[tuple[tk.Frame, tk.Widget, bool]] = []
        self._embedded_widgets: list[tk.Widget] = []
        self.ui_settings = load_ui_settings(UI_SETTINGS_PATH)
        self.ui_settings_path = UI_SETTINGS_PATH
        self.config_path = CONFIG_PATH
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
        self._discovery_home_after_id = self.root.after(250, self._load_discovery_home)
        self.root.bind("<Destroy>", self._cancel_pending_home_load, add="+")

    def _build_header(self) -> None:
        self.header = ttk.Frame(self.root, padding=(22, 17, 22, 14), style="Header.TFrame")
        self.header.pack(fill="x")
        ttk.Label(self.header, text="论文 Data Agent", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(
            self.header,
            text="导入任意本地论文或公开网址，然后直接向 Agent 提问",
            style="Subtitle.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(3, 0))
        self.header_controls = ttk.Frame(self.header, style="Header.TFrame")
        theme_box = ttk.Frame(self.header_controls, style="Header.TFrame")
        theme_box.pack(side="left", padx=(0, 20))
        ttk.Label(theme_box, text="皮肤", style="Header.TLabel").pack(side="left", padx=(0, 6))
        self.theme_var = tk.StringVar(value=self.theme_name)
        theme_combo = ttk.Combobox(theme_box, textvariable=self.theme_var, state="readonly", values=tuple(THEMES), width=10)
        theme_combo.pack(side="left")
        theme_combo.bind("<<ComboboxSelected>>", self._theme_changed)
        self.api_status = ttk.Label(self.header_controls, text="", style="Warning.TLabel")
        self.api_status.pack(side="left")
        self.model_settings_button = ttk.Button(
            self.header_controls, text="模型设置", command=self._open_api_dialog, style="Accent.TButton",
        )
        self.model_settings_button.pack(side="left", padx=(12, 0))
        self.header_controls.grid(row=2, column=0, columnspan=2, sticky="e", pady=(10, 0))
        self.header.columnconfigure(0, weight=1)

    def _build_tabs(self) -> None:
        self.main_notebook = ttk.Notebook(self.root)
        self.main_notebook.pack(fill="both", expand=True, padx=18, pady=(0, 14))
        self.home_tab = ttk.Frame(self.main_notebook, padding=16)
        self.library_hub_tab = ttk.Frame(self.main_notebook, padding=12)
        self.help_tab = ttk.Frame(self.main_notebook, padding=16)
        self.main_notebook.add(self.home_tab, text="首页")
        self.main_notebook.add(self.library_hub_tab, text="我的论文库")
        self.main_notebook.add(self.help_tab, text="使用说明")

        self._build_library_bar(self.library_hub_tab)
        self.notebook = ttk.Notebook(self.library_hub_tab)
        self.notebook.pack(fill="both", expand=True)
        self.import_tab = ttk.Frame(self.notebook, padding=16)
        self.chat_tab = ttk.Frame(self.notebook, padding=16)
        self.notebook.add(self.import_tab, text="论文导入")
        self.notebook.add(self.chat_tab, text="与 Agent 对话")
        self.ppt_tab = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(self.ppt_tab, text="PPT 预览与修改")
        self.ppt_panel = PresentationPanel(self, self.ppt_tab)
        self.notebook.bind("<<NotebookTabChanged>>", self._tab_changed)
        self._build_home_tab()
        self._build_import_tab()
        self._build_chat_tab()
        self._build_help_tab()

    def _build_help_tab(self) -> None:
        self.help_text = ScrolledText(self.help_tab, wrap="word", font=("Microsoft YaHei UI", 10), padx=14, pady=12)
        self.help_text.pack(fill="both", expand=True)
        self.help_text.insert(
            "1.0",
            "使用顺序\n\n"
            "1. 首次打开停留在“首页”；点击热门方向会直接切换并刷新；“订阅设置”用于修改标签、期刊、会议和每次推荐 2–10 篇。\n"
            "2. 进入“我的论文库”，点击“新建论文库”；每个课题建议使用一个独立论文库。\n"
            "3. 在论文库内的“论文导入”页粘贴本地文件夹地址，或点击“浏览选择”。\n"
            "4. 也可以从首页选择推荐论文和目标论文库，下载仍可访问的公开全文。\n"
            "5. 可点击“建立/更新向量索引”，首次下载公开多语言 Embedding 模型，之后使用 BM25+向量混合检索。\n"
            "6. 点击右上角“模型设置”，可直接选择 DeepSeek、Kimi、千问、智谱等预设。\n"
            "7. 进入论文库内的“与 Agent 对话”，直接描述任务。\n\n"
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


def main() -> None:
    os.chdir(PROJECT_ROOT)
    load_local_config(CONFIG_PATH)
    root = tk.Tk()
    PaperAgentGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
