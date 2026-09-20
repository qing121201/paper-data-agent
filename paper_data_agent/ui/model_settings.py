"""Model status and OpenAI-compatible API configuration dialog."""

from __future__ import annotations

import threading
import tkinter as tk
from tkinter import messagebox, ttk

from ..config import apply_config, llm_ready, save_config
from ..llm import LLMConfig, OpenAICompatibleClient
from ..providers import PROVIDER_BY_NAME, PROVIDER_PRESETS, detect_provider
from .theme import THEMES


class ModelSettingsMixin:
    """Own model status display, connection testing, and local configuration."""

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
                    save_config(self.config_path, config)
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
