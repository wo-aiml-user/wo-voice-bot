import os
import sys
import json
import glob
import time
import asyncio
from pathlib import Path
from loguru import logger
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any

from crawl4ai import (
    AsyncWebCrawler,
    BrowserConfig,
    CrawlerRunConfig,
    CacheMode,
    CrawlerMonitor,
    MemoryAdaptiveDispatcher,
)

from app.data_scraping_pipeline.scraping.cleaner import clean_content
from app.data_scraping_pipeline.scraping.sitemap_extractor import get_latest_two_sitemap_paths, compare_sitemaps, SitemapProcessingError

#-------------------------------------------------------------------------------------------------------------------------------------
#-------------------------------------------------------------------------------------------------------------------------------------

class CrawlError(Exception):
    """Base exception for crawler errors."""
    pass

class InputError(CrawlError):
    """Error related to input data or files."""
    pass

class CrawlExecutionError(CrawlError):
    """Error during crawl execution."""
    pass

class OutputError(CrawlError):
    """Error related to output handling."""
    pass

async def get_sitemap_changes(
    sitemap_dir: str = "sitemaps"
) -> Tuple[List[str], bool]:
    """
    Get URLs that have changed between the two most recent sitemaps.
    
    Args:
        sitemap_dir: Directory containing sitemap JSON files
    
    Returns:
        Tuple of (list of changed URLs, is_first_run flag)
    
    Raises:
        InputError: If sitemap directory or files are invalid
    """
    try:
        # Check for sitemap files
        pattern = os.path.join(sitemap_dir, "*.json")
        files = glob.glob(pattern)
        
        if not files:
            logger.warning(f"No sitemap files found in {sitemap_dir}")
            raise InputError(f"No sitemap files found in {sitemap_dir}")
        
        if len(files) == 1:
            # First run, get all URLs from the only sitemap
            logger.info("First run detected: only one sitemap snapshot found.")
            
            try:
                with open(files[0], 'r', encoding='utf-8') as f:
                    sitemap_data = json.load(f)
                
                urls = [item.get("url", "") for item in sitemap_data if isinstance(item, dict)]
                urls = [url for url in urls if url]  # Filter out empty URLs
                
                logger.info(f"Loaded {len(urls)} URLs from single sitemap file")
                return urls, True
                
            except json.JSONDecodeError as e:
                logger.error(f"Invalid JSON in sitemap file {files[0]}: {e}")
                raise InputError(f"Invalid JSON in sitemap file: {e}")
        
        else:
            # Multiple sitemaps, compare the two most recent
            try:
                yesterday_path, today_path = get_latest_two_sitemap_paths(sitemap_dir)
                logger.info(f"Comparing sitemaps: {os.path.basename(yesterday_path)} "
                           f"and {os.path.basename(today_path)}")
                
                changed_urls = compare_sitemaps(yesterday_path, today_path)
                logger.info(f"Found {len(changed_urls)} changed URLs")
                
                return changed_urls, False
                
            except SitemapProcessingError as e:
                logger.error(f"Sitemap comparison error: {e}")
                raise InputError(f"Sitemap comparison error: {e}")
    
    except Exception as e:
        if not isinstance(e, InputError):
            logger.error(f"Unexpected error in get_sitemap_changes: {e}", exc_info=True)
            raise InputError(f"Unexpected error determining sitemap changes: {str(e)}")
        raise

