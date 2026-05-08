"""벡터 DB 래퍼 — ChromaDB.

PersistentClient + 기본 임베딩 함수(all-MiniLM-L6-v2). 메타데이터는
flat 형태로만 저장 가능하므로 emotion_tag 는 valence/arousal/labels(json)
세 키로 분리해서 직렬화한다.
"""

from __future__ import annotations

import json
import math
from typing import Any

import chromadb
from chromadb.utils import embedding_functions


def _flatten_record(record: dict) -> dict[str, Any]:
    """record dict 를 chroma metadata 호환 flat dict 로 변환."""
    metadata: dict[str, Any] = {}
    for key, value in record.items():
        if key in ("id", "content"):
            continue
        if key == "emotion_tag" and isinstance(value, dict):
            metadata["emotion_valence"] = float(value.get("valence", 0.0))
            metadata["emotion_arousal"] = float(value.get("arousal", 0.0))
            metadata["emotion_labels"] = json.dumps(list(value.get("labels", [])))
            continue
        # bool 도 chroma 가 허용. 리스트/딕트는 직렬화.
        if isinstance(value, (str, int, float, bool)) or value is None:
            if value is None:
                continue
            metadata[key] = value
        else:
            metadata[key] = json.dumps(value)
    return metadata


def _inflate_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    """flat metadata 를 emotion_tag 가 포함된 dict 로 복원."""
    result: dict[str, Any] = dict(metadata)
    if "emotion_valence" in metadata or "emotion_arousal" in metadata:
        labels_raw = metadata.get("emotion_labels", "[]")
        try:
            labels = json.loads(labels_raw) if isinstance(labels_raw, str) else list(labels_raw)
        except (json.JSONDecodeError, TypeError):
            labels = []
        result["emotion_tag"] = {
            "valence": float(metadata.get("emotion_valence", 0.0)),
            "arousal": float(metadata.get("emotion_arousal", 0.0)),
            "labels": labels,
        }
    return result


class VectorDB:
    """ChromaDB PersistentClient 래퍼."""

    def __init__(
        self,
        collection_name: str = "episodic",
        persist_dir: str = "./chroma_db",
    ):
        self.collection_name = collection_name
        self.persist_dir = persist_dir
        self._client = chromadb.PersistentClient(path=persist_dir)
        self._embed_fn = embedding_functions.DefaultEmbeddingFunction()
        self.collection = self._client.get_or_create_collection(
            name=collection_name,
            embedding_function=self._embed_fn,
        )

    async def embed(self, text: str) -> list[float]:
        """단일 텍스트 임베딩."""
        vectors = self._embed_fn([text])
        # numpy array 일 가능성 — list 로 정규화
        vec = vectors[0]
        return list(vec) if not isinstance(vec, list) else vec

    async def search(
        self,
        query: str,
        k: int = 10,
        mood_bias: dict | None = None,
        where: dict | None = None,
    ) -> list[dict]:
        """시맨틱 검색. mood_bias 주어지면 2k 받아서 재정렬."""
        if self.collection.count() == 0:
            return []

        n_results = min(k * 2 if mood_bias else k, max(self.collection.count(), 1))
        kwargs: dict[str, Any] = {
            "query_texts": [query],
            "n_results": n_results,
        }
        if where:
            kwargs["where"] = where

        raw = self.collection.query(**kwargs)

        ids = raw.get("ids", [[]])[0]
        documents = raw.get("documents", [[]])[0]
        metadatas = raw.get("metadatas", [[]])[0] or [{} for _ in ids]
        distances = raw.get("distances", [[]])[0] or [0.0 for _ in ids]

        results: list[dict] = []
        for rid, doc, meta, dist in zip(ids, documents, metadatas, distances):
            inflated = _inflate_metadata(meta or {})
            entry = {
                "id": rid,
                "content": doc,
                "distance": float(dist),
                **inflated,
            }
            results.append(entry)

        if mood_bias is not None:
            mood_v = float(mood_bias.get("valence", 0.0))
            # audit γ5: NaN/Inf 거리는 정렬을 깨뜨리므로 mood-bias rerank 단계에서 스킵.
            #          (정상 값으로 복구 불가능 → 결과 후보에서 제외하는 게 안전.)
            cleaned: list[dict] = []
            for entry in results:
                dist = entry["distance"]
                if math.isnan(dist) or math.isinf(dist):
                    continue
                semantic_score = 1.0 / (1.0 + dist)
                emo_v = float(entry.get("emotion_valence", 0.0))
                mood_match = 1.0 - abs(mood_v - emo_v) / 2.0
                entry["_score"] = semantic_score + 0.5 * mood_match
                cleaned.append(entry)
            cleaned.sort(key=lambda e: -e["_score"])
            results = cleaned[:k]
        else:
            results = results[:k]

        return results

    def upsert(self, record: dict) -> None:
        """record 한 건 삽입/갱신."""
        rid = record["id"]
        content = record["content"]
        metadata = _flatten_record(record)
        self.collection.upsert(
            ids=[rid],
            documents=[content],
            metadatas=[metadata],
        )

    def update(self, record_id: str, record: dict) -> None:
        """기존 record 갱신. emotion_tag 재평탄화."""
        content = record.get("content")
        metadata = _flatten_record(record)
        kwargs: dict[str, Any] = {
            "ids": [record_id],
            "metadatas": [metadata],
        }
        if content is not None:
            kwargs["documents"] = [content]
        self.collection.update(**kwargs)

    def get(self, record_id: str) -> dict | None:
        """id 로 단건 조회 (테스트용)."""
        raw = self.collection.get(ids=[record_id])
        ids = raw.get("ids") or []
        if not ids:
            return None
        documents = raw.get("documents") or [None]
        metadatas = raw.get("metadatas") or [{}]
        meta = metadatas[0] or {}
        inflated = _inflate_metadata(meta)
        return {
            "id": ids[0],
            "content": documents[0],
            **inflated,
        }
