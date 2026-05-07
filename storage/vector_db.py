"""벡터 DB 래퍼 — ChromaDB.

임베딩, 검색, 메타데이터 필터링.
Phase 2에서 구현.
"""

from __future__ import annotations


class VectorDB:
    """ChromaDB 래퍼."""

    def __init__(self, collection_name: str = "episodic"):
        self.collection_name = collection_name
        # Phase 2: chromadb.Client() 초기화

    async def embed(self, text: str) -> list[float]:
        raise NotImplementedError("Phase 2")

    async def search(
        self,
        query: str,
        k: int = 10,
        mood_bias: dict | None = None,
    ) -> list[dict]:
        raise NotImplementedError("Phase 2")

    def upsert(self, record: dict) -> None:
        raise NotImplementedError("Phase 2")

    def update(self, record_id: str, record: dict) -> None:
        raise NotImplementedError("Phase 2")
