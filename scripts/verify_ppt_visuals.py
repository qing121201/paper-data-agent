"""Opt-in local integration check: use configured model and preserve source deck."""
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from paper_data_agent.config import load_local_config
from paper_data_agent.llm import LLMConfig, OpenAICompatibleClient
from paper_data_agent.presentation_workspace import revise_slide, render_preview

if __name__ == "__main__":
    load_local_config(ROOT / ".env")
    config = LLMConfig.from_env()
    config.timeout_seconds = 240
    source = ROOT / "libraries/swe-agent/outputs/SWE-agent-与-SWE-bench-研究脉络组会汇报-20260916-135509/presentation_spec.json"
    page = 2
    instruction = ("为本页插入 SWE-BENCH CAN LANGUAGE MODELS RESOLVE 原论文的一幅相关原图或表格。"
        "仔细查看候选图，裁剪到图表区域并保留标签和图注；不要用整页截图。"
        "选择清晰的图上文下布局，正文只留一句解释；不要选其他论文的图。")
    if "--draw" in sys.argv:
        source = max((ROOT / "libraries/swe-agent/outputs").glob("SWE-agent-*/presentation_spec.json"), key=lambda p: p.stat().st_mtime)
        page = 5
        instruction = "根据 AGENTLESS 论文为这一页自绘一张定位、修复、补丁验证的三步流程图。使用 drawing，不用截图。来源注明本地原文页码，正文只保留一句说明，图上文下。"
    target = revise_slide(source, page, instruction, OpenAICompatibleClient(config))
    with zipfile.ZipFile(target.parent / "paper-presentation.pptx") as archive:
        media = [n for n in archive.namelist() if n.startswith("ppt/media/")]
    print("SPEC:", target, flush=True)
    print("MEDIA:", len(media), flush=True)
    print("PREVIEW:", render_preview(target)[page], flush=True)