def load_urls_from_json(input_json_path: str) -> List[str]:
    """
    Load URLs from a JSON file.
    
    Args:
        input_json_path: Path to JSON file containing URL data
    
    Returns:
        List of URLs
    
    Raises:
        InputError: If file doesn't exist or has invalid format
    """
    logger.info(f"Loading URLs from {input_json_path}")
    
    try:
        if not os.path.isfile(input_json_path):
            raise InputError(f"Input file not found: {input_json_path}")
        
        with open(input_json_path, "r", encoding="utf-8") as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError as e:
                raise InputError(f"Invalid JSON in {input_json_path}: {e}")
        
        if not isinstance(data, list):
            raise InputError(f"Expected list in {input_json_path}, got {type(data).__name__}")
        
        if not data:
            logger.warning(f"Empty list in {input_json_path}")
            return []
        
        if not (isinstance(data[0], dict) and "url" in data[0]):
            raise InputError(f"Items in {input_json_path} must be dicts with a 'url' key")
        
        urls = [item.get("url", "") for item in data]
        urls = [url for url in urls if url]  # Filter out empty URLs
        
        logger.info(f"Loaded {len(urls)} URLs from {input_json_path}")
        return urls
        
    except Exception as e:
        if not isinstance(e, InputError):
            logger.error(f"Unexpected error loading URLs: {e}", exc_info=True)
            raise InputError(f"Error loading URLs: {str(e)}")
        raise

def filter_urls_to_crawl(all_urls: List[str], changed_urls: List[str]) -> List[str]:
    """
    Filter the list of all URLs to only include those that have changed.
    
    Args:
        all_urls: All URLs from the latest sitemap
        changed_urls: URLs that have changed since the previous sitemap
    
    Returns:
        List of URLs to crawl
    """
    # Convert changed_urls to a set for O(1) lookups
    changed_set = set(changed_urls)
    
    # Filter all_urls to only include those in changed_set
    urls_to_crawl = [url for url in all_urls if url in changed_set]
    
    logger.info(f"Filtered {len(all_urls)} URLs to {len(urls_to_crawl)} for crawling")
    return urls_to_crawl

async def crawl_urls(
    urls: List[str],
    headless: bool = True,
    max_session_permit: int = 5,
    memory_threshold_percent: float = 70.0,
    max_retries: int = 3,
    retry_delay: float = 2.0,
) -> Dict[str, str]:
    """
    Crawl a list of URLs and extract their content, ensuring partial results are returned even if some fail.
    
    Args:
        urls: List of URLs to crawl
        headless: Whether to run browser in headless mode
        max_session_permit: Maximum number of parallel browser sessions
        memory_threshold_percent: Memory threshold for adaptive dispatcher
        max_retries: Maximum number of retries for failed crawls
        retry_delay: Delay between retries in seconds
    
    Returns:
        Dictionary mapping URLs to their extracted content
    """
    if not urls:
        logger.info("No URLs to crawl")
        return {}
    
    logger.info(f"Crawling {len(urls)} URLs with max_session_permit={max_session_permit}")
    
    # Initialize result dict and failed URLs list
    results = {}
    failed_urls = []
    
    # Configure browser
    browser_config = BrowserConfig(
        headless=headless,
        verbose=False,
        extra_args=["--no-sandbox", "--disable-setuid-sandbox"],
    )
    
    # Configure crawler run parameters
    run_config = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        excluded_tags=["header", "footer", "nav", "form", "script", "style", "iframe"],
        check_robots_txt=True,
        wait_until="networkidle",
        page_timeout=500000,
        stream=False,

    )
    
    # Configure memory-adaptive dispatcher
    dispatcher = MemoryAdaptiveDispatcher(
        memory_threshold_percent=memory_threshold_percent,
        check_interval=1.0,
        max_session_permit=max_session_permit,
        monitor=CrawlerMonitor()
    )
    
    # Initial crawl
    try:
        async with AsyncWebCrawler(config=browser_config) as crawler:
            monitor = CrawlerMonitor()
            results_list = await crawler.arun_many(
                urls=urls,
                config=run_config,
                dispatcher=dispatcher,
                monitor=monitor,
            )
            
            # Process initial results
            for res in results_list:
                if not res.success:
                    logger.warning(f"Error crawling {res.url}: {res.error_message}")
                    failed_urls.append(res.url)
                else:
                    content = res.markdown or ""
                    cleaned_content = clean_content(res.url, content)
                    
                    # Only add non-empty content to results
                    if cleaned_content:
                        results[res.url] = cleaned_content
                    else:
                        logger.info(f"Skipping URL (empty after cleaning): {res.url}")

    except Exception as e:
        logger.error(f"Error during initial crawling: {e}", exc_info=True)
        # Continue with whatever results we have
    
    # Handle retries for failed URLs
    if failed_urls and max_retries > 0:
        logger.info(f"Retrying {len(failed_urls)} failed URLs (attempt 1/{max_retries})")
        
        for retry in range(max_retries):
            if not failed_urls:
                break
                
            await asyncio.sleep(retry_delay * (retry + 1))
            
            try:
                retry_results = await crawler.arun_many(
                    urls=failed_urls,
                    config=run_config,
                    dispatcher=dispatcher,
                )
                
                # Process retry results
                still_failed = []
                for res in retry_results:
                    if not res.success:
                        logger.warning(f"Still failed after retry {retry+1}: {res.url}")
                        still_failed.append(res.url)
                    else:
                        logger.info(f"Successfully crawled on retry {retry+1}: {res.url}")
                        content = res.markdown or ""
                        cleaned_content = clean_content(res.url, content)
                        
                        # Only add non-empty content to results
                        if cleaned_content:
                            results[res.url] = cleaned_content
                        else:
                            logger.info(f"Skipping URL (empty after cleaning): {res.url}")
                
                failed_urls = still_failed
                
            except Exception as e:
                logger.error(f"Error during retry {retry+1}: {e}", exc_info=True)
                if retry < max_retries - 1:
                    logger.info("Continuing with next retry attempt")
                else:
                    logger.warning("All retry attempts failed for some URLs")
                    break
        
        if failed_urls:
            logger.warning(f"{len(failed_urls)} URLs failed after all retries")
    
    # Log final stats
    success_count = len(results)
    fail_count = len(failed_urls)
    total = len(urls)
    success_rate = (success_count / total * 100) if total > 0 else 0
    
    logger.info(f"Crawling complete: {success_count}/{total} successful ({success_rate:.1f}%)")
    if fail_count:
        logger.warning(f"Failed to crawl {fail_count} URLs")
    
    return results

