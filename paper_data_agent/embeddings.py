from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np


DEFAULT_EMBEDDING_MODEL = "intfloat/multilingual-e5-small"
VECTOR_FORMAT = "paper-data-agent-vectors-v1"


def vector_paths(index_path: Path) -> tuple[Path, Path]:
    """Return the compressed vectors and metadata sidecars for one JSON index."""
    stem = index_path.with_suffix("")
    return stem.with_suffix(".vectors.npz"), stem.with_suffix(".vectors.json")


def chunks_fingerprint(chunks: Iterable[Any]) -> str:
    digest = hashlib.sha256()
    for chunk in chunks:
        for value in (
            chunk.paper_id, chunk.title, chunk.path, chunk.page, chunk.chunk_id, chunk.text
        ):
            digest.update(str(value).encode("utf-8", errors="replace"))
            digest.update(b"\0")
    return digest.hexdigest()


_MODEL_CACHE: dict[str, Any] = {}


def _load_model(model_name: str):
    if model_name in _MODEL_CACHE:
        return _MODEL_CACHE[model_name]
    try:
        from sentence_transformers import SentenceTransformer
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "本地向量检索需要 sentence-transformers；请先安装 requirements.txt"
        ) from exc
    model = SentenceTransformer(model_name)
    _MODEL_CACHE[model_name] = model
    return model


def _encode(model: Any, texts: Sequence[str], role: str, batch_size: int = 24) -> np.ndarray:
    method = getattr(model, "encode_query" if role == "query" else "encode_document", None)
    prepared = list(texts)
    if not callable(method):
        prefix = "query: " if role == "query" else "passage: "
        prepared = [prefix + text for text in prepared]
        method = model.encode
    result = method(
        prepared,
        batch_size=batch_size,
        show_progress_bar=False,
        convert_to_numpy=True,
        normalize_embeddings=True,
    )
    array = np.asarray(result, dtype=np.float32)
    if array.ndim == 1:
        array = array.reshape(1, -1)
    return array


@dataclass(slots=True)
class LocalEmbeddingIndex:
    vectors: np.ndarray
    model_name: str
    chunk_fingerprint: str
    encoder: Any | None = None

    @classmethod
    def build(
        cls,
        chunks: Sequence[Any],
        vectors_path: Path,
        metadata_path: Path,
        model_name: str = DEFAULT_EMBEDDING_MODEL,
        encoder: Any | None = None,
        batch_size: int = 24,
    ) -> "LocalEmbeddingIndex":
        if not chunks:
            raise ValueError("论文库没有可建立向量的文本块")
        model = encoder or _load_model(model_name)
        texts = [f"{chunk.title}\n{chunk.text}" for chunk in chunks]
        vectors = _encode(model, texts, "document", batch_size=batch_size)
        if vectors.shape[0] != len(chunks):
            raise RuntimeError("Embedding 返回数量与论文文本块不一致")
        fingerprint = chunks_fingerprint(chunks)
        vectors_path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(vectors_path, vectors=vectors)
        metadata = {
            "format": VECTOR_FORMAT,
            "model": model_name,
            "chunk_count": len(chunks),
            "dimensions": int(vectors.shape[1]),
            "chunk_fingerprint": fingerprint,
        }
        metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        return cls(vectors, model_name, fingerprint, model)

    @classmethod
    def load(
        cls,
        vectors_path: Path,
        metadata_path: Path,
        chunks: Sequence[Any],
    ) -> "LocalEmbeddingIndex":
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if metadata.get("format") != VECTOR_FORMAT:
            raise ValueError("不支持的向量索引格式")
        fingerprint = chunks_fingerprint(chunks)
        if metadata.get("chunk_fingerprint") != fingerprint:
            raise ValueError("向量索引与当前论文文本不一致，需要更新")
        with np.load(vectors_path, allow_pickle=False) as payload:
            vectors = np.asarray(payload["vectors"], dtype=np.float32)
        if vectors.ndim != 2 or vectors.shape[0] != len(chunks):
            raise ValueError("向量索引数量与当前论文文本不一致，需要更新")
        return cls(vectors, str(metadata["model"]), fingerprint)

    def scores(self, query: str) -> np.ndarray:
        if not query.strip():
            raise ValueError("query must contain searchable words")
        model = self.encoder or _load_model(self.model_name)
        query_vector = _encode(model, [query], "query")[0]
        return self.vectors @ query_vector


def vector_status(index_path: Path, chunks: Sequence[Any]) -> str:
    vectors_path, metadata_path = vector_paths(index_path)
    if not vectors_path.is_file() or not metadata_path.is_file():
        return "未建立"
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return "需要更新"
    if (
        metadata.get("format") != VECTOR_FORMAT
        or metadata.get("chunk_count") != len(chunks)
        or metadata.get("chunk_fingerprint") != chunks_fingerprint(chunks)
    ):
        return "需要更新"
    return "可用"
