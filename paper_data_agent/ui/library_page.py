"""Paper-library selection, import, indexing, and list UI."""

from __future__ import annotations

import os
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
import webbrowser

from ..library import PaperLibrary


class LibraryPageMixin:
    """Own the desktop paper-library page and its direct user actions.

    The host window provides background execution and chat-session restoration.
    """

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
