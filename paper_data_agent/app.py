from __future__ import annotations

import os
from datetime import datetime
from getpass import getpass
from pathlib import Path

from .config import apply_config, llm_ready, load_local_config, save_config
from .core import PaperAgent, PaperIndex
from .llm import LLMConfig, LLMError, OpenAICompatibleClient
from .skills import SELECTED_SKILLS, SkillCatalog, default_skill_root
from .workflow import ResearchWorkflowAgent


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INDEX = PROJECT_ROOT / "output" / "paper_index.json"
OUTPUT_DIR = PROJECT_ROOT / "output"
CONFIG_PATH = PROJECT_ROOT / ".env"


def _configure_api() -> bool:
    print("\n配置大模型 API（密钥输入时不会显示）")
    print("  1. OpenAI 官方 API")
    print("  2. 其他 OpenAI-compatible API / 本地模型")
    print("  0. 返回")
    provider = input("请选择：").strip()
    if provider == "0":
        return False
    if provider == "1":
        base_url = "https://api.openai.com/v1"
        api_style = "responses"
    elif provider == "2":
        base_url = input("接口地址（通常以 /v1 结尾）：").strip()
        api_style = "chat_completions"
    else:
        print("请输入 0、1 或 2。")
        return False
    model = input("模型名称（必须与服务商控制台一致）：").strip()
    api_key = getpass("API Key（本地模型允许留空）：").strip()
    config = LLMConfig(base_url=base_url, model=model, api_key=api_key, api_style=api_style)
    try:
        config.validate()
    except ValueError as exc:
        print(f"配置不完整：{exc}")
        return False
    apply_config(config)
    print("配置格式检查通过。真正连接会在发送第一条对话时验证。")
    print("注意：选择保存会把密钥明文保存在本机项目的 .env 文件中，该文件已被 Git 忽略。")
    if input("是否保存供下次启动使用？(y/N)：").strip().lower() == "y":
        save_config(CONFIG_PATH, config)
        print(f"已保存到：{CONFIG_PATH}")
    else:
        print("仅本次运行有效。")
    return True


def _load_local_agent() -> tuple[PaperAgent | None, int, int]:
    if not DEFAULT_INDEX.is_file():
        return None, 0, 0
    index = PaperIndex.load(DEFAULT_INDEX)
    return PaperAgent(index), len({chunk.title for chunk in index.chunks}), len(index.chunks)


def _welcome(paper_count: int, chunk_count: int, skill_count: int, online: bool) -> None:
    model_state = "已配置（首次生成时验证连接）" if online else "未配置（离线检索仍可使用）"
    print()
    print("=" * 64)
    print("  欢迎使用论文 Data Agent")
    print("  我可以检索本地论文、生成证据简报，并调用科研 Skill 协助写作。")
    print("-" * 64)
    print(f"  本地论文库：{paper_count} 篇论文，{chunk_count} 个文本块")
    print(f"  科研 Skills：{skill_count} 个已集成")
    print(f"  大模型：{model_state}")
    print("=" * 64)


def _read_query(prompt: str) -> str:
    return input(prompt).strip()


def _show_search(agent: PaperAgent) -> None:
    query = _read_query("请输入要查的问题：")
    if not query:
        print("没有输入问题，已返回菜单。")
        return
    hits = agent.run("search_papers", query=query, top_k=5)
    if not hits:
        print("没有找到匹配证据。可尝试改用论文中的英文关键词。")
        return
    print(f"\n找到 {len(hits)} 条论文证据：")
    for number, hit in enumerate(hits, start=1):
        excerpt = " ".join(hit["text"].split())[:240]
        print(f"\n{number}. {hit['title']}（PDF 第 {hit['page']} 页）")
        print(f"   相关性：{hit['score']}  路径：{hit['path']}")
        print(f"   {excerpt}...")


def _save_markdown(prefix: str, content: str) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = OUTPUT_DIR / f"{prefix}-{timestamp}.md"
    path.write_text(content, encoding="utf-8")
    return path


