"""Small labelled retrieval benchmark evaluation."""

from __future__ import annotations

from typing import Any

from .index import PaperIndex


def evaluate_retrieval(index: PaperIndex, benchmark: list[dict[str, Any]], top_k: int = 3) -> dict[str, Any]:
    methods = {
        "filename_baseline": index.filename_baseline,
        "bm25_fulltext": index.search_bm25_documents,
    }
    if index.embedding_index is not None:
        methods["hybrid_bm25_vector"] = index.search_documents
    output: dict[str, Any] = {"top_k": top_k, "query_count": len(benchmark), "methods": {}}
    for method_name, method in methods.items():
        rows = []
        reciprocal_ranks = []
        hits_at_1 = 0
        hits_at_k = 0
        for item in benchmark:
            retrieved = method(item["query"], top_k=top_k)
            gold_patterns = [pattern.lower() for pattern in item["gold_title_contains"]]
            rank = 0
            for position, title in enumerate(retrieved, start=1):
                if any(pattern in title.lower() for pattern in gold_patterns):
                    rank = position
                    break
            hits_at_1 += int(rank == 1)
            hits_at_k += int(rank > 0)
            reciprocal_ranks.append(1 / rank if rank else 0.0)
            rows.append(
                {
                    "query": item["query"],
                    "gold_title_contains": item["gold_title_contains"],
                    "retrieved": retrieved,
                    "first_relevant_rank": rank,
                }
            )
        count = max(1, len(benchmark))
        output["methods"][method_name] = {
            "hit_at_1": round(hits_at_1 / count, 4),
            f"hit_at_{top_k}": round(hits_at_k / count, 4),
            "mrr": round(sum(reciprocal_ranks) / count, 4),
            "rows": rows,
        }
    return output
