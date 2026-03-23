"""RAG retriever: embed query → vector search → fetch memory records."""

from typing import Optional

from ..db.repositories.embedding import EmbeddingRepository, RetrievedDoc
from ..db.repositories.memory import MemoryRepository
from ..llm.client import LLMClient
from ..memory.models import MemoryRecord
from ..utils.logging import get_logger

logger = get_logger(__name__)


class Retriever:
    def __init__(
        self,
        llm: LLMClient,
        embedding_repo: EmbeddingRepository,
        memory_repo: MemoryRepository,
        n_results: int = 5,
        similarity_threshold: float = 0.7,
    ) -> None:
        self._llm = llm
        self._embeddings = embedding_repo
        self._memory = memory_repo
        self._n_results = n_results
        self._threshold = similarity_threshold

    async def retrieve(
        self,
        query: str,
        n_results: Optional[int] = None,
        exclude_record_ids: Optional[list[str]] = None,
    ) -> list[MemoryRecord]:
        """
        Embed the query, search for similar memories, return matching records.
        Results below similarity_threshold are filtered out.
        """
        n = n_results or self._n_results
        query_embedding = await self._llm.embed(query)

        docs = await self._embeddings.query(
            query_embedding=query_embedding,
            n_results=n,
            exclude_record_ids=exclude_record_ids,
        )

        results: list[MemoryRecord] = []
        for doc in docs:
            logger.debug(
                "retriever.candidate",
                score=round(doc.score, 4),
                passed=doc.score >= self._threshold,
                record_id=doc.record_id,
            )
            if doc.score < self._threshold:
                continue
            record = await self._memory.get_by_id(doc.record_id)
            if record:
                results.append(record)

        logger.debug(
            "retriever.retrieved",
            query_snippet=query[:50],
            threshold=self._threshold,
            candidates=len(docs),
            passed_threshold=len(results),
        )
        return results

    async def index(self, record: MemoryRecord) -> str:
        """
        Embed a memory record and store the vector. Returns the embedding_id.
        Updates record.embedding_id in the DB.
        """
        from ..utils.ids import new_id
        embedding = await self._llm.embed(record.content)
        embedding_id = new_id()
        await self._embeddings.upsert(embedding_id, record.id, embedding)
        await self._memory.update_embedding_id(record.id, embedding_id)
        logger.debug("retriever.indexed", record_id=record.id, embedding_id=embedding_id)
        return embedding_id
