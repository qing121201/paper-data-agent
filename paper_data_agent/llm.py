from __future__ import annotations

import json
import os
import base64
import mimetypes
from pathlib import Path
from dataclasses import dataclass
from typing import Any
from urllib import error, request


class LLMError(RuntimeError):
    """Raised when an OpenAI-compatible endpoint cannot return usable text."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class LLMTruncatedError(LLMError):
    """Raised when a chat response contains text but stops at the token limit."""

    def __init__(self, partial_text: str, reasoning_content: str = ""):
        super().__init__("模型回答达到本次输出上限。")
        self.partial_text = partial_text
        self.reasoning_content = reasoning_content


@dataclass(slots=True)
class LLMConfig:
    base_url: str
    model: str
    api_key: str = ""
    api_style: str = "auto"
    timeout_seconds: float = 90.0
    max_output_tokens: int | None = None

    @classmethod
    def from_env(cls) -> "LLMConfig":
        return cls(
            base_url=os.getenv("PAPER_AGENT_BASE_URL", "https://api.openai.com/v1"),
            model=os.getenv("PAPER_AGENT_MODEL", ""),
            api_key=os.getenv("PAPER_AGENT_API_KEY", os.getenv("OPENAI_API_KEY", "")),
            api_style=os.getenv("PAPER_AGENT_API_STYLE", "auto"),
            timeout_seconds=float(os.getenv("PAPER_AGENT_TIMEOUT", "90")),
            max_output_tokens=cls._output_limit_from_env(),
        )

    @staticmethod
    def _output_limit_from_env() -> int | None:
        raw = os.getenv("PAPER_AGENT_MAX_OUTPUT_TOKENS", "").strip().lower()
        if raw in {"", "auto", "none"}:
            return None
        return int(raw)

    def validate(self) -> None:
        if not self.base_url.startswith(("http://", "https://")):
            raise ValueError("PAPER_AGENT_BASE_URL must be an http(s) URL")
        if not self.model:
            raise ValueError("PAPER_AGENT_MODEL is required for online generation")
        if self.api_style not in {"auto", "responses", "chat_completions"}:
            raise ValueError("PAPER_AGENT_API_STYLE must be auto, responses, or chat_completions")
        if "api.openai.com" in self.base_url and not self.api_key:
            raise ValueError("PAPER_AGENT_API_KEY or OPENAI_API_KEY is required for api.openai.com")


class OpenAICompatibleClient:
    """Small HTTP client for OpenAI Responses and Chat Completions APIs.

    It intentionally avoids an SDK dependency so the demo also works with local
    OpenAI-compatible servers. API keys are read from the environment and are
    never included in generated artifacts or exception messages.
    """

    def __init__(self, config: LLMConfig):
        config.validate()
        self.config = config

    def _post(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.config.base_url.rstrip('/')}/{endpoint.lstrip('/')}"
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        http_request = request.Request(url, data=body, headers=headers, method="POST")
        try:
            with request.urlopen(http_request, timeout=self.config.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise LLMError(f"LLM endpoint returned HTTP {exc.code}: {detail}", exc.code) from exc
        except (error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise LLMError(f"LLM request failed: {exc}") from exc

    @staticmethod
    def _responses_text(payload: dict[str, Any]) -> str:
        if isinstance(payload.get("output_text"), str) and payload["output_text"].strip():
            return payload["output_text"].strip()
        pieces: list[str] = []
        for item in payload.get("output", []):
            for content in item.get("content", []):
                if content.get("type") == "output_text" and isinstance(content.get("text"), str):
                    pieces.append(content["text"])
        return "\n".join(pieces).strip()

    @staticmethod
    def _chat_text(payload: dict[str, Any]) -> str:
        try:
            choice = payload["choices"][0]
            message = choice["message"]
            content = message["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError("模型返回格式中没有可读取的回答内容。") from exc
        text = ""
        if isinstance(content, str):
            text = content.strip()
        elif isinstance(content, list):
            text = "\n".join(
                item.get("text", "") for item in content if isinstance(item, dict)
            ).strip()
        finish_reason = choice.get("finish_reason")
        reasoning = message.get("reasoning_content")
        if finish_reason == "length":
            if text:
                raise LLMTruncatedError(
                    text,
                    reasoning if isinstance(reasoning, str) else "",
                )
            raise LLMError(
                "模型在推理阶段用完了输出额度，尚未生成最终回答。"
                "程序已为 DeepSeek 调低推理强度并提高额度；请重试一次。"
            )
        if text:
            return text
        if isinstance(reasoning, str) and reasoning.strip():
            raise LLMError(
                "模型只返回了推理内容，没有返回最终答案。"
                "请重试；若持续出现，可在模型设置中改用 deepseek-flash。"
            )
        if finish_reason == "content_filter":
            raise LLMError("模型没有返回文字：内容被服务商的安全策略拦截。")
        if finish_reason == "insufficient_system_resource":
            raise LLMError("模型服务暂时资源不足，没有生成完整回答，请稍后重试。")
        return ""

    def _chat_payload(
        self,
        system_prompt: str,
        user_prompt: str,
        max_output_tokens: int | None,
        reasoning_effort: str | None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        if max_output_tokens is not None:
            payload["max_tokens"] = max_output_tokens
        if "api.deepseek.com" in self.config.base_url.lower():
            effort = reasoning_effort or "low"
            payload["reasoning_effort"] = effort
            payload["thinking"] = {"type": "disabled" if effort == "none" else "enabled"}
        return payload

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        reasoning_effort: str | None = None,
        max_output_tokens: int | None = None,
        image_paths: list[str] | None = None,
    ) -> str:
        style = self.config.api_style
        output_limit = max_output_tokens if max_output_tokens is not None else self.config.max_output_tokens
        if style == "auto":
            style = "responses" if "api.openai.com" in self.config.base_url else "chat_completions"

        images = []
        for value in image_paths or []:
            path = Path(value)
            if path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
                raise ValueError("模型图片输入仅支持 PNG、JPEG、WebP 或 GIF")
            data = path.read_bytes()
            if len(data) > 20 * 1024 * 1024:
                raise ValueError("单张图片超过本地 20 MB 传输限制")
            mime = mimetypes.guess_type(path.name)[0] or "image/png"
            images.append(f"data:{mime};base64," + base64.b64encode(data).decode("ascii"))

        if style == "responses":
            request_payload = {
                "model": self.config.model,
                "instructions": system_prompt,
                "input": user_prompt,
                "store": False,
            }
            if output_limit is not None:
                request_payload["max_output_tokens"] = output_limit
            if images:
                request_payload["input"] = [{"role": "user", "content":
                    [{"type": "input_text", "text": user_prompt}] +
                    [{"type": "input_image", "image_url": image, "detail": "high"} for image in images]}]
            payload = self._post("responses", request_payload)
            text = self._responses_text(payload)
        else:
            chat_payload = self._chat_payload(
                system_prompt, user_prompt, output_limit, reasoning_effort
            )
            if images:
                chat_payload["messages"][1]["content"] = [{"type": "text", "text": user_prompt}] + [
                    {"type": "image_url", "image_url": {"url": image, "detail": "high"}} for image in images]
            completed_parts: list[str] = []
            for continuation_index in range(3):
                payload = self._post("chat/completions", chat_payload)
                try:
                    text = self._chat_text(payload)
                except LLMTruncatedError as exc:
                    completed_parts.append(exc.partial_text)
                    if continuation_index >= 2:
                        text = "\n\n".join(completed_parts) + (
                            "\n\n[提示：回答连续三次达到服务商输出上限，"
                            "以上内容可能仍不完整。请缩小问题范围后继续提问。]"
                        )
                        break
                    assistant_message: dict[str, Any] = {
                        "role": "assistant",
                        "content": exc.partial_text,
                    }
                    if exc.reasoning_content:
                        assistant_message["reasoning_content"] = exc.reasoning_content
                    chat_payload["messages"].extend(
                        [
                            assistant_message,
                            {
                                "role": "user",
                                "content": (
                                    "上一个回答因为输出长度上限被截断。请严格从截断处继续，"
                                    "不要复述已经输出的内容，并完整收尾。"
                                ),
                            },
                        ]
                    )
                    continue
                if completed_parts:
                    completed_parts.append(text)
                    text = "\n\n".join(completed_parts)
                break
        if not text:
            raise LLMError("模型接口返回成功，但回答文字为空。请重试或更换模型。")
        return text
