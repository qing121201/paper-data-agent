from __future__ import annotations

import os
from pathlib import Path
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from .config import apply_config, llm_ready, load_local_config, save_config
from .library import LibraryManager, PaperLibrary
from .llm import LLMConfig, LLMError, OpenAICompatibleClient
from .providers import PROVIDER_BY_NAME, PROVIDER_PRESETS, detect_provider
from .skills import SkillCatalog
from .ui_settings import DEFAULT_THEME, load_ui_settings
from .ui.chat_page import ChatPageMixin
from .ui.home_page import HomePageMixin
from .ui.library_page import LibraryPageMixin
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


class PaperAgentGUI(ThemeMixin, HomePageMixin, LibraryPageMixin, ChatPageMixin):
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
