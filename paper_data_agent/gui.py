from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import re
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
from .ui_settings import DEFAULT_THEME, load_ui_settings
from .ui.theme import THEMES, ThemeMixin
from .workflow import ResearchWorkflowAgent
from .presentation_ui import PresentationPanel
from .discovery import (
    DiscoveryPaper, DiscoveryService, DiscoveryStore, DiscoverySubscription,
    SORT_COMBINED, SORT_MODES,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent
LIBRARIES_ROOT = PROJECT_ROOT / "libraries"
CONFIG_PATH = PROJECT_ROOT / ".env"
UI_SETTINGS_PATH = PROJECT_ROOT / "config" / "ui.json"
DISCOVERY_SETTINGS_PATH = PROJECT_ROOT / "config" / "discovery.json"
DISCOVERY_CACHE_PATH = PROJECT_ROOT / "config" / "discovery_cache.json"


class PaperAgentGUI(ThemeMixin):
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

    def _build_library_bar(self, parent: ttk.Frame) -> None:
        bar = ttk.Frame(parent, padding=(0, 0, 0, 10))
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

    def _build_home_tab(self) -> None:
        self.home_canvas = tk.Canvas(self.home_tab, highlightthickness=0, borderwidth=0)
        self.home_scrollbar = ttk.Scrollbar(
            self.home_tab, orient="vertical", command=self.home_canvas.yview,
        )
        self.home_canvas.configure(yscrollcommand=self.home_scrollbar.set)
        self.home_scrollbar.pack(side="right", fill="y")
        self.home_canvas.pack(side="left", fill="both", expand=True)
        self.home_content = ttk.Frame(self.home_canvas)
        self._home_canvas_window = self.home_canvas.create_window(
            (0, 0), window=self.home_content, anchor="nw",
        )
        self.home_content.bind("<Configure>", self._sync_home_scroll_region)
        self.home_canvas.bind("<Configure>", self._resize_home_content)
        self.root.bind_all("<MouseWheel>", self._scroll_home_from_pointer, add="+")

        heading = ttk.Frame(self.home_content)
        heading.pack(fill="x", pady=(0, 10))
        ttk.Label(heading, text="论文发现", style="Heading.TLabel").pack(side="left")
        ttk.Label(heading, text="每天按你的研究方向发现新论文；引用数来自 OpenAlex。", style="Muted.TLabel").pack(side="left", padx=(10, 0))
        self.discovery_status = ttk.Label(heading, text="等待设置订阅", style="Muted.TLabel")
        self.discovery_status.pack(side="right")

        quick = ttk.LabelFrame(self.home_content, text="热门方向（点击即切换并刷新）", padding=8)
        quick.pack(fill="x", pady=(0, 10))
        for index, topic in enumerate(("AI Agent", "大语言模型", "多模态学习", "计算机视觉",
                                       "自然语言处理", "虚拟细胞", "脑科学与 fMRI", "具身智能")):
            ttk.Button(quick, text=topic, command=lambda value=topic: self._quick_topic(value)).grid(
                row=index // 3, column=index % 3, sticky="ew", padx=3, pady=3)
        for column in range(3):
            quick.columnconfigure(column, weight=1)

        filters = ttk.Frame(self.home_content)
        filters.pack(fill="x", pady=(0, 10))
        ttk.Label(filters, text="订阅：").pack(side="left")
        self.discovery_subscription_var = tk.StringVar()
        self.discovery_subscription_combo = ttk.Combobox(filters, textvariable=self.discovery_subscription_var,
                                                          state="readonly", width=24)
        self.discovery_subscription_combo.pack(side="left", padx=(5, 8))
        self.discovery_subscription_combo.bind("<<ComboboxSelected>>", self._discovery_subscription_changed)
        ttk.Button(filters, text="订阅设置", command=self._open_subscription_dialog).pack(side="left")
        ttk.Label(filters, text="排序：").pack(side="left", padx=(18, 4))
        self.discovery_sort_var = tk.StringVar(value=SORT_COMBINED)
        sort_combo = ttk.Combobox(filters, textvariable=self.discovery_sort_var, values=SORT_MODES,
                                  state="readonly", width=10)
        sort_combo.pack(side="left")
        sort_combo.bind("<<ComboboxSelected>>", self._discovery_sort_changed)
        ttk.Button(filters, text="刷新今日推荐", command=self._refresh_discovery,
                   style="Accent.TButton").pack(side="left", padx=(10, 0))

        list_frame = ttk.LabelFrame(self.home_content, text="推荐结果（每次 2–10 篇）", padding=8)
        self.discovery_results_frame = list_frame
        list_frame.pack(fill="x")
        columns = ("title", "date", "venue", "citations", "access")
        self.discovery_tree = ttk.Treeview(list_frame, columns=columns, show="headings", height=5, selectmode="browse")
        for key, label, width in (
            ("title", "论文", 430), ("date", "发表日期", 95), ("venue", "期刊 / 会议", 190),
            ("citations", "OpenAlex 引用", 100), ("access", "公开全文", 75),
        ):
            self.discovery_tree.heading(key, text=label)
            self.discovery_tree.column(key, width=width, anchor="w" if key in {"title", "venue"} else "center")
        vertical_scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.discovery_tree.yview)
        horizontal_scrollbar = ttk.Scrollbar(list_frame, orient="horizontal", command=self.discovery_tree.xview)
        self.discovery_tree.configure(
            yscrollcommand=vertical_scrollbar.set,
            xscrollcommand=horizontal_scrollbar.set,
        )
        self.discovery_tree.grid(row=0, column=0, sticky="nsew")
        vertical_scrollbar.grid(row=0, column=1, sticky="ns")
        horizontal_scrollbar.grid(row=1, column=0, sticky="ew")
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)
        self.discovery_tree.bind("<<TreeviewSelect>>", self._show_discovery_detail)
        self.discovery_tree.bind("<Double-1>", lambda _event: self._open_discovery_source())

        detail_frame = ttk.LabelFrame(self.home_content, text="论文摘要与操作", padding=8)
        detail_frame.pack(fill="both", expand=True, pady=(10, 0))
        self.discovery_detail = ScrolledText(detail_frame, height=5, wrap="word", font=("Microsoft YaHei UI", 9), padx=8, pady=6)
        self.discovery_detail.insert("1.0", "选择一篇推荐论文，可查看摘要、来源和评分依据。")
        self.discovery_detail.configure(state="disabled")
        actions = ttk.Frame(detail_frame)
        ttk.Label(actions, text="加入论文库：").pack(anchor="w")
        self.discovery_target_combo = ttk.Combobox(actions, state="readonly", width=25)
        self.discovery_target_combo.pack(fill="x", pady=(3, 8))
        self.discovery_target_combo.bind("<<ComboboxSelected>>", lambda _event: self._render_discovery_papers(list(self.discovery_papers.values())))
        self.discovery_import_button = ttk.Button(
            actions, text="加入选中的论文", command=self._import_discovery_paper, style="Accent.TButton",
        )
        self.discovery_open_button = ttk.Button(actions, text="打开原文网页", command=self._open_discovery_source)
        self.discovery_copy_button = ttk.Button(actions, text="复制标题和链接", command=self._copy_discovery_info)
        self.discovery_import_button.pack(fill="x")
        self.discovery_open_button.pack(fill="x", pady=(7, 0))
        self.discovery_copy_button.pack(fill="x", pady=(7, 0))
        self.discovery_detail.grid(row=0, column=0, sticky="nsew")
        actions.grid(row=0, column=1, sticky="ns", padx=(10, 0))
        detail_frame.columnconfigure(0, weight=1)
        detail_frame.rowconfigure(0, weight=1)

    def _sync_home_scroll_region(self, _event=None) -> None:
        if not hasattr(self, "home_canvas"):
            return
        self.home_canvas.update_idletasks()
        requested_height = self.home_content.winfo_reqheight()
        viewport_height = self.home_canvas.winfo_height()
        content_height = max(requested_height, viewport_height)
        self.home_canvas.itemconfigure(self._home_canvas_window, height=content_height)
        self.home_canvas.configure(
            scrollregion=(0, 0, self.home_canvas.winfo_width(), content_height),
        )

    def _resize_home_content(self, event) -> None:
        self.home_canvas.itemconfigure(self._home_canvas_window, width=max(1, event.width))
        self.root.after_idle(self._sync_home_scroll_region)

    def _scroll_home_from_pointer(self, event):
        if not hasattr(self, "home_canvas") or self.main_notebook.select() != str(self.home_tab):
            return None
        pointer_x, pointer_y = self.root.winfo_pointerxy()
        left, top = self.home_canvas.winfo_rootx(), self.home_canvas.winfo_rooty()
        if not (left <= pointer_x < left + self.home_canvas.winfo_width()
                and top <= pointer_y < top + self.home_canvas.winfo_height()):
            return None
        if isinstance(event.widget, (tk.Text, ttk.Treeview, ttk.Combobox)):
            return None
        delta = -1 if event.delta > 0 else 1
        self.home_canvas.yview_scroll(delta * 3, "units")
        return "break"

    def _tab_changed(self, event=None):
        if hasattr(self, "ppt_panel") and self.notebook.select() == str(self.ppt_tab):
            self.ppt_panel.refresh()

    def _refresh_discovery_controls(self) -> None:
        if not hasattr(self, "discovery_subscription_combo"):
            return
        names = [item.name for item in self.discovery_subscriptions]
        self.discovery_subscription_combo["values"] = names
        if names and self.discovery_subscription_var.get() not in names:
            self.discovery_subscription_var.set(names[0])
        elif not names:
            self.discovery_subscription_var.set("")
        libraries = list(self.library_lookup)
        self.discovery_target_combo["values"] = libraries
        if libraries and self.discovery_target_combo.get() not in libraries:
            current_id = self.current_library.info.library_id if self.current_library else ""
            current_display = next((display for display, library_id in self.library_lookup.items()
                                    if library_id == current_id), libraries[0])
            self.discovery_target_combo.set(current_display)
        elif not libraries:
            self.discovery_target_combo.set("")

    def _selected_subscription(self) -> DiscoverySubscription | None:
        selected = self.discovery_subscription_var.get()
        return next((item for item in self.discovery_subscriptions if item.name == selected), None)

    def _quick_topic(self, topic: str) -> None:
        subscription = next(
            (item for item in self.discovery_subscriptions
             if item.name == topic or [value.casefold() for value in item.topics] == [topic.casefold()]),
            None,
        )
        if subscription is None:
            current = self._selected_subscription()
            subscription = DiscoverySubscription(
                name=topic,
                topics=[topic],
                count=current.count if current else 5,
                recency_days=current.recency_days if current else 90,
            ).normalized()
            self.discovery_subscriptions.append(subscription)
            self.discovery_store.save_subscriptions(self.discovery_subscriptions)
            self._refresh_discovery_controls()
        self.discovery_subscription_var.set(subscription.name)
        cached = self.discovery_store.load_cached(subscription, self.discovery_sort_var.get())
        if cached is not None:
            self._render_discovery_papers(cached)
        self.discovery_status.configure(text=f"已选择“{topic}”，正在更新……")
        self._refresh_discovery()

    def _open_subscription_dialog(self, prefill_topic: str = "") -> None:
        current = None if prefill_topic else self._selected_subscription()
        dialog = tk.Toplevel(self.root)
        dialog.title("每日论文订阅设置")
        dialog.geometry("590x390")
        dialog.transient(self.root)
        dialog.grab_set()
        body = ttk.Frame(dialog, padding=18)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="订阅名称：").grid(row=0, column=0, sticky="w", pady=5)
        name_var = tk.StringVar(value=current.name if current else (prefill_topic or "我的关注"))
        ttk.Entry(body, textvariable=name_var).grid(row=0, column=1, sticky="ew", pady=5)
        ttk.Label(body, text="标签 / 主题：").grid(row=1, column=0, sticky="nw", pady=5)
        topics = tk.Text(body, height=4, wrap="word", font=("Microsoft YaHei UI", 9))
        topics.grid(row=1, column=1, sticky="ew", pady=5)
        topics.insert("1.0", "，".join(current.topics) if current else prefill_topic)
        ttk.Label(body, text="用逗号分隔，例如：AI Agent，虚拟细胞，多模态学习", style="Muted.TLabel").grid(
            row=2, column=1, sticky="w")
        ttk.Label(body, text="期刊 / 会议：").grid(row=3, column=0, sticky="nw", pady=5)
        venues = tk.Text(body, height=3, wrap="word", font=("Microsoft YaHei UI", 9))
        venues.grid(row=3, column=1, sticky="ew", pady=5)
        venues.insert("1.0", "，".join(current.venues) if current else "")
        ttk.Label(body, text="可留空；例如：Nature，NeurIPS，ACL", style="Muted.TLabel").grid(row=4, column=1, sticky="w")
        options = ttk.Frame(body)
        options.grid(row=5, column=1, sticky="w", pady=(12, 6))
        ttk.Label(options, text="每次推荐").pack(side="left")
        count_var = tk.IntVar(value=current.count if current else 5)
        ttk.Spinbox(options, from_=2, to=10, textvariable=count_var, width=4).pack(side="left", padx=5)
        ttk.Label(options, text="篇；检索最近").pack(side="left")
        days_var = tk.IntVar(value=current.recency_days if current else 90)
        ttk.Spinbox(options, from_=7, to=730, increment=7, textvariable=days_var, width=6).pack(side="left", padx=5)
        ttk.Label(options, text="天").pack(side="left")
        ttk.Label(body, text="说明：引用数来自 OpenAlex，会与发表时间和主题相关度分开展示。", style="Muted.TLabel").grid(
            row=6, column=1, sticky="w", pady=(5, 12))
        buttons = ttk.Frame(body)
        buttons.grid(row=7, column=0, columnspan=2, sticky="e")

        def save(as_new: bool = False) -> None:
            try:
                subscription = DiscoverySubscription.from_form(
                    name_var.get(), topics.get("1.0", "end"), venues.get("1.0", "end"),
                    count_var.get(), days_var.get(), "" if as_new or not current else current.subscription_id,
                )
            except (ValueError, tk.TclError) as exc:
                messagebox.showerror("设置有误", str(exc), parent=dialog)
                return
            if not subscription.topics and not subscription.venues:
                messagebox.showinfo("请填写关注内容", "至少填写一个标签、期刊或会议。", parent=dialog)
                return
            if any(item.name == subscription.name and item.subscription_id != subscription.subscription_id
                   for item in self.discovery_subscriptions):
                messagebox.showinfo("名称已存在", "请使用不同的订阅名称。", parent=dialog)
                return
            if current and not as_new:
                self.discovery_subscriptions = [subscription if item.subscription_id == current.subscription_id else item
                                                for item in self.discovery_subscriptions]
            else:
                self.discovery_subscriptions.append(subscription)
            self.discovery_store.save_subscriptions(self.discovery_subscriptions)
            self._refresh_discovery_controls()
            self.discovery_subscription_var.set(subscription.name)
            dialog.destroy()
            self._refresh_discovery()

        def delete() -> None:
            if not current:
                return
            if not messagebox.askyesno("删除订阅", f"确定删除订阅“{current.name}”吗？论文库不会受影响。", parent=dialog):
                return
            self.discovery_subscriptions = [item for item in self.discovery_subscriptions
                                            if item.subscription_id != current.subscription_id]
            self.discovery_store.save_subscriptions(self.discovery_subscriptions)
            self._refresh_discovery_controls()
            self._render_discovery_papers([])
            dialog.destroy()

        if current:
            ttk.Button(buttons, text="删除订阅", command=delete).pack(side="left", padx=(0, 8))
            ttk.Button(buttons, text="另存为新订阅", command=lambda: save(True)).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="取消", command=dialog.destroy).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="保存并刷新", command=save, style="Accent.TButton").pack(side="left")
        body.columnconfigure(1, weight=1)

    def _load_discovery_home(self) -> None:
        self._discovery_home_after_id = None
        self._refresh_discovery_controls()
        subscription = self._selected_subscription()
        if not subscription:
            self.discovery_status.configure(text="请选择热门方向，或设置自定义订阅")
            return
        cached = self.discovery_store.load_cached(subscription, self.discovery_sort_var.get())
        if cached is not None:
            self._render_discovery_papers(cached)
            self.discovery_status.configure(text=f"已显示今日缓存 · {len(cached)} 篇")
        self._refresh_discovery(silent=True)

    def _cancel_pending_home_load(self, event=None) -> None:
        if event is not None and event.widget is not self.root:
            return
        callback_id = getattr(self, "_discovery_home_after_id", None)
        if callback_id:
            try:
                self.root.after_cancel(callback_id)
            except tk.TclError:
                pass
            self._discovery_home_after_id = None

    def _discovery_subscription_changed(self, _event=None) -> None:
        subscription = self._selected_subscription()
        if not subscription:
            return
        cached = self.discovery_store.load_cached(subscription, self.discovery_sort_var.get())
        if cached is not None:
            self._render_discovery_papers(cached)
        else:
            self._refresh_discovery()

    def _discovery_sort_changed(self, _event=None) -> None:
        subscription = self._selected_subscription()
        if not subscription:
            return
        cached = self.discovery_store.load_cached(subscription, self.discovery_sort_var.get())
        if cached is not None:
            self._render_discovery_papers(cached)
        else:
            self._refresh_discovery()

    def _refresh_discovery(self, silent: bool = False) -> None:
        subscription = self._selected_subscription()
        if not subscription:
            if not silent:
                self._open_subscription_dialog()
            return
        sort_mode = self.discovery_sort_var.get()

        if self.discovery_busy:
            self._pending_discovery_refresh = (subscription.subscription_id, sort_mode, silent)
            self.discovery_status.configure(text=f"已选择“{subscription.name}”，等待当前更新结束后自动刷新……")
            return
        self._start_discovery_refresh(subscription, sort_mode, silent)

    def _start_discovery_refresh(
        self, subscription: DiscoverySubscription, sort_mode: str, silent: bool,
    ) -> None:
        self.discovery_busy = True
        self.discovery_status.configure(text=f"正在更新“{subscription.name}”……")

        def task():
            papers = self.discovery_service.recommend(subscription, sort_mode)
            self.discovery_store.save_cached(subscription, sort_mode, papers)
            return papers

        def runner() -> None:
            try:
                papers = task()
            except Exception as exc:
                self.root.after(
                    0,
                    lambda error=exc: self._discovery_refresh_failed(
                        subscription.subscription_id, sort_mode, silent, error,
                    ),
                )
            else:
                self.root.after(
                    0,
                    lambda: self._discovery_refresh_done(subscription.subscription_id, sort_mode, papers),
                )

        threading.Thread(target=runner, daemon=True).start()

    def _discovery_refresh_done(
        self, subscription_id: str, sort_mode: str, papers: list[DiscoveryPaper],
    ) -> None:
        self.discovery_busy = False
        current = self._selected_subscription()
        if (current and current.subscription_id == subscription_id
                and self.discovery_sort_var.get() == sort_mode):
            self._render_discovery_papers(papers)
            self.discovery_status.configure(
                text=f"“{current.name}”已更新 · {len(papers)} 篇 · {datetime.now().strftime('%H:%M')}",
            )
        self._start_pending_discovery_refresh()

    def _discovery_refresh_failed(
        self, subscription_id: str, sort_mode: str, silent: bool, exc: Exception,
    ) -> None:
        self.discovery_busy = False
        current = self._selected_subscription()
        is_current = bool(
            current and current.subscription_id == subscription_id
            and self.discovery_sort_var.get() == sort_mode
        )
        if is_current:
            suffix = "，已保留当前结果" if self.discovery_papers else "；可稍后再次刷新"
            self.discovery_status.configure(text="更新失败" + suffix)
            if not silent:
                messagebox.showerror("推荐更新失败", str(exc))
        self._start_pending_discovery_refresh()

    def _start_pending_discovery_refresh(self) -> None:
        pending = self._pending_discovery_refresh
        self._pending_discovery_refresh = None
        if pending is None:
            return
        subscription_id, sort_mode, silent = pending
        subscription = next(
            (item for item in self.discovery_subscriptions if item.subscription_id == subscription_id),
            None,
        )
        if subscription is not None:
            self._start_discovery_refresh(subscription, sort_mode, silent)

    def _render_discovery_papers(self, papers: list[DiscoveryPaper]) -> None:
        for item in self.discovery_tree.get_children():
            self.discovery_tree.delete(item)
        self.discovery_papers = {}
        if hasattr(self, "discovery_results_frame"):
            self.discovery_results_frame.configure(text=f"推荐结果（{len(papers)} 篇）")
        target = self._selected_discovery_library()
        normalize_doi = lambda value: re.sub(r"^https?://(?:dx\.)?doi\.org/", "", value, flags=re.I).casefold()
        existing_dois = {normalize_doi(record.doi) for record in target.records() if record.doi} if target else set()
        existing_titles = {record.title.casefold() for record in target.records()} if target else set()
        for paper in papers:
            iid = hashlib.sha256(paper.paper_key.encode("utf-8")).hexdigest()[:20]
            self.discovery_papers[iid] = paper
            imported = (paper.doi and normalize_doi(paper.doi) in existing_dois) or paper.title.casefold() in existing_titles
            access = "已在库" if imported else ("可尝试加入" if paper.downloadable else "仅元数据")
            self.discovery_tree.insert("", "end", iid=iid, values=(
                paper.title, paper.publication_date or paper.year or "—", paper.venue or "—",
                paper.cited_by_count, access,
            ))
        if papers:
            first = self.discovery_tree.get_children()[0]
            self.discovery_tree.selection_set(first)
            self.discovery_tree.focus(first)
            self._show_discovery_detail()
        else:
            self._set_discovery_detail("当前条件下没有得到推荐结果。可扩大时间范围或调整标签。")

    def _selected_discovery_paper(self) -> DiscoveryPaper | None:
        selected = self.discovery_tree.selection()
        return self.discovery_papers.get(selected[0]) if selected else None

    def _selected_discovery_library(self) -> PaperLibrary | None:
        library_id = self.library_lookup.get(self.discovery_target_combo.get()) if hasattr(self, "discovery_target_combo") else None
        return self.manager.open(library_id) if library_id else None

    def _set_discovery_detail(self, text: str) -> None:
        self.discovery_detail.configure(state="normal")
        self.discovery_detail.delete("1.0", "end")
        self.discovery_detail.insert("1.0", text)
        self.discovery_detail.configure(state="disabled")

    def _show_discovery_detail(self, _event=None) -> None:
        paper = self._selected_discovery_paper()
        if not paper:
            return
        authors = "、".join(paper.authors[:8]) or "未提供"
        if len(paper.authors) > 8:
            authors += " 等"
        self._set_discovery_detail(
            f"{paper.title}\n\n作者：{authors}\n发表：{paper.publication_date or paper.year or '未提供'}"
            f"    期刊/会议：{paper.venue or '未提供'}    OpenAlex 引用：{paper.cited_by_count}\n"
            f"推荐依据：主题相关度 {paper.relevance_score:.2f} · 新近程度 {paper.freshness_score:.2f} · "
            f"引用得分 {paper.citation_score:.2f}\n网页状态："
            f"{'已验证可访问' if paper.link_verified else '外部页面失效，查看时将打开 OpenAlex 记录'}\n"
            f"DOI：{paper.doi or '未提供'}\n\n"
            f"摘要：{paper.abstract or 'OpenAlex 未提供摘要。'}"
        )

    def _open_discovery_source(self) -> None:
        paper = self._selected_discovery_paper()
        if not paper:
            messagebox.showinfo("请选择论文", "请先在推荐列表中选择一篇论文。")
            return
        url = paper.landing_url or paper.openalex_id
        if not url:
            messagebox.showinfo("没有公开网址", "这条记录没有可打开的公开地址。")
            return
        webbrowser.open(url)

    def _copy_discovery_info(self) -> None:
        paper = self._selected_discovery_paper()
        if not paper:
            return
        url = paper.landing_url or paper.openalex_id
        self.root.clipboard_clear()
        self.root.clipboard_append(f"{paper.title}\n{url}".strip())
        self.discovery_status.configure(text="标题和链接已复制")

    def _import_discovery_paper(self) -> None:
        paper = self._selected_discovery_paper()
        library = self._selected_discovery_library()
        if not paper:
            messagebox.showinfo("请选择论文", "请先选择一篇推荐论文。")
            return
        if not library:
            messagebox.showinfo("请选择论文库", "请先新建或选择目标论文库。")
            return
        urls = list(dict.fromkeys([paper.public_url, *paper.public_urls]))
        if not urls:
            messagebox.showinfo("没有公开全文", "OpenAlex 没有为这篇论文提供可导入的公开全文地址。")
            return

        def task():
            errors: list[str] = []
            for url in urls[:5]:
                try:
                    result = library.import_url(
                        url, title_override=paper.title, authors=paper.authors, year=paper.year,
                        doi=re.sub(r"^https?://(?:dx\.)?doi\.org/", "", paper.doi, flags=re.I),
                        cited_by_count=paper.cited_by_count,
                    )
                    if result.added or result.duplicates:
                        return result
                    errors.extend(result.failures)
                except Exception as exc:
                    errors.append(str(exc))
            raise RuntimeError(errors[-1] if errors else "公开全文无法导入")

        def success(result) -> None:
            self.discovery_status.configure(text="已加入论文库" if result.added else "目标论文库中已存在")
            if self.current_library and self.current_library.info.library_id == library.info.library_id:
                self.current_library = self.manager.open(library.info.library_id)
                self._refresh_papers()
            self._render_discovery_papers(list(self.discovery_papers.values()))

        self._run_background(task, success, self.discovery_status, "正在下载公开全文并建立索引……")

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

    def _refresh_libraries(self, select_id: str | None = None) -> None:
        infos = self.manager.list()
        self.library_lookup = {f"{item.name}  [{item.library_id}]": item.library_id for item in infos}
        values = list(self.library_lookup)
        self.library_combo["values"] = values
        self._refresh_discovery_controls()
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
        self.main_notebook.select(self.library_hub_tab)
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
        self._refresh_discovery_controls()
        current_display = next((display for display, value in self.library_lookup.items() if value == library_id), "")
        if current_display:
            self.discovery_target_combo.set(current_display)
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
                self.main_notebook.select(self.library_hub_tab)
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
