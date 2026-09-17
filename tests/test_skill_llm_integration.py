import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import tempfile
import threading
import unittest

from paper_data_agent.core import PaperAgent, PaperChunk, PaperIndex
from paper_data_agent.llm import LLMConfig, LLMTruncatedError, OpenAICompatibleClient
from paper_data_agent.skills import SELECTED_SKILLS, SkillCatalog
from paper_data_agent.workflow import (
    ResearchWorkflowAgent,
    coverage_note,
    prettify_paper_references,
    remove_reading_process_branches,
    route_skill,
)


class _MockHandler(BaseHTTPRequestHandler):
    paths: list[str] = []
    bodies: list[dict] = []
    scripted_responses: list[object] = []

    def do_POST(self) -> None:  # noqa: N802 - stdlib callback name
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length).decode("utf-8"))
        self.__class__.paths.append(self.path)
        self.__class__.bodies.append(body)
        scripted = self.__class__.scripted_responses.pop(0) if self.__class__.scripted_responses else ""
        if isinstance(scripted, dict):
            payload = scripted
        elif self.path.endswith("/responses"):
            payload = {"output_text": scripted or "responses-ok"}
        else:
            payload = {"choices": [{"message": {"content": scripted or "chat-ok"}}]}
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format: str, *args: object) -> None:
        return


class MockEndpoint:
    def __enter__(self) -> str:
        _MockHandler.paths.clear()
        _MockHandler.bodies.clear()
        _MockHandler.scripted_responses.clear()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _MockHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        host, port = self.server.server_address
        return f"http://{host}:{port}/v1"

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


def _write_skill(root: Path, name: str) -> None:
    package = root / name
    package.mkdir(parents=True)
    (package / "SKILL.md").write_text(
        f'---\nname: {name}\ndescription: "test workflow"\n---\n\n# Workflow\nPreserve sources.',
        encoding="utf-8",
    )
    (package / "manifest.yaml").write_text("name: test\nalways_load: []\n", encoding="utf-8")


class LLMClientTests(unittest.TestCase):
    def test_responses_protocol(self) -> None:
        with MockEndpoint() as base_url:
            client = OpenAICompatibleClient(
                LLMConfig(base_url, "test-model", "test-key", "responses")
            )
            self.assertEqual(client.generate("system", "user"), "responses-ok")
            self.assertEqual(_MockHandler.paths, ["/v1/responses"])
            self.assertEqual(_MockHandler.bodies[0]["instructions"], "system")
            self.assertFalse(_MockHandler.bodies[0]["store"])

    def test_chat_completions_protocol(self) -> None:
        with MockEndpoint() as base_url:
            client = OpenAICompatibleClient(
                LLMConfig(base_url, "local-model", "", "chat_completions")
            )
            self.assertEqual(client.generate("system", "user"), "chat-ok")
            self.assertEqual(_MockHandler.paths, ["/v1/chat/completions"])
            self.assertEqual(_MockHandler.bodies[0]["messages"][1]["content"], "user")

    def test_deepseek_payload_controls_thinking_and_output_limit(self) -> None:
        client = OpenAICompatibleClient(
            LLMConfig("https://api.deepseek.com", "deepseek-flash", "test-key")
        )
        planning = client._chat_payload("system", "user", 1200, "none")
        answering = client._chat_payload("system", "user", 4096, "low")
        self.assertEqual(planning["thinking"], {"type": "disabled"})
        self.assertEqual(planning["reasoning_effort"], "none")
        self.assertEqual(answering["thinking"], {"type": "enabled"})
        self.assertEqual(answering["reasoning_effort"], "low")
        self.assertEqual(answering["max_tokens"], 4096)

    def test_auto_output_omits_max_tokens(self) -> None:
        client = OpenAICompatibleClient(
            LLMConfig("https://api.deepseek.com", "deepseek-flash", "test-key", max_output_tokens=None)
        )
        payload = client._chat_payload("system", "user", None, "high")
        self.assertNotIn("max_tokens", payload)
        self.assertEqual(payload["reasoning_effort"], "high")

    def test_empty_reasoning_response_has_actionable_error(self) -> None:
        payload = {
            "choices": [{
                "finish_reason": "length",
                "message": {"content": None, "reasoning_content": "still reasoning"},
            }]
        }
        with self.assertRaisesRegex(Exception, "推理阶段用完了输出额度"):
            OpenAICompatibleClient._chat_text(payload)

    def test_partial_length_response_is_not_silently_accepted(self) -> None:
        payload = {
            "choices": [{
                "finish_reason": "length",
                "message": {"content": "回答的前半段", "reasoning_content": "thinking"},
            }]
        }
        with self.assertRaises(LLMTruncatedError) as caught:
            OpenAICompatibleClient._chat_text(payload)
        self.assertEqual(caught.exception.partial_text, "回答的前半段")

    def test_chat_completion_auto_continues_after_length_cutoff(self) -> None:
        with MockEndpoint() as base_url:
            _MockHandler.scripted_responses.extend([
                {
                    "choices": [{
                        "finish_reason": "length",
                        "message": {"content": "第一部分", "reasoning_content": "thinking"},
                    }]
                },
                {
                    "choices": [{
                        "finish_reason": "stop",
                        "message": {"content": "第二部分"},
                    }]
                },
            ])
            client = OpenAICompatibleClient(
                LLMConfig(base_url, "local-model", "", "chat_completions")
            )
            self.assertEqual(client.generate("system", "user"), "第一部分\n\n第二部分")
            self.assertEqual(len(_MockHandler.bodies), 2)
            self.assertIn("从截断处继续", _MockHandler.bodies[1]["messages"][-1]["content"])