def save_results(
    results: Dict[str, str],
    output_dir: str = "page_contents",
    date_str: Optional[str] = None,
) -> str:
    """
    Save crawl results to a JSON file in the specified directory.
    
    Args:
        results: Dictionary mapping URLs to their content
        output_dir: Directory to save results in
        date_str: Date string for filename (default: today's date)
    
    Returns:
        Path to the saved file
    
    Raises:
        OutputError: If saving fails
    """
    try:
        # Create output directory if it doesn't exist
        os.makedirs(output_dir, exist_ok=True)
        
        # Use today's date if not specified
        if not date_str:
            date_str = datetime.now().strftime("%Y-%m-%d")
        
        # Define output path
        output_path = os.path.join(output_dir, f"{date_str}.json")
        
        # Save results
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        
        logger.info(f"Saved {len(results)} page contents to {output_path}")
        return output_path
        
    except (IOError, OSError) as e:
        logger.error(f"I/O error saving results: {e}", exc_info=True)
        raise OutputError(f"Error saving results: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error saving results: {e}", exc_info=True)
        raise OutputError(f"Unexpected error saving results: {str(e)}")

async def extract_and_save_contents(
    sitemap_dir: str = "sitemaps",
    output_dir: str = "page_contents",
    headless: bool = True,
    max_session_permit: int = 5,
    memory_threshold_percent: float = 70.0,
    max_retries: int = 3,
) -> Dict[str, Any]:
    """
    Main function to extract and save contents from URLs in sitemap files.
    
    Args:
        sitemap_dir: Directory containing sitemap JSON files
        output_dir: Directory to save page contents in
        headless: Whether to run browser in headless mode
        max_session_permit: Maximum number of parallel browser sessions
        memory_threshold_percent: Memory threshold for adaptive dispatcher
        max_retries: Maximum number of retries for failed crawls
    
    Returns:
        Dictionary with execution results
    """
    start_time = time.time()
    result = {
        "success": False,
        "message": "",
        "date": datetime.now().strftime("%Y-%m-%d"),
        "crawled_urls_count": 0,
        "output_path": "",
        "execution_time_seconds": 0,
        "error": None
    }
    
    try:
        # 1. Get latest sitemap path
        sitemap_files = sorted(Path(sitemap_dir).glob("*.json"), 
                             key=lambda p: datetime.strptime(p.stem, "%Y-%m-%d").date())
        
        if not sitemap_files:
            raise InputError(f"No sitemap files found in {sitemap_dir}")
        
        latest_sitemap_path = str(sitemap_files[-1])
        date_str = Path(latest_sitemap_path).stem  # YYYY-MM-DD
        logger.info(f"Using latest sitemap: {latest_sitemap_path}")
        
        # 2. Load all URLs from the latest sitemap
        all_urls = load_urls_from_json(latest_sitemap_path)
        
        # 3. Determine changed URLs by comparing with previous sitemap
        changed_urls, is_first_run = await get_sitemap_changes(sitemap_dir)
        
        # 4. Determine which URLs to crawl
        urls_to_crawl = all_urls if is_first_run else changed_urls
        
        # 5. Crawl URLs
        if urls_to_crawl:
            logger.info(f"Starting crawl of {len(urls_to_crawl)} URLs")
            results = await crawl_urls(
                urls=urls_to_crawl,
                headless=headless,
                max_session_permit=max_session_permit,
                memory_threshold_percent=memory_threshold_percent,
                max_retries=max_retries,
            )
            
            result["crawled_urls_count"] = len(results)
            
            # 6. Save results
            output_path = save_results(results, output_dir, date_str)
            result["output_path"] = output_path
            
            if is_first_run:
                result["message"] = f"First run: extracted {len(results)} pages"
            else:
                result["message"] = f"Incremental run: extracted {len(results)} changed pages"
                
        else:
            logger.info("No changes detected, creating empty results file")
            # Save empty results with today's date
            output_path = save_results({}, output_dir, date_str)
            result["output_path"] = output_path
            result["message"] = "No changes detected since previous crawl"
        
        result["success"] = True
        
    except InputError as e:
        result["message"] = f"Input error: {str(e)}"
        result["error"] = str(e)
        logger.error(result["message"])
        
    except CrawlExecutionError as e:
        result["message"] = f"Crawl execution error: {str(e)}"
        result["error"] = str(e)
        logger.error(result["message"])
        
    except OutputError as e:
        result["message"] = f"Output error: {str(e)}"
        result["error"] = str(e)
        logger.error(result["message"])
        
    except Exception as e:
        result["message"] = f"Unexpected error: {str(e)}"
        result["error"] = str(e)
        logger.error(f"Unexpected error in extract_and_save_contents: {e}", exc_info=True)
    
    finally:
        # Calculate execution time
        execution_time = time.time() - start_time
        result["execution_time_seconds"] = round(execution_time, 2)
        logger.info(f"Total execution time: {execution_time:.2f} seconds")
        
        # Return execution results
        return result

async def main():
    """Command-line entry point."""
    try:
        # Configuration parameters
        config = {
            "sitemap_dir": "sitemaps",
            "output_dir": "page_contents",
            "headless": True,
            "max_session_permit": 5,
            "memory_threshold_percent": 70.0,
            "max_retries": 3,
        }
        
        # Run extraction process
        result = await extract_and_save_contents(**config)
        
        # Log final status
        if result["success"]:
            logger.info(f"Process completed successfully: {result['message']}")
        else:
            logger.error(f"Process failed: {result['message']}")
            
        return result
        
    except KeyboardInterrupt:
        logger.info("Process interrupted by user")
        return {"success": False, "message": "Process interrupted by user"}
        
    except Exception as e:
        logger.critical(f"Fatal error in main: {e}", exc_info=True)
        return {"success": False, "message": f"Fatal error: {str(e)}"}


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nProcess interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"Fatal error: {e}")
        sys.exit(1)
