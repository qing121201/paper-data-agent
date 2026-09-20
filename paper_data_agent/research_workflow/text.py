"""User-facing text cleanup, coverage summaries, and deterministic Skill routing."""

from __future__ import annotations

import re


def prettify_paper_references(text: str) -> str:
    """Hide internal #N identifiers in user-facing prose and artifacts."""
    return re.sub(r"(?<![#\w])#(\d+)\b", r"〔论文 \1〕", text)


def remove_reading_process_branches(markdown: str) -> str:
    """Keep audit metadata in chat, not as a branch of the research mindmap."""
    lines = markdown.splitlines()
    output: list[str] = []
    skipping_indent: int | None = None
    process_titles = ("阅读覆盖", "本次阅读", "证据预算", "阅读计划")
    for line in lines:
        bullet = re.match(r"^(\s*)[-*+]\s+(.*)$", line)
        if skipping_indent is not None:
            if bullet and len(bullet.group(1)) > skipping_indent:
                continue
            skipping_indent = None
        if bullet:
            label = re.sub(r"[*_`]+", "", bullet.group(2)).strip()
            if label.startswith(process_titles):
                skipping_indent = len(bullet.group(1))
                continue
        output.append(line)
    return "\n".join(output).strip()


def coverage_note(evidence: str) -> str:
    """Build a deterministic, plain-language coverage note for artifact tasks."""
    survey = re.search(
        r"论文库总数：(\d+) 篇；实际读取：(\d+) 篇；预算不足未读：(\d+) 篇。.*?"
        r"完整摘要：(\d+) 篇；无法可靠识别摘要边界而改读完整首页/前两页：(\d+) 篇。",
        evidence,
        flags=re.DOTALL,
    )
    if survey:
        total, read, skipped, abstracts, front_pages = survey.groups()
        return (
            "## 本次阅读说明\n\n"
            f"本次共检查论文库中的 {total} 篇论文，实际读取 {read} 篇："
            f"其中 {abstracts} 篇读取完整摘要，{front_pages} 篇因无法可靠识别摘要边界而读取完整首页或前两页；"
            f"另有 {skipped} 篇因本次证据预算未读取。该说明只出现在回答中，不写入思维导图。"
        )
    focused = re.search(
        r"候选论文：(\d+) 篇；实际完整读取：(\d+) 篇；因预算跳过：(\d+) 篇。",
        evidence,
    )
    if focused:
        candidates, read, skipped = focused.groups()
        return (
            "## 本次阅读说明\n\n"
            f"本次检索到 {candidates} 篇候选论文，完整读取其中 {read} 篇的相关 PDF 页面，"
            f"另有 {skipped} 篇因本次证据预算未读取。该说明只出现在回答中，不写入思维导图。"
        )
    return "## 本次阅读说明\n\n本次产物依据上方执行记录中的论文证据生成；阅读过程信息未写入思维导图。"


ROUTES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("nature-image2ppt", ("图片转ppt", "截图还原", "扫描pdf转ppt", "editable ppt")),
    ("nature-paper2ppt", ("论文汇报", "文献汇报", "paper to ppt", "组会ppt")),
    ("nature-statistics", ("统计", "p值", "p value", "置信区间", "显著性", "样本量")),
    ("nature-figure", ("科研绘图", "论文配图", "多面板图", "scientific figure")),
    ("nature-ref-verifier", ("核验引用", "参考文献核验", "verify ref", "doi核验")),
    ("nature-reviewer", ("审稿", "reviewer", "评审意见", "投稿前自审")),
    ("nature-polishing", ("润色", "polish", "学术翻译", "英文修改")),
    ("nature-reader", ("中英对照", "全文翻译", "读论文", "paper reader")),
    ("nature-academic-search", ("查文献", "检索论文", "search papers", "literature search")),
    ("nature-writing", ("写综述", "相关工作", "写摘要", "论文写作", "research brief")),
    ("nature-paper-card", ("精读", "证据卡", "paper card", "文献卡片")),
    ("research-explorer", ("选题探索", "研究方向", "研究选题", "topic exploration")),
    ("experiment-suite", ("实验方案", "实验包", "对照实验", "experiment suite")),
    ("integrity-auditor", ("完整性审计", "完整性", "数据造假", "图片重复", "integrity audit")),
    ("mindmap-render", ("思维导图", "mindmap", "知识图谱图")),
)


def route_skill(query: str) -> str:
    normalized = query.lower().replace(" ", "")
    if (
        any(word in normalized for word in ("核验", "校验", "verify", "check"))
        and any(word in normalized for word in ("引用", "参考文献", "reference", "ref", "doi"))
    ):
        return "nature-ref-verifier"
    for skill, keywords in ROUTES:
        if any(keyword.lower().replace(" ", "") in normalized for keyword in keywords):
            return skill
    return "nature-paper-card"
