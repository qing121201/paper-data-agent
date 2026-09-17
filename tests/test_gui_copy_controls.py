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


if __name__ == "__main__":
    unittest.main()
