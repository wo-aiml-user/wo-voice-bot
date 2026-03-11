import re
import json
from loguru import logger
from langchain_core.documents import Document
from typing import List, Dict, Any, Optional, Union

class ChunkingError(Exception):
    """Custom exception for chunking errors."""
    pass

class InvalidInputError(Exception):
    """Custom exception for invalid input errors."""
    pass

def chunk_markdown(
    text: str,
    min_size: int = 1000,
    max_size: int = 1100,
    overlap: int = 0
) -> List[str]:
    """
    Split text (markdown) into chunks of ~min_size–max_size characters,
    each starting at a heading (#, ## or ###).  If no heading is found
    after min_size, we extend to either the next header (≤max_size) or, failing that,
    to the last space/newline before max_size.  Optionally overlap chunks.

    Args:
        text: The markdown text to chunk
        min_size: Minimum chunk size in characters
        max_size: Maximum chunk size in characters
        overlap: Number of characters to overlap between chunks

    Returns:
        List of chunk strings

    Raises:
        ChunkingError: If there's an error during the chunking process
        ValueError: If parameters are invalid
    """
    try:
        # Validate parameters
        if not isinstance(text, str):
            raise ValueError("Text must be a string")
        if min_size <= 0 or max_size <= 0:
            raise ValueError("min_size and max_size must be positive integers")
        if min_size > max_size:
            raise ValueError("min_size must be less than or equal to max_size")
        if overlap < 0:
            raise ValueError("overlap must be a non-negative integer")
        
        if not text.strip():
            logger.warning("Empty or whitespace-only text provided, returning empty chunks list")
            return []
            
        header_re = re.compile(r'^#{1,3}\s+.*', flags=re.MULTILINE)
        text_len = len(text)

        # 1) find all headers
        headers = [m.start() for m in header_re.finditer(text)]
        if not headers:
        # fallback: no headers at all → just break on whitespace/newlines
            headers = [0]
        else:
            # Add position 0 if we want to include content before first header
            headers = [0] + headers

        chunks = []
        # 2) first chunk starts at first header
        chunk_start = headers[0]

        while chunk_start < text_len:
            # if what's left is shorter than min_size, take it all
            if chunk_start + min_size >= text_len:
                chunks.append(text[chunk_start:])
                break

            # define the window where we ideally want to cut
            min_cut = chunk_start + min_size
            max_cut = min(chunk_start + max_size, text_len)

            # 3a) look for a header between min_cut and max_cut
            next_header = header_re.search(text, pos=min_cut, endpos=max_cut)
            if next_header:
                cut_at = next_header.start()
            else:
                # 3b) no header in that slice → find last space or newline
                ws1 = text.rfind(' ', chunk_start + min_size, max_cut)
                ws2 = text.rfind('\n', chunk_start + min_size, max_cut)
                split_pos = max(ws1, ws2)
                if split_pos != -1:
                    cut_at = split_pos
                else:
                    # 3c) still nothing → hard cut at max_cut
                    cut_at = max_cut

            # extract chunk
            chunks.append(text[chunk_start:cut_at])

            # 4) prepare next chunk start with optional overlap
            if overlap > 0:
                # we want to re‑include overlap chars from the end of this chunk
                next_start_candidate = max(chunk_start, cut_at - overlap)
            else:
                next_start_candidate = cut_at

            # but each chunk must start at a header, so find the next header ≥ that point
            hdr = header_re.search(text, pos=next_start_candidate)
            if hdr:
                chunk_start = hdr.start()
            else:
                # no more headers: just continue from where overlap left us
                chunk_start = next_start_candidate

        return chunks
    except ValueError as e:
        # Re-raise ValidationError with the original message
        raise ValueError(str(e))
    except Exception as e:
        logger.error(f"Error during markdown chunking: {str(e)}")
        raise ChunkingError(f"Failed to chunk markdown text: {str(e)}")

