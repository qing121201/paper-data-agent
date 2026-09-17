import tempfile
import unittest
from pathlib import Path

import numpy as np

from paper_data_agent.core import PaperChunk, PaperIndex
from paper_data_agent.embeddings import vector_paths, vector_status


class FakeEncoder:
    @staticmethod
    def _vectors(texts):
        rows = []
        for text in texts:
            lower = text.lower()
            if "software" in lower or "issue" in lower or "修复" in lower:
                rows.append([0.0, 1.0, 0.0])
            elif "cell" in lower or "细胞" in lower:
                rows.append([1.0, 0.0, 0.0])
            else:
                rows.append([0.0, 0.0, 1.0])
        return np.asarray(rows, dtype=np.float32)

    def encode_query(self, texts, **_kwargs):
        return self._vectors(texts)

    def encode_document(self, texts, **_kwargs):
        return self._vectors(texts)


def chunks():
    return [
        PaperChunk("cell", "Virtual Cell", "cell.pdf", 1, 0, "whole cell simulation"),
        PaperChunk("swe", "SWE-agent", "swe.pdf", 1, 0, "software issue repair agent"),
        PaperChunk("other", "Other", "other.pdf", 1, 0, "unrelated benchmark"),
    ]


class EmbeddingIndexTests(unittest.TestCase):
    def test_build_load_and_hybrid_cross_language_search(self):
        with tempfile.TemporaryDirectory() as folder:
            index_path = Path(folder) / "index.json"
            index = PaperIndex(chunks())
            index.save(index_path)
            index.build_embeddings(index_path, model_name="fake", encoder=FakeEncoder())

            loaded = PaperIndex.load(index_path)
            self.assertIsNotNone(loaded.embedding_index)
            loaded.embedding_index.encoder = FakeEncoder()
            hits = loaded.search("修复软件仓库问题", top_k=2)
            self.assertEqual(hits[0].title, "SWE-agent")
            self.assertEqual(hits[0].retrieval, "hybrid")
            self.assertEqual(vector_status(index_path, loaded.chunks), "可用")

    def test_stale_vectors_fall_back_to_bm25(self):
        with tempfile.TemporaryDirectory() as folder:
            index_path = Path(folder) / "index.json"
            index = PaperIndex(chunks())
            index.save(index_path)
            index.build_embeddings(index_path, model_name="fake", encoder=FakeEncoder())

            changed = PaperIndex(chunks()[:-1])
            changed.save(index_path)
            loaded = PaperIndex.load(index_path)
            self.assertIsNone(loaded.embedding_index)
            self.assertEqual(vector_status(index_path, loaded.chunks), "需要更新")
            hits = loaded.search("software issue", top_k=1)
            self.assertEqual(hits[0].title, "SWE-agent")
            self.assertEqual(hits[0].retrieval, "bm25")

    def test_vector_sidecars_are_separate_from_portable_json(self):
        with tempfile.TemporaryDirectory() as folder:
            index_path = Path(folder) / "index.json"
            index = PaperIndex(chunks())
            index.save(index_path)
            vectors_path, metadata_path = vector_paths(index_path)
            self.assertFalse(vectors_path.exists())
            self.assertFalse(metadata_path.exists())
            index.build_embeddings(index_path, model_name="fake", encoder=FakeEncoder())
            self.assertTrue(vectors_path.is_file())
            self.assertTrue(metadata_path.is_file())


if __name__ == "__main__":
    unittest.main()
