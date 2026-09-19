"""Theme definitions and styling behavior for the desktop application."""

from __future__ import annotations

from tkinter import ttk

from ..ui_settings import DEFAULT_THEME, save_ui_settings


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


class ThemeMixin:
    """Own theme application without owning product or page behavior."""

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
        if hasattr(self, "home_canvas"):
            self.home_canvas.configure(background=palette["surface"])
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
            "TNotebook.Tab", background=palette["bg"], foreground=palette["muted"],
            padding=(18, 9), font=("Microsoft YaHei UI", 10, "bold"),
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
            "Chat.Horizontal.TProgressbar", troughcolor=palette["border"],
            background=palette["accent"], bordercolor=palette["border"],
            lightcolor=palette["accent"], darkcolor=palette["accent"],
        )
        if hasattr(self, "theme_var"):
            self.theme_var.set(name)
        if hasattr(self, "chat_log"):
            self._style_text_widgets()
        if persist:
            self.ui_settings["theme"] = name
            save_ui_settings(self.ui_settings_path, self.ui_settings)

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
        self.discovery_detail.configure(**common)
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
