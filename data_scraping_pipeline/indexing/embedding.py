from loguru import logger
from pydantic import PrivateAttr
from typing import List, cast, Iterable
from langchain_voyageai import VoyageAIEmbeddings

class CustomVoyageAIEmbeddings(VoyageAIEmbeddings):
    _total_tokens: int = PrivateAttr(default=0)  # Properly declare with PrivateAttr
    _query_tokens: int = PrivateAttr(default=0)  # Track query tokens separately
    _document_tokens: int = PrivateAttr(default=0)  # Track document tokens separately

    def get_total_tokens(self) -> int:
        """Get the total number of tokens processed."""
        total = self._query_tokens + self._document_tokens
        return total

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """Embed search docs with adaptive batch size."""
        embeddings: List[List[float]] = []
        
        current_batch_size = self.batch_size
        
        while current_batch_size >= 2:
            try:
                # Reset embeddings list for each retry
                embeddings = []
                
                # Use the current batch size for iteration
                for i in range(0, len(texts), current_batch_size):
                    embed_response = self._client.embed(
                        texts[i : i + current_batch_size],
                        model=self.model,
                        input_type="document",
                        truncation=self.truncation,
                        output_dimension=self.output_dimension,
                    )
                    batch_embed = embed_response.embeddings
                    embeddings.extend(cast(Iterable[List[float]], batch_embed))
                    self._document_tokens += embed_response.total_tokens
                
                logger.info(f"Successfully embedded documents with batch size {current_batch_size}")
                break  # Exit loop on success
            
            except Exception as e:
                logger.info(f"Error embedding documents with batch size {current_batch_size}: {str(e)}")
                current_batch_size //= 2  # Reduce the batch size and retry
                
        if current_batch_size < 2:
            logger.info("Embedding failed due to persistent errors with low batch size.")
            raise Exception("Embedding failed with all attempted batch sizes")
            
        return embeddings
