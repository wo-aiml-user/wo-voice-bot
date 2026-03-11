import os
import json
from asyncio import Lock
from loguru import logger
from datetime import datetime
from data_scraping_pipeline.config import settings
from data_scraping_pipeline.scraping.sitemap_extractor import extract_sitemap
from data_scraping_pipeline.scraping.pagecontent_extractor import extract_and_save_contents
from data_scraping_pipeline.indexing.indexer import run_indexer
from data_scraping_pipeline.indexing.vector_store import (
    connect_to_mongodb, 
    disconnect_from_mongodb,
    create_vector_search_index
)

pipeline_lock = Lock()

async def run_pipeline():
    """
    Run the complete data scraping and indexing pipeline.
    
    Flow:
    1. Connect to MongoDB
    2. Ensure vector search index exists
    3. Extract sitemap and compare with previous day
    4. Crawl changed/new pages and save content
    5. Index the scraped content into MongoDB
    6. Disconnect from MongoDB
    """
    try:
        if pipeline_lock.locked():
            logger.info("Pipeline already running, skipping this execution")
            return
        logger.info("Starting pipeline execution")
        
        # Stage 1: Connect to MongoDB
        logger.info("Connecting to MongoDB...")
        connect_to_mongodb()
        
        # Stage 2: Ensure vector search index exists
        logger.info("Checking vector search index...")
        create_vector_search_index()
        
        # Stage 3: Snapshot the sitemap
        logger.info("Stage 1: Extracting sitemap...")
        sitemap_result = extract_sitemap(
            sitemap_url="https://webosmotic.com/sitemap.xml",
            base_dir=settings.SITEMAPS_DIR,
            library="ET",
            compare=True,
        )
        if not sitemap_result["success"]:
            logger.error(f"Sitemap extraction failed: {sitemap_result['message']}")
            raise RuntimeError(f"Sitemap extraction failed: {sitemap_result['message']}")
        
        # Stage 4: Crawl the pages (async)
        logger.info("Stage 2: Crawling pages...")
        crawl_result = await extract_and_save_contents(
            sitemap_dir=settings.SITEMAPS_DIR,
            output_dir=settings.PAGE_CONTENTS_DIR,
            headless=True,
            max_session_permit=settings.MAX_SESSION_PERMIT,
            memory_threshold_percent=settings.MEMORY_THRESHOLD,
            max_retries=3,
        )

        if not crawl_result["success"]:
            logger.error(f"Crawling failed: {crawl_result['message']}")
            raise RuntimeError(f"Crawling failed: {crawl_result['message']}")
        
        # Stage 5: Index the scraped content
        logger.info("Stage 3: Indexing content into MongoDB...")
        index_result = run_indexer()
        
        if index_result["success"]:
            logger.info(f"Pipeline completed successfully: {index_result['message']}")
        else:
            logger.error(f"Indexing failed: {index_result['message']}")
            raise RuntimeError(f"Indexing failed: {index_result['message']}")
        
    except Exception as e:
        logger.error(f"Pipeline failed with error: {str(e)}", exc_info=True)
        raise
    finally:
        # Always disconnect from MongoDB
        disconnect_from_mongodb()


if __name__ == "__main__":
    import asyncio
    os.makedirs("logs", exist_ok=True)
    asyncio.run(run_pipeline())
