"""Agent chat page, transcript rendering, and research-task interaction."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
import json
import math
import tkinter as tk
from tkinter import messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from ..config import llm_ready
from ..core import PaperAgent, PaperIndex
from ..library import PaperLibrary
from ..llm import LLMConfig, OpenAICompatibleClient
from ..markdown_render import inline_segments, parse_markdown_blocks
from ..ui.theme import THEMES
from ..workflow import ResearchWorkflowAgent


class ChatPageMixin:
    """Own chat widgets, transcript rendering, and workflow execution.

    The host window provides library selection, background execution, and page
    navigation shared with the rest of the desktop application.
    """

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