class SkillWorkflowTests(unittest.TestCase):
    def test_mindmap_process_branch_is_removed_and_references_are_prettified(self) -> None:
        markdown = """# 研究脉络
- 阅读覆盖与证据边界
  - 读取 37 篇
- 方法演进
  - #24 提出代码智能体
"""
        cleaned = prettify_paper_references(remove_reading_process_branches(markdown))
        self.assertNotIn("阅读覆盖", cleaned)
        self.assertNotIn("读取 37 篇", cleaned)
        self.assertIn("方法演进", cleaned)
        self.assertIn("〔论文 24〕", cleaned)

    def test_coverage_note_is_separate_plain_language(self) -> None:
        evidence = (
            "- 论文库总数：37 篇；实际读取：37 篇；预算不足未读：0 篇。\n"
            "- 完整摘要：30 篇；无法可靠识别摘要边界而改读完整首页/前两页：7 篇。"
        )
        note = coverage_note(evidence)
        self.assertIn("本次阅读说明", note)
        self.assertIn("30 篇读取完整摘要", note)
        self.assertIn("不写入思维导图", note)

    def test_catalog_and_dry_run_include_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_skill(root, "nature-paper-card")
            catalog = SkillCatalog(root)
            self.assertEqual(catalog.discover()[0].name, "nature-paper-card")
            index = PaperIndex(
                [PaperChunk("swe", "SWE-agent", "swe.pdf", 3, 0, "agent computer interface")]
            )
            workflow = ResearchWorkflowAgent(catalog, paper_agent=PaperAgent(index))
            result = workflow.run("精读 agent interface", dry_run=True)
            self.assertEqual(result.skill, "nature-paper-card")
            self.assertIn("SWE-agent", result.answer)
            self.assertIn("Preserve sources", result.answer)

    def test_router_covers_named_artifact_skills(self) -> None:
        cases = {
            "把截图还原成可编辑 PPT": "nature-image2ppt",
            "审查样本量和 p value": "nature-statistics",
            "帮我做论文配图": "nature-figure",
            "精读这篇论文并制作证据卡": "nature-paper-card",
            "核验 SWE-agent 论文参考文献信息": "nature-ref-verifier",
            "帮我写综述的相关工作": "nature-writing",
            "以 reviewer 视角进行投稿前自审": "nature-reviewer",
            "润色这段英文": "nature-polishing",
            "生成全文中英对照": "nature-reader",
            "在线查文献": "nature-academic-search",
            "生成组会PPT": "nature-paper2ppt",
            "帮我探索一个研究选题": "research-explorer",
            "生成完整实验方案": "experiment-suite",
            "审计论文的数据与图片完整性": "integrity-auditor",
            "把论文脉络做成思维导图": "mindmap-render",
        }
        for query, expected in cases.items():
            with self.subTest(query=query):
                self.assertEqual(route_skill(query), expected)
        installed = {item.name for item in SkillCatalog().discover()}
        self.assertEqual(installed, set(SELECTED_SKILLS))

    def test_ai4s_reference_files_are_loaded(self) -> None:
        loaded = SkillCatalog().load("experiment-suite")
        self.assertTrue(any("references" in item for item in loaded.loaded_files))

    def test_autonomous_chat_selects_corpus_tool_and_skill(self) -> None:
        class FakeClient:
            def __init__(self) -> None:
                self.responses = [
                    json.dumps(
                        {
                            "tool": "survey_corpus",
                            "skill": "nature-writing",
                            "search_query": "software engineering agents",
                            "reason": "需要先查看全部论文再归纳主题",
                        },
                        ensure_ascii=False,
                    ),
                    json.dumps({"tool": "finish", "skill": "nature-writing", "reason": "证据足够", "arguments": {}}),
                    "这批论文主要讨论软件工程智能体。",
                ]

            def generate(self, system_prompt: str, user_prompt: str, **_options) -> str:
                return self.responses.pop(0)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_skill(root, "nature-writing")
            index = PaperIndex(
                [PaperChunk("swe", "SWE-agent", "swe.pdf", 1, 0, "software engineering agent")]
            )
            workflow = ResearchWorkflowAgent(
                SkillCatalog(root), client=FakeClient(), paper_agent=PaperAgent(index)
            )
            progress: list[tuple[int, str]] = []
            result, plan = workflow.chat(
                "这批论文在讲什么？",
                progress_callback=lambda value, text: progress.append((value, text)),
            )
            self.assertEqual(plan.tool, "finish")
            self.assertEqual(result.steps[0]["tool"], "survey_corpus")
            self.assertEqual(plan.skill, "nature-writing")
            self.assertIn("SWE-agent", result.evidence_brief)
            self.assertIn("软件工程智能体", result.answer)
            self.assertTrue(any("正在读取论文 1/1" in text for _value, text in progress))
            self.assertEqual(progress[-1], (100, "完成"))

    def test_autonomous_chat_over_http_mock(self) -> None:
        with tempfile.TemporaryDirectory() as directory, MockEndpoint() as base_url:
            root = Path(directory)
            _write_skill(root, "nature-writing")
            _MockHandler.scripted_responses.extend(
                [
                    json.dumps(
                        {
                            "tool": "survey_corpus",
                            "skill": "nature-writing",
                            "search_query": "software engineering agents",
                            "reason": "概览全部论文",
                        },
                        ensure_ascii=False,
                    ),
                    json.dumps({"tool": "finish", "skill": "nature-writing", "reason": "证据足够", "arguments": {}}),
                    "HTTP mock final answer",
                ]
            )
            client = OpenAICompatibleClient(
                LLMConfig(base_url, "test-model", "test-key", "responses")
            )
            index = PaperIndex(
                [PaperChunk("swe", "SWE-agent", "swe.pdf", 1, 0, "software engineering agent")]
            )
            workflow = ResearchWorkflowAgent(
                SkillCatalog(root), client=client, paper_agent=PaperAgent(index)
            )
            result, plan = workflow.chat("这批论文在讲什么？")
            self.assertEqual(result.answer, "HTTP mock final answer")
            self.assertEqual(plan.tool, "finish")
            self.assertEqual(_MockHandler.paths, ["/v1/responses"] * 3)


if __name__ == "__main__":
    unittest.main()
