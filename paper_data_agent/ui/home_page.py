"""Home and daily paper discovery UI for the desktop application."""

from __future__ import annotations

from datetime import datetime
import hashlib
import re
import threading
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk
from tkinter.scrolledtext import ScrolledText
import webbrowser

from ..discovery import (
    DiscoveryPaper,
    DiscoverySubscription,
    SORT_COMBINED,
    SORT_MODES,
)
from ..library import PaperLibrary


class HomePageMixin:
    """Build and coordinate the discovery home page.

    The host window provides library selection, background-task execution,
    clipboard helpers, and configured discovery services.
    """

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
