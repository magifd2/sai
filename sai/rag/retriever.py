"""RAG retriever: embed query → vector search → fetch memory records.

Supports HyDE (Hypothetical Document Embeddings):
  Instead of embedding the raw query, the LLM generates a hypothetical
  Slack message that would answer the query, then that text is embedded.
  This bridges the semantic gap between question-style queries and
  statement-style stored messages (e.g. "what was dinner?" vs "dinner was X").
"""

from typing import Optional

from ..db.repositories.embedding import EmbeddingRepository, RetrievedDoc
from ..db.repositories.memory import MemoryRepository
from ..llm.client import ChatMessage, LLMClient
from ..memory.models import MemoryRecord
from ..utils.logging import get_logger

logger = get_logger(__name__)

_HYDE_SYSTEM = (
    "You are a search assistant. Given a question about past Slack conversations, "
    "write a short example Slack message that would directly answer it. "
    "Write only the message text — no labels, no explanation, no quotes."
)


class Retriever:
    def __init__(
        self,
        llm: LLMClient,
        embedding_repo: EmbeddingRepository,
        memory_repo: MemoryRepository,
        n_results: int = 5,
        similarity_threshold: float = 0.5,
        use_hyde: bool = True,
    ) -> None:
        self._llm = llm
        self._embeddings = embedding_repo
        self._memory = memory_repo
        self._n_results = n_results
        self._threshold = similarity_threshold
        self._use_hyde = use_hyde

    async def retrieve(
        self,
        query: str,
        n_results: Optional[int] = None,
        exclude_record_ids: Optional[list[str]] = None,
    ) -> list[MemoryRecord]:
        """
        Embed the query (via HyDE if enabled), search for similar memories,
        return matching records above similarity_threshold.
        """
        n = n_results or self._n_results

        if self._use_hyde:
            search_text = await self._hypothetical_doc(query)
        else:
            search_text = query

        query_embedding = await self._llm.embed(search_text)

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
            hyde=self._use_hyde,
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

    async def _hypothetical_doc(self, query: str) -> str:
        """Generate a hypothetical Slack message that would answer the query (HyDE).

        Falls back to the original query if the LLM call fails.
        """
        try:
            hyp = await self._llm.chat(
                [
                    ChatMessage(role="system", content=_HYDE_SYSTEM),
                    ChatMessage(role="user", content=query),
                ],
                max_tokens=150,
                temperature=0.0,
            )
            logger.debug("retriever.hyde", query_snippet=query[:50], hyp_snippet=hyp[:80])
            return hyp or query
        except Exception as exc:
            logger.warning("retriever.hyde_failed", error=str(exc))
            return query
