"""LLM plan parsing, checkpoint writing, and next-action selection."""

from __future__ import annotations

import json
import re
from typing import Any

from .models import AgentPlan


class PlanningMixin:
    """Provide planning behavior to the composed research workflow agent."""

    def _evidence(self, query: str, top_k: int) -> str:
        if not self.paper_agent:
            return "No local paper index was supplied."
        return self.paper_agent.run("build_brief", query=query, top_k=top_k)

    @staticmethod
    def _parse_plan(text: str) -> dict[str, Any]:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE)
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start < 0 or end < start:
            raise ValueError("planner did not return a JSON object")
        payload = json.loads(cleaned[start : end + 1])
        if not isinstance(payload, dict):
            raise ValueError("planner result must be an object")
        result: dict[str, Any] = {
            key: str(payload.get(key, "")).strip()
            for key in ("tool", "skill", "search_query", "reason")
        }
        result["arguments"] = payload.get("arguments") if isinstance(payload.get("arguments"), dict) else {}
        return result

    def _checkpoint(self, status: str, **payload: Any) -> None:
        if self.checkpoint_path is None:
            return
        self.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        data = {"status": status, **payload}
        self.checkpoint_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    def plan(self, query: str, history: list[dict[str, str]] | None = None) -> AgentPlan:
        if self.client is None:
            raise ValueError("LLM client is required for autonomous planning")
        history_text = "\n".join(
            f"{item.get('role', 'user')}: {item.get('content', '')[:1200]}"
            for item in (history or [])[-6:]
        )
        skill_names = ", ".join(item.name for item in self.catalog.discover())
        system = self.PLANNER_PROMPT.format(skills=skill_names)
        paper_count = len({chunk.paper_id or chunk.path for chunk in self.paper_agent.index.chunks}) if self.paper_agent else 0
        library_status = (
            "The current local paper library is empty. Interpret the user's complete natural-language intent. "
            "If they want papers obtained or added, choose search_and_import; do not require fixed keywords. "
            "Do not choose local reading tools until papers exist."
            if paper_count == 0 else f"The current local paper library contains {paper_count} indexed papers."
        )
        raw = self.client.generate(
            system,
            f"Local library status:\n{library_status}\n\nConversation:\n{history_text}\n\nLatest user task:\n{query}",
            reasoning_effort="high",
            max_output_tokens=8192,
        )
        payload = self._parse_plan(raw)
        allowed_tools = {
            "clarify", "search_papers", "build_brief", "survey_corpus", "online_search", "search_and_import",
            "create_scientific_figure", "create_presentation", "none",
            "create_mindmap", "read_pages", "read_full_papers", "apply_skill", "finish",
        }
        if payload["tool"] not in allowed_tools:
            raise ValueError(f"planner selected unknown tool: {payload['tool']}")
        installed = {item.name for item in self.catalog.discover()}
        if payload["skill"] not in installed:
            raise ValueError(f"planner selected unknown skill: {payload['skill']}")
        search_query = payload["search_query"]
        if payload["tool"] in {"search_papers", "build_brief", "online_search", "search_and_import"} and not search_query:
            raise ValueError("检索步骤缺少明确查询词，进度已保存")
        plan = AgentPlan(
            payload["tool"], payload["skill"], search_query, payload["reason"], payload["arguments"]
        )
        return plan