def create_langchain_documents(
    chunks: List[str], 
    webpage_url: Optional[str] = None,
) -> List[Document]:
    """
    Convert a list of text chunks into LangChain Document objects with metadata.
    
    Args:
        chunks: List of text chunks
        webpage_url: URL of the webpage (optional)
        
    Returns:
        List of LangChain Document objects
        
    Raises:
        ValueError: If chunks is not a list of strings
    """
    try:
        if not isinstance(chunks, list):
            raise ValueError("chunks must be a list")
        
        documents = []
        
        for i, chunk in enumerate(chunks):
            if not isinstance(chunk, str):
                raise ValueError(f"Chunk at index {i} is not a string")
                
            # Create metadata dictionary
            metadata: Dict[str, Any] = {
                "chunk_id": i + 1,
                "chunk_number": i + 1,  # Added chunk_number as alias to chunk_id
                "chunk_size": len(chunk)
            }
            
            # Add optional metadata if provided
            if webpage_url:
                metadata["webpage_url"] = webpage_url
                
            # Create Document object
            doc = Document(
                page_content=chunk,
                metadata=metadata
            )
            
            documents.append(doc)
            
        return documents
    except ValueError as e:
        # Re-raise ValueErrors with the original message
        raise ValueError(str(e))
    except Exception as e:
        logger.error(f"Error creating LangChain documents: {str(e)}")
        raise Exception(f"Failed to create LangChain documents: {str(e)}")

def process_json_input(
    json_data: Union[str, dict],
    min_size: int = 1000,
    max_size: int = 1100,
    overlap: int = 0
) -> List[Document]:
    """
    Process JSON input with multiple webpage URLs and their content.
    
    Args:
        json_data: JSON string or dictionary containing webpage URLs as keys and their content as values
        min_size: Minimum chunk size for the markdown chunker
        max_size: Maximum chunk size for the markdown chunker
        overlap: Overlap size between chunks
    
    Returns:
        List of LangChain Document objects from all webpages
        
    Raises:
        InvalidInputError: If the JSON data is invalid or has an unexpected format
        ChunkingError: If there's an error during the chunking process
        ValueError: If parameters are invalid
    """
    try:
        # Parse JSON data if it's a string
        if isinstance(json_data, str):
            try:
                data = json.loads(json_data)
            except json.JSONDecodeError as e:
                raise InvalidInputError(f"Invalid JSON input: {str(e)}")
        elif isinstance(json_data, dict):
            data = json_data
        else:
            raise InvalidInputError("Input must be a JSON string or dictionary")
        
        # Check if data is empty
        if not data:
            logger.warning("Empty JSON data provided")
            return []
            
        all_documents = []
        
        # Process each webpage
        for url, content in data.items():
            try:
                # Validate URL and content
                if not isinstance(url, str) or not url.strip():
                    logger.warning(f"Skipping invalid URL: {url}")
                    continue
                    
                if not isinstance(content, str):
                    logger.warning(f"Skipping non-string content for URL {url}")
                    continue
                
                # Chunk the content
                chunks = chunk_markdown(content, min_size=min_size, max_size=max_size, overlap=overlap)
                
                # Create LangChain documents
                documents = create_langchain_documents(chunks, webpage_url=url)
                
                # Add to the collection
                all_documents.extend(documents)
                
                logger.info(f"Successfully processed URL: {url} - Created {len(documents)} documents")
                
            except (ChunkingError, ValueError) as e:
                logger.error(f"Error processing URL {url}: {str(e)}")
                continue  # Skip this URL and continue with others
        
        return all_documents
        
    except InvalidInputError as e:
        # Re-raise InvalidInputError with the original message
        raise InvalidInputError(str(e))
    except Exception as e:
        logger.error(f"Unexpected error during JSON processing: {str(e)}")
        raise Exception(f"Failed to process JSON input: {str(e)}")

def process_markdown_documents(
    json_input: Union[str, dict],
    min_size: int = 1000,
    max_size: int = 1100,
    overlap: int = 0
) -> List[Document]:
    """
    Main function to process markdown documents from JSON input.
    This is the only function that should be called by external code.
    
    Args:
        json_input: JSON string or dictionary with webpage URLs as keys and markdown content as values
        min_size: Minimum chunk size for the markdown chunker
        max_size: Maximum chunk size for the markdown chunker
        overlap: Overlap size between chunks
        
    Returns:
        List of LangChain Document objects
        
    Raises:
        Exception: If any error occurs during processing
    """
    try:
        # Validate parameters
        if min_size <= 0 or max_size <= 0:
            raise ValueError("min_size and max_size must be positive integers")
        if min_size > max_size:
            raise ValueError("min_size must be less than or equal to max_size")
        if overlap < 0:
            raise ValueError("overlap must be a non-negative integer")
            
        # Process the input and return the documents
        return process_json_input(json_input, min_size, max_size, overlap)
        
    except Exception as e:
        logger.error(f"Error in process_markdown_documents: {str(e)}")
        # In production code, you might want to handle this differently
        # based on your error handling requirements
        raise
