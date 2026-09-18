import tkinter as tk
import unittest

from paper_data_agent.gui import PaperAgentGUI


class GuiCopyControlTests(unittest.TestCase):
    def setUp(self) -> None:
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk unavailable: {exc}")
        self.root.withdraw()
        self.gui = PaperAgentGUI(self.root)
        self.root.update_idletasks()

    def tearDown(self) -> None:
        if hasattr(self, "root"):
            self.root.destroy()

    def test_paper_list_exposes_path_and_copy_controls(self) -> None:
        self.assertEqual(tuple(self.gui.paper_tree["columns"]), ("title", "type", "path", "source"))
        def descendants(widget):
            for child in widget.winfo_children():
                yield child
                yield from descendants(child)
        button_texts = {str(widget.cget("text")) for widget in descendants(self.gui.import_tab)
                        if "text" in widget.keys()}
        self.assertTrue({
            "复制论文标题", "复制本地路径", "复制整行",
            "建立/更新向量索引", "从论文库移除",
        } <= button_texts)
        children = self.gui.paper_tree.get_children()
        if not children:
            self.skipTest("No paper records available for clipboard smoke test")
        self.gui.paper_tree.selection_set(children[0])
        record = self.gui._selected_paper_record()
        self.assertIsNotNone(record)
        self.gui._copy_selected_title()
        self.assertEqual(self.root.clipboard_get(), record.title)
        self.gui._copy_selected_path()
        self.assertEqual(self.root.clipboard_get(), record.local_path)

    def test_markdown_table_cells_are_selectable_text_widgets(self) -> None:
        self.gui._insert_table((("论文", "结论"), ("Paper A", "Result A")))
        self.root.update_idletasks()
        self.assertGreaterEqual(len(self.gui._table_cells), 4)
        cell = self.gui._table_cells[-1][1]
        self.assertIsInstance(cell, tk.Text)
        self.assertEqual(cell.get("1.0", "end-1c"), "Result A")
        self.assertEqual(str(cell.cget("state")), "disabled")

    def test_home_and_library_are_separate_top_level_sections(self) -> None:
        top_tabs = [self.gui.main_notebook.tab(index, "text")
                    for index in range(self.gui.main_notebook.index("end"))]
        library_tabs = [self.gui.notebook.tab(index, "text")
                        for index in range(self.gui.notebook.index("end"))]
        self.assertEqual(top_tabs, ["首页", "我的论文库", "使用说明"])
        self.assertEqual(library_tabs, ["论文导入", "与 Agent 对话", "PPT 预览与修改"])
        self.assertEqual(self.gui.main_notebook.select(), str(self.gui.home_tab))

    def test_home_exposes_common_research_topics(self) -> None:
        def descendants(widget):
            for child in widget.winfo_children():
                yield child
                yield from descendants(child)
        texts = {str(widget.cget("text")) for widget in descendants(self.gui.home_tab)
                 if "text" in widget.keys()}
        self.assertTrue({"AI Agent", "大语言模型", "多模态学习", "虚拟细胞", "具身智能"} <= texts)


if __name__ == "__main__":
    unittest.main()
