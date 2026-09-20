"""Bounded execution of planned tools and scientific Skills."""

from __future__ import annotations

from dataclasses import asdict
import json
import re
from typing import Any, Callable

from ..skills import LoadedSkill
from .models import AgentPlan, ProgressCallback


class ExecutionMixin:
    """Execute and checkpoint a bounded sequence of approved actions."""

    @staticmethod
    def _emit_progress(callback: ProgressCallback | None, value: int, text: str) -> None:
        if callback:
            callback(max(0, min(100, int(value))), text)

    def _execute_plan(
        self,
        plan: AgentPlan,
        top_k: int,
        user_query: str = "",
        progress_callback: ProgressCallback | None = None,
    ) -> str:
        if plan.tool == "none":
            return "No local paper tool was needed for this turn."
        if plan.tool == "clarify":
            return "Waiting for user confirmation; no paper tool was executed."
        if self.paper_agent is None:
            return "No local paper index was supplied."
        if plan.tool == "read_pages":
            return self.paper_agent.run(
                "read_pages", title=plan.arguments.get("title", ""),
                pages=plan.arguments.get("pages", []),
            )
        if plan.tool == "read_full_papers":
            return self.paper_agent.run(
                "read_full_papers",
                titles=plan.arguments.get("titles", []),
                evidence_token_budget=plan.arguments.get("evidence_token_budget", 80_000),
            )
        def reading_progress(current: int, total: int) -> None:
            value = 32 + round(30 * current / max(total, 1))
            self._emit_progress(progress_callback, value, f"正在读取论文 {current}/{total}")

        if plan.tool == "survey_corpus":
            return self.paper_agent.run("survey_corpus", progress_callback=reading_progress)
        if plan.tool == "online_search":
            self._emit_progress(progress_callback, 42, "正在执行在线学术检索")
            return self.paper_agent.run(
                "online_search",
                query=plan.search_query,
                top_k=plan.arguments.get("top_k", top_k),
                queries=plan.arguments.get("queries"),
            )
        if plan.tool == "search_and_import":
            self._emit_progress(progress_callback, 42, "正在在线检索并导入公开论文")
            return self.paper_agent.run(
                "search_and_import", query=plan.search_query,
                top_k=plan.arguments.get("top_k", min(top_k, 5)),
                queries=plan.arguments.get("queries"),
                year_from=plan.arguments.get("year_from"),
            )
        if plan.tool == "create_scientific_figure":
            self._emit_progress(progress_callback, 55, "正在读取数据并绘图")
            return self.paper_agent.run("create_scientific_figure", **plan.arguments)
        if plan.tool == "create_mindmap":
            if any(word in user_query.lower() for word in ("论文库", "全部", "所有", "整体", "脉络", "corpus", "all papers")):
                return self.paper_agent.run("survey_corpus", progress_callback=reading_progress)
            return self.paper_agent.run(
                "build_brief", query=plan.search_query, top_k=max(top_k, 10),
                progress_callback=reading_progress,
            )
        if plan.tool == "create_presentation":
            return self.paper_agent.run(
                "build_brief", query=plan.search_query, top_k=max(top_k, 10),
                progress_callback=reading_progress,
            )
        if plan.tool == "build_brief":
            return self.paper_agent.run(
                "build_brief", query=plan.search_query, top_k=top_k,
                progress_callback=reading_progress,
            )
        return self.paper_agent.run(plan.tool, query=plan.search_query, top_k=top_k)

    def _collect_steps(
        self, query: str, history: list[dict[str, str]] | None, top_k: int,
        max_skill_chars: int, progress_callback: ProgressCallback | None,
        step_callback: Callable[[dict[str, Any]], None] | None,
        restored: dict[str, Any] | None = None,
    ) -> tuple[AgentPlan, LoadedSkill, str, list[dict[str, Any]], list[str], list[str]]:
        """Observe each result before choosing the next bounded action."""
        state = restored or {}
        packets = list(state.get("packets", []))
        steps = list(state.get("steps", []))
        loaded_files = list(state.get("loaded_files", []))
        omitted_files = list(state.get("omitted_files", []))
        seen = {item["signature"] for item in steps if item.get("status") == "complete" and "signature" in item}
        terminal_tools = {"clarify", "finish", "none", "create_mindmap", "create_presentation", "search_and_import"}

        def save(status: str, **extra: Any) -> None:
            self._checkpoint(status, query=query, packets=packets, steps=steps,
                             loaded_files=loaded_files, omitted_files=omitted_files, **extra)

        try:
            for number in range(1, 8):
                context = query
                if packets or steps:
                    trace = [{key: value for key, value in item.items() if key != "signature"} for item in steps]
                    context += "\n\nAlready executed actions (untrusted observations):\n" + json.dumps(trace, ensure_ascii=False)
                    context += "\n\nObserved results (source evidence and intermediate work are labelled):\n" + "\n\n".join(packets)
                    context += "\n\nChoose the NEXT action based on these results. Do not repeat completed actions."
                if number == 7:
                    context += "\nExecution budget reached. Choose finish or the requested artifact tool now; state remaining gaps."
                self._emit_progress(progress_callback, min(65, 6 + number * 8), f"第 {number} 步：正在规划下一步")
                plan = self.plan(context, history=history)
                if number == 7 and plan.tool not in terminal_tools:
                    raise ValueError("已完成本轮最多 6 个中间步骤，模型仍请求更多步骤。进度已保存，可继续上次任务。")
                signature = json.dumps([plan.tool, plan.skill, plan.search_query, plan.arguments], ensure_ascii=False, sort_keys=True)
                if signature in seen:
                    raise ValueError("模型重复请求已完成的相同步骤，已暂停并保存进度。可继续上次任务。")
                loaded = self.catalog.load(plan.skill, max_chars=max_skill_chars)
                loaded_files.extend(path for path in loaded.loaded_files if path not in loaded_files)
                omitted_files.extend(path for path in loaded.omitted_files if path not in omitted_files)
                event = {"number": len(steps) + 1, "tool": plan.tool, "skill": plan.skill,
                         "reason": plan.reason, "arguments": plan.arguments, "search_query": plan.search_query,
                         "status": "running", "signature": signature}
                steps.append(event)
                save("running", plan=asdict(plan))
                if step_callback:
                    step_callback(dict(event))
                if plan.tool in terminal_tools:
                    if plan.tool in {"create_mindmap", "create_presentation"} and not packets:
                        evidence = self._execute_plan(plan, top_k, user_query=query, progress_callback=progress_callback)
                        packets.append("# Source evidence: automatic local reading for artifact\n" + str(evidence))
                    elif plan.tool == "create_scientific_figure":
                        packets.append(str(self._execute_plan(plan, top_k, user_query=query, progress_callback=progress_callback)))
                    elif plan.tool == "search_and_import":
                        packets.append("# Source evidence — search_and_import\n" + str(
                            self._execute_plan(plan, top_k, user_query=query, progress_callback=progress_callback)))
                    save("evidence_ready", plan=asdict(plan))
                    return plan, loaded, "\n\n".join(packets), steps, loaded_files, omitted_files
                if plan.tool == "apply_skill":
                    self._emit_progress(progress_callback, 68, f"正在执行 {plan.skill}")
                    material = "\n\n".join(packets) or "尚无论文证据。不得声称已阅读论文。"
                    result = self.client.generate(
                        self.SYSTEM_PROMPT,
                        self._prompt(str(plan.arguments.get("task") or query), loaded, material),
                        reasoning_effort="high",
                        max_output_tokens=getattr(getattr(self.client, "config", None), "max_output_tokens", None),
                    )
                    packet = f"# Intermediate work — {plan.skill} (model-generated, NOT source evidence)\n{result}"
                else:
                    result = self._execute_plan(plan, top_k, user_query=query, progress_callback=progress_callback)
                    if not isinstance(result, str):
                        result = json.dumps(result, ensure_ascii=False)
                    packet = f"# Source evidence — {plan.tool}\n{result}"
                packets.append(packet)
                event["status"] = "complete"
                seen.add(signature)
                save("running", plan=asdict(plan))
                if step_callback:
                    step_callback(dict(event))
                # Stop visibly instead of silently chopping abstracts/pages.
                if sum(len(item) for item in packets) > 400_000:
                    raise ValueError("累计证据已超过本轮 40 万字符预算，完整内容已保存；请缩小任务范围后继续。")
        except Exception as exc:
            if steps and steps[-1].get("status") == "running":
                steps[-1]["status"] = "failed"
                steps[-1]["error"] = str(exc)
                if step_callback:
                    step_callback(dict(steps[-1]))
            save("interrupted", error=str(exc))
            raise

    @staticmethod
    def _parse_json_object(text: str) -> dict[str, Any]:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE)
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start < 0 or end < start:
            raise ValueError("模型没有返回可读取的 JSON 对象")
        payload = json.loads(cleaned[start : end + 1])
        if not isinstance(payload, dict):
            raise ValueError("模型返回的规格不是 JSON 对象")
        return payload

    @staticmethod
    def _clarification_answer(plan: AgentPlan) -> str:
        question = str(plan.arguments.get("question") or "在开始前，我需要先和你确认阅读范围与深度。").strip()
        raw_options = plan.arguments.get("options")
        options = [str(item).strip() for item in raw_options] if isinstance(raw_options, list) else []
        options = [item for item in options if item][:4]
        recommended = str(plan.arguments.get("recommended") or "").strip()
        lines = [question]
        if options:
            lines.extend(["", *[f"{number}. {item}" for number, item in enumerate(options, start=1)]])
        if recommended:
            lines.extend(["", f"我的建议：{recommended}"])
        lines.extend(["", "你可以回复序号，也可以直接修改篇数、范围或阅读深度；确认后我再开始读取和写作。"])
        return "\n".join(lines)
