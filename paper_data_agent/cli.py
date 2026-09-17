from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path

from .core import PaperAgent, PaperIndex, evaluate_retrieval
from .embeddings import DEFAULT_EMBEDDING_MODEL
from .llm import LLMConfig, OpenAICompatibleClient
from .skills import SELECTED_SKILLS, SkillCatalog, default_skill_root
from .workflow import ResearchWorkflowAgent


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Paper Data Agent demo")
    subparsers = parser.add_subparsers(dest="command", required=True)

    index_parser = subparsers.add_parser("index", help="Build an index from PDFs")
    index_parser.add_argument("--input", type=Path, required=True)
    index_parser.add_argument("--output", type=Path, required=True)

    search_parser = subparsers.add_parser("search", help="Search indexed papers")
    search_parser.add_argument("--index", type=Path, required=True)
    search_parser.add_argument("--query", required=True)
    search_parser.add_argument("--top-k", type=int, default=5)

    vectors_parser = subparsers.add_parser("vectors", help="Build a local embedding index")
    vectors_parser.add_argument("--index", type=Path, required=True)
    vectors_parser.add_argument("--model", default=DEFAULT_EMBEDDING_MODEL)
    vectors_parser.add_argument("--batch-size", type=int, default=24)

    brief_parser = subparsers.add_parser("brief", help="Generate an evidence brief")
    brief_parser.add_argument("--index", type=Path, required=True)
    brief_parser.add_argument("--query", required=True)
    brief_parser.add_argument("--top-k", type=int, default=5)
    brief_parser.add_argument("--output", type=Path)

    evaluate_parser = subparsers.add_parser("evaluate", help="Run the retrieval benchmark")
    evaluate_parser.add_argument("--index", type=Path, required=True)
    evaluate_parser.add_argument("--benchmark", type=Path, required=True)
    evaluate_parser.add_argument("--output", type=Path, required=True)
    evaluate_parser.add_argument("--top-k", type=int, default=3)

    skills_parser = subparsers.add_parser("skills", help="List integrated research skills")
    skills_parser.add_argument("--skill-root", type=Path, default=default_skill_root())

    agent_parser = subparsers.add_parser("agent", help="Run a research-skill + LLM workflow")
    agent_parser.add_argument("--query", required=True)
    agent_parser.add_argument("--skill", choices=SELECTED_SKILLS)
    agent_parser.add_argument("--index", type=Path)
    agent_parser.add_argument("--skill-root", type=Path, default=default_skill_root())
    agent_parser.add_argument("--top-k", type=int, default=5)
    agent_parser.add_argument("--max-skill-chars", type=int, default=120_000)
    agent_parser.add_argument("--dry-run", action="store_true")
    agent_parser.add_argument("--output", type=Path)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "index":
        index = PaperIndex.build(args.input)
        index.save(args.output)
        papers = len({chunk.title for chunk in index.chunks})
        print(json.dumps({"papers": papers, "chunks": len(index.chunks), "output": str(args.output)}, ensure_ascii=False))
        return

    if args.command == "skills":
        catalog = SkillCatalog(args.skill_root)
        print(json.dumps(catalog.to_dicts(), ensure_ascii=False, indent=2))
        return

    if args.command == "vectors":
        index = PaperIndex.load(args.index)
        embedding = index.build_embeddings(
            args.index, model_name=args.model, batch_size=args.batch_size
        )
        print(json.dumps({
            "model": embedding.model_name,
            "chunks": len(index.chunks),
            "dimensions": int(embedding.vectors.shape[1]),
            "index": str(args.index),
        }, ensure_ascii=False))
        return

    if args.command == "agent":
        catalog = SkillCatalog(args.skill_root)
        paper_agent = PaperAgent(PaperIndex.load(args.index)) if args.index else None
        client = None if args.dry_run else OpenAICompatibleClient(LLMConfig.from_env())
        workflow = ResearchWorkflowAgent(catalog, client=client, paper_agent=paper_agent)
        result = workflow.run(
            query=args.query,
            skill=args.skill,
            top_k=args.top_k,
            dry_run=args.dry_run,
            max_skill_chars=args.max_skill_chars,
        )
        payload = asdict(result)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(result.answer, encoding="utf-8")
            payload["answer"] = f"written to {args.output}"
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    index = PaperIndex.load(args.index)
    agent = PaperAgent(index)
    if args.command == "search":
        result = agent.run("search_papers", query=args.query, top_k=args.top_k)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.command == "brief":
        result = agent.run("build_brief", query=args.query, top_k=args.top_k)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(result, encoding="utf-8")
            print(args.output)
        else:
            print(result)
    elif args.command == "evaluate":
        benchmark = json.loads(args.benchmark.read_text(encoding="utf-8"))
        result = evaluate_retrieval(index, benchmark, top_k=args.top_k)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({key: value for key, value in result.items() if key != "methods"}, ensure_ascii=False))
        for method, values in result["methods"].items():
            print(method, {key: value for key, value in values.items() if key != "rows"})


if __name__ == "__main__":
    main()