def _build_brief(agent: PaperAgent) -> None:
    query = _read_query("请输入简报主题：")
    if not query:
        print("没有输入主题，已返回菜单。")
        return
    brief = agent.run("build_brief", query=query, top_k=5)
    path = _save_markdown("证据简报", brief)
    print(f"证据简报已生成：{path}")


def _run_research_agent(paper_agent: PaperAgent, catalog: SkillCatalog) -> None:
    config = LLMConfig.from_env()
    if not llm_ready(config):
        print("大模型尚未配置，所以现在不能生成 AI 综述/精读结果。")
        print("本地论文检索和证据简报不受影响；配置方法见 README.md。")
        return
    workflow = ResearchWorkflowAgent(
        catalog,
        client=OpenAICompatibleClient(config),
        paper_agent=paper_agent,
    )
    history: list[dict[str, str]] = []
    transcript_path = OUTPUT_DIR / f"对话记录-{datetime.now().strftime('%Y%m%d-%H%M%S')}.md"
    print("\n已进入论文 Agent 对话。你只需说任务，不用选择工具或 Skill。")
    print("例如：这 33 篇论文主要讲什么？ / 精读 SWE-agent / 帮我写相关工作")
    print("输入 /back 返回菜单，输入 /help 查看说明。")
    while True:
        query = input("\n你 > ").strip()
        if query.lower() == "/back":
            print(f"已返回菜单。对话记录：{transcript_path}")
            return
        if query.lower() == "/help":
            print("直接描述科研任务即可；Agent 会先规划，再调用本地工具和 NatureSkill。")
            continue
        if not query:
            continue
        print("Agent 正在判断任务并调用合适的工具……")
        try:
            result, plan = workflow.chat(query=query, history=history)
        except (ValueError, LLMError) as exc:
            print(f"调用失败：{exc}")
            print("请检查接口地址、模型名称、余额或网络，也可返回菜单重新配置。")
            continue
        print(f"[执行记录] 工具={plan.tool}；Skill={plan.skill}；检索词={plan.search_query}")
        if plan.reason:
            print(f"[选择原因] {plan.reason}")
        print(f"\nAgent > {result.answer}")
        history.extend(
            [
                {"role": "user", "content": query},
                {"role": "assistant", "content": result.answer},
            ]
        )
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        transcript = ["# 论文 Agent 对话记录", ""]
        for item in history:
            speaker = "你" if item["role"] == "user" else "Agent"
            transcript.extend([f"## {speaker}", "", item["content"], ""])
        transcript_path.write_text("\n".join(transcript), encoding="utf-8")
        print(f"\n（本轮已保存到 {transcript_path.name}）")


def main() -> None:
    os.chdir(PROJECT_ROOT)
    load_local_config(CONFIG_PATH)
    try:
        paper_agent, paper_count, chunk_count = _load_local_agent()
        catalog = SkillCatalog(default_skill_root())
        skill_count = len(catalog.discover())
    except (OSError, ValueError) as exc:
        print(f"启动检查失败：{exc}")
        return

    config = LLMConfig.from_env()
    _welcome(paper_count, chunk_count, skill_count, llm_ready(config))
    if paper_agent is None:
        print(f"未找到论文索引：{DEFAULT_INDEX}")
        print("请先按照 README.md 的“重新建库”说明建立索引。")
        return

    while True:
        print("\n请选择功能：")
        print("  1. 与论文 Agent 对话（自动选择工具和 Skill）")
        print("  2. 配置大模型 API")
        print("  3. 检索本地论文证据（离线调试）")
        print("  4. 生成带页码的证据简报（离线调试）")
        print("  5. 查看已集成的 Skills")
        print("  0. 退出")
        choice = input("请输入序号：").strip()
        if choice == "1":
            _run_research_agent(paper_agent, catalog)
        elif choice == "2":
            _configure_api()
        elif choice == "3":
            _show_search(paper_agent)
        elif choice == "4":
            _build_brief(paper_agent)
        elif choice == "5":
            print("\n" + "\n".join(f"  - {name}" for name in SELECTED_SKILLS))
        elif choice == "0":
            print("已退出。生成的文件都保存在 output 文件夹中。")
            return
        else:
            print("请输入 0、1、2、3、4 或 5。")


if __name__ == "__main__":
    main()
