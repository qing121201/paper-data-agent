import json
from pathlib import Path
import tempfile
import unittest

from paper_data_agent.core import PaperAgent, PaperChunk, PaperIndex
from paper_data_agent.skills import SkillCatalog
from paper_data_agent.workflow import ResearchWorkflowAgent


def action(tool, skill="nature-paper-card", **arguments):
    return json.dumps({"tool": tool, "skill": skill, "search_query": "agent",
                       "reason": "核实相关证据", "arguments": arguments})


class ScriptedClient:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.prompts = []

    def generate(self, system, prompt, **kwargs):
        self.prompts.append((system, prompt))
        value = next(self.responses)
        if isinstance(value, Exception):
            raise value
        return value


class MultiStepTests(unittest.TestCase):
    def make_agent(self, directory):
        return PaperAgent(PaperIndex([
            PaperChunk("a", "Paper A", "a.pdf", 1, 0, "agent abstract introduction"),
            PaperChunk("a", "Paper A", "a.pdf", 3, 0, "EXPERIMENT_PAGE_COMPLETE agent accuracy 42"),
        ]), output_dir=Path(directory) / "outputs")

    def test_reads_then_drafts_then_reviews_with_real_intermediate_handoff(self):
        with tempfile.TemporaryDirectory() as directory:
            client = ScriptedClient([
                action("survey_corpus"),
                action("read_pages", title="Paper A", pages=[3]),
                action("apply_skill", "nature-writing", task="写比较草稿"),
                "DRAFT: accuracy 42 is scoped to the reported experiment.",
                action("apply_skill", "nature-reviewer", task="审查草稿是否夸大"),
                "REVIEW: do not extrapolate beyond this experiment.",
                action("finish", "nature-writing"),
                "最终回答：保留实验范围。",
            ])
            events = []
            workflow = ResearchWorkflowAgent(SkillCatalog(), client, self.make_agent(directory))
            result, _ = workflow.chat("概览论文，补读实验并写作审查", step_callback=events.append)
            self.assertEqual([step["tool"] for step in result.steps],
                             ["survey_corpus", "read_pages", "apply_skill", "apply_skill", "finish"])
            self.assertTrue(all(step["status"] == "complete" for step in result.steps))
            review_prompt = next(prompt for _, prompt in client.prompts if "# User task\n审查草稿" in prompt)
            self.assertIn("DRAFT: accuracy 42", review_prompt)
            self.assertIn("EXPERIMENT_PAGE_COMPLETE", review_prompt)
            self.assertIn("NOT source evidence", review_prompt)
            self.assertIn("REVIEW: do not extrapolate", client.prompts[-1][1])
            self.assertEqual(len(events), 10)

    def test_resume_reuses_saved_evidence_without_reading_again(self):
        with tempfile.TemporaryDirectory() as directory:
            checkpoint = Path(directory) / "in_progress.json"
            agent = self.make_agent(directory)
            first = ResearchWorkflowAgent(SkillCatalog(), ScriptedClient([
                action("read_pages", title="Paper A", pages=[3]), RuntimeError("temporary failure")
            ]), agent, checkpoint)
            with self.assertRaisesRegex(RuntimeError, "temporary failure"):
                first.chat("补读实验")
            saved = json.loads(checkpoint.read_text(encoding="utf-8"))
            self.assertEqual(saved["status"], "interrupted")
            self.assertIn("EXPERIMENT_PAGE_COMPLETE", saved["packets"][0])
            second_client = ScriptedClient([action("finish"), "实验说明"])
            second = ResearchWorkflowAgent(SkillCatalog(), second_client, agent, checkpoint)
            result, _ = second.chat("继续上次任务")
            self.assertIn("EXPERIMENT_PAGE_COMPLETE", second_client.prompts[0][1])
            self.assertEqual(sum(step["tool"] == "read_pages" for step in result.steps), 1)

    def test_duplicate_action_stops_and_preserves_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            checkpoint = Path(directory) / "in_progress.json"
            workflow = ResearchWorkflowAgent(SkillCatalog(), ScriptedClient([
                action("survey_corpus"), action("survey_corpus")
            ]), self.make_agent(directory), checkpoint)
            with self.assertRaisesRegex(ValueError, "重复"):
                workflow.chat("概览")
            self.assertTrue(json.loads(checkpoint.read_text(encoding="utf-8"))["packets"])

    def test_missing_page_is_not_claimed_as_read(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.make_agent(directory).run("read_pages", title="Paper A", pages=[99])
            self.assertIn("未读取", result)
            with self.assertRaises(ValueError):
                self.make_agent(directory).run("read_pages", title="unknown", pages=[1])

    def test_search_and_import_is_an_executable_terminal_action(self):
        with tempfile.TemporaryDirectory() as directory:
            agent = PaperAgent(PaperIndex([]), output_dir=Path(directory) / "outputs",
                               online_importer=lambda query, top_k=5, **kwargs: f"IMPORTED {top_k}: {query}")
            client = ScriptedClient([
                json.dumps({"tool": "search_and_import", "skill": "nature-academic-search",
                            "search_query": "virtual cell", "reason": "检索并导入", "arguments": {"top_k": 3}}),
                "已导入三篇公开论文。",
            ])
            workflow = ResearchWorkflowAgent(SkillCatalog(), client, agent)
            request = "我要开始研究虚拟细胞，先替这个空库准备三篇最合适的公开论文"
            result, plan = workflow.chat(request)
            self.assertEqual(plan.tool, "search_and_import")
            self.assertIn("IMPORTED 3: virtual cell", result.evidence_brief)
            self.assertIn("IMPORTED 3: virtual cell", result.answer)
            self.assertEqual(len(client.prompts), 1)
            self.assertIn("current local paper library is empty", client.prompts[0][1])
            self.assertIn(request, client.prompts[0][1])

    def test_ambiguous_review_can_pause_for_confirmation_before_reading(self):
        with tempfile.TemporaryDirectory() as directory:
            client = ScriptedClient([
                action(
                    "clarify",
                    "nature-writing",
                    question="你希望采用哪种阅读深度？",
                    options=["全库摘要 + 核心论文全文", "全部论文全文", "仅摘要"],
                    recommended="先覆盖全库摘要，再完整阅读核心论文。",
                )
            ])
            workflow = ResearchWorkflowAgent(SkillCatalog(), client, self.make_agent(directory))
            progress = []
            result, plan = workflow.chat("给我写一篇完整综述", progress_callback=lambda v, t: progress.append((v, t)))
            self.assertEqual(plan.tool, "clarify")
            self.assertEqual(result.steps[0]["status"], "waiting_confirmation")
            self.assertIn("你希望采用哪种阅读深度", result.answer)
            self.assertIn("全库摘要 + 核心论文全文", result.answer)
            self.assertEqual(len(client.prompts), 1)
            self.assertEqual(progress[-1], (100, "等待你确认阅读方案"))

    def test_confirmed_plan_can_read_complete_paper_then_write(self):
        with tempfile.TemporaryDirectory() as directory:
            client = ScriptedClient([
                action("survey_corpus", "nature-writing"),
                action("read_full_papers", "nature-reader", titles=["Paper A"], evidence_token_budget=1000),
                action("apply_skill", "nature-writing", task="按已确认范围写综述"),
                "综述草稿",
                action("finish", "nature-writing"),
                "最终综述",
            ])
            workflow = ResearchWorkflowAgent(SkillCatalog(), client, self.make_agent(directory))
            history = [
                {"role": "user", "content": "给我写完整综述"},
                {"role": "assistant", "content": "建议全库摘要加核心论文全文。"},
                {"role": "user", "content": "按推荐方案做。"},
            ]
            result, _plan = workflow.chat("按推荐方案做。", history=history)
            self.assertEqual(
                [step["tool"] for step in result.steps],
                ["survey_corpus", "read_full_papers", "apply_skill", "finish"],
            )
            self.assertIn("EXPERIMENT_PAGE_COMPLETE", result.evidence_brief)
            self.assertIn("按推荐方案做", client.prompts[0][1])
