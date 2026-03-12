from pydantic import PrivateAttr
from typing import List, cast, Any
from langchain_voyageai import VoyageAIEmbeddings

class CustomVoyageAIEmbeddings(VoyageAIEmbeddings):
    _total_tokens: int = PrivateAttr(default=0)  # Properly declare with PrivateAttr
    _query_tokens: int = PrivateAttr(default=0)  # Track query tokens separately
    _document_tokens: int = PrivateAttr(default=0)  # Track document tokens separately
    _rerank_tokens: int = PrivateAttr(default=0)    # Track rerank tokens separately

    def get_total_tokens(self) -> int:
        """Get the total number of tokens processed (embedding + reranking)."""
        return self._query_tokens + self._document_tokens + self._rerank_tokens

    def embed_query(self, text: str) -> List[float]:
        """Embed query text."""
        embed_response = self._client.embed(
            [text],
            model=self.model,
            input_type="query",
            truncation=self.truncation,
            output_dimension=self.output_dimension,
        )
        self._query_tokens += embed_response.total_tokens
        return cast(List[float], embed_response.embeddings[0])

    def rerank(self, query: str, documents: List[str], model: str, top_k: int) -> Any:
        """Rerank documents based on query."""
        rerank_response = self._client.rerank(
            query=query,
            documents=documents,
            model=model,
            top_k=top_k
        )
        self._rerank_tokens += rerank_response.total_tokens
        return rerank_response
