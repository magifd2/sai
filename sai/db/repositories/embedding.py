"""EmbeddingRepository: vector storage and similarity search via DuckDB VSS."""

from typing import Optional

from .base import BaseRepository


class RetrievedDoc:
    def __init__(self, embedding_id: str, record_id: str, score: float) -> None:
        self.embedding_id = embedding_id
        self.record_id = record_id
        self.score = score  # cosine similarity (0-1, higher = more similar)


class EmbeddingRepository(BaseRepository):

    def __init__(self, embed_dim: int = 768) -> None:
        self._embed_dim = embed_dim

    async def upsert(
        self, embedding_id: str, record_id: str, embedding: list[float]
    ) -> None:
        """Insert or replace an embedding vector."""
        await self._run(self._upsert_sync, embedding_id, record_id, embedding)

    def _upsert_sync(
        self, embedding_id: str, record_id: str, embedding: list[float]
    ) -> None:
        self._execute(
            """
            INSERT OR REPLACE INTO memory_embeddings (embedding_id, record_id, embedding)
            VALUES (?, ?, ?)
            """,
            [embedding_id, record_id, embedding],
        )

    async def delete(self, embedding_id: str) -> None:
        await self._run(
            self._execute,
            "DELETE FROM memory_embeddings WHERE embedding_id = ?",
            [embedding_id],
        )

    async def delete_many(self, embedding_ids: list[str]) -> None:
        if not embedding_ids:
            return
        placeholders = ",".join("?" * len(embedding_ids))
        await self._run(
            self._execute,
            f"DELETE FROM memory_embeddings WHERE embedding_id IN ({placeholders})",
            embedding_ids,
        )

    async def delete_by_record_id(self, record_id: str) -> None:
        await self._run(
            self._execute,
            "DELETE FROM memory_embeddings WHERE record_id = ?",
            [record_id],
        )

    async def query(
        self,
        query_embedding: list[float],
        n_results: int = 5,
        exclude_record_ids: Optional[list[str]] = None,
    ) -> list[RetrievedDoc]:
        """
        Return the n_results most similar documents using HNSW cosine search.
        Optionally exclude specific record IDs from results.
        """
        return await self._run(
            self._query_sync, query_embedding, n_results, exclude_record_ids
        )

    def _query_sync(
        self,
        query_embedding: list[float],
        n_results: int,
        exclude_record_ids: Optional[list[str]],
    ) -> list[RetrievedDoc]:
        if exclude_record_ids:
            placeholders = ",".join("?" * len(exclude_record_ids))
            sql = f"""
                SELECT embedding_id, record_id,
                       array_cosine_similarity(embedding, ?::FLOAT[{self._embed_dim}]) AS score
                  FROM memory_embeddings
                 WHERE record_id NOT IN ({placeholders})
                 ORDER BY score DESC
                 LIMIT ?
            """
            params = [query_embedding, *exclude_record_ids, n_results]
        else:
            sql = f"""
                SELECT embedding_id, record_id,
                       array_cosine_similarity(embedding, ?::FLOAT[{self._embed_dim}]) AS score
                  FROM memory_embeddings
                 ORDER BY score DESC
                 LIMIT ?
            """
            params = [query_embedding, n_results]

        rows = self._execute(sql, params)
        return [RetrievedDoc(r[0], r[1], float(r[2])) for r in rows]
