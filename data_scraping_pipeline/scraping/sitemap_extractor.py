import os
import time
import json
import urllib3
import requests
from glob import glob
from loguru import logger
from datetime import datetime
import xml.etree.ElementTree as ET
from usp.exceptions import SitemapException
from usp.tree import sitemap_tree_for_homepage
from urllib3.exceptions import InsecureRequestWarning
from typing import List, Dict, Tuple, Optional, Any
from requests.exceptions import RequestException, HTTPError, Timeout, ConnectionError

# Suppress insecure request warnings
urllib3.disable_warnings(InsecureRequestWarning)

# Type aliases
SitemapUrl = Dict[str, str]
SitemapUrlList = List[SitemapUrl]
LastModifiedMap = Dict[str, str]


class SitemapExtractionError(Exception):
    """Base exception for sitemap extraction errors."""
    pass


class SitemapFetchError(SitemapExtractionError):
    """Failed to fetch sitemap from URL."""
    pass


class SitemapParseError(SitemapExtractionError):
    """Failed to parse sitemap XML content."""
    pass


class SitemapOutputError(SitemapExtractionError):
    """Failed to output sitemap data."""
    pass


class SitemapProcessingError(SitemapExtractionError):
    """Generic processing error for sitemap operations."""
    pass


# ─── NETWORK UTILITIES ─────────────────────────────────────────────────────────

def fetch_sitemap(url: str, timeout: int = 30, retries: int = 3, backoff_factor: float = 0.5) -> str:
    """
    Fetch sitemap content from URL with retry logic.
    
    Args:
        url: The URL of the sitemap to fetch
        timeout: Request timeout in seconds
        retries: Number of retries before giving up
        backoff_factor: Exponential backoff factor between retries
        
    Returns:
        The sitemap content as a string
        
    Raises:
        SitemapFetchError: If unable to fetch the sitemap after retries
    """
    logger.info(f"Fetching sitemap from URL: {url}")
    
    session = requests.Session()
    
    for attempt in range(retries):
        try:
            resp = session.get(url, timeout=timeout, verify=True)
            resp.raise_for_status()
            return resp.text
            
        except HTTPError as e:
            error_msg = f"HTTP error occurred: {e} (status code: {e.response.status_code})"
            if attempt == retries - 1:
                logger.error(error_msg)
                raise SitemapFetchError(error_msg) from e
            
        except Timeout as e:
            error_msg = f"Request timed out: {e}"
            if attempt == retries - 1:
                logger.error(error_msg)
                raise SitemapFetchError(error_msg) from e
            
        except ConnectionError as e:
            error_msg = f"Connection error: {e}"
            if attempt == retries - 1:
                logger.error(error_msg)
                raise SitemapFetchError(error_msg) from e
            
        except RequestException as e:
            error_msg = f"Request exception: {e}"
            if attempt == retries - 1:
                logger.error(error_msg)
                raise SitemapFetchError(error_msg) from e
        
        # Calculate backoff time
        backoff_time = backoff_factor * (2 ** attempt)
        logger.warning(f"Retrying in {backoff_time:.1f} seconds... (attempt {attempt + 1}/{retries})")
        time.sleep(backoff_time)
    
    # This should not be reached due to the exception handling above
    raise SitemapFetchError(f"Failed to fetch sitemap after {retries} attempts")


# ─── XML PARSING UTILITIES ─────────────────────────────────────────────────────

def parse_index_sitemap(sitemap_content: str) -> List[str]:
    """
    Parse an index sitemap to extract child sitemap URLs.
    
    Args:
        sitemap_content: XML content of the sitemap index
        
    Returns:
        List of child sitemap URLs
        
    Raises:
        SitemapParseError: If unable to parse the sitemap index
    """
    logger.info("Parsing index sitemap")
    urls = []
    
    try:
        root = ET.fromstring(sitemap_content)
        ns = {"ns": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        
        for sm in root.findall("ns:sitemap", ns):
            loc_element = sm.find("ns:loc", ns)
            if loc_element is not None and loc_element.text:
                urls.append(loc_element.text.strip())
                
    except ET.ParseError as e:
        error_msg = f"XML parse error in index sitemap: {e}"
        logger.error(error_msg)
        raise SitemapParseError(error_msg) from e
        
    except Exception as e:
        error_msg = f"Unexpected error parsing index sitemap: {e}"
        logger.error(error_msg)
        raise SitemapParseError(error_msg) from e
    
    if not urls:
        logger.warning("No sitemap URLs found in index sitemap")
        
    logger.info(f"Found {len(urls)} child sitemaps in index")
    return urls


def parse_sitemap(sitemap_content: str) -> Tuple[SitemapUrlList, LastModifiedMap]:
    """
    Parse a sitemap to extract URLs and their last modified timestamps.
    
    Args:
        sitemap_content: XML content of the sitemap
        
    Returns:
        Tuple containing:
        - List of dicts with 'url' and 'lastmodified' keys
        - Dictionary mapping URLs to last modified timestamps
        
    Raises:
        SitemapParseError: If unable to parse the sitemap
    """
    logger.info("Parsing sitemap")
    urls_list = []
    lastmod_map = {}
    
    try:
        root = ET.fromstring(sitemap_content)
        ns = {"ns": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        
        for url_element in root.findall("ns:url", ns):
            loc_element = url_element.find("ns:loc", ns)
            lastmod_element = url_element.find("ns:lastmod", ns)
            
            if loc_element is not None and loc_element.text:
                url = loc_element.text.strip()
                if not url.lower().startswith(("http://", "https://")):
                    logger.warning(f"Skipping non‑HTTP URL: {url}")
                    continue
                lastmod = lastmod_element.text.strip() if lastmod_element is not None and lastmod_element.text else ""
                
                entry = {"url": url, "lastmodified": lastmod}
                urls_list.append(entry)
                lastmod_map[url] = lastmod
                
    except ET.ParseError as e:
        error_msg = f"XML parse error in sitemap: {e}"
        logger.error(error_msg)
        raise SitemapParseError(error_msg) from e
        
    except Exception as e:
        error_msg = f"Unexpected error parsing sitemap: {e}"
        logger.error(error_msg)
        raise SitemapParseError(error_msg) from e
    
    if not urls_list:
        logger.warning("No URLs found in sitemap")
        
    logger.info(f"Found {len(urls_list)} URLs in sitemap")
    return urls_list, lastmod_map


def get_all_urls_and_last_modified(
    sitemap_url: str, 
    additional_urls: List[str] = [],
    timeout: int = 30,
    retries: int = 3
) -> Tuple[SitemapUrlList, LastModifiedMap]:
    """
    Get all URLs and last modified timestamps from a sitemap, including its children.
    
    Args:
        sitemap_url: URL of the sitemap or sitemap index
        additional_urls: Additional URLs to include
        timeout: Request timeout in seconds
        retries: Number of retries for fetch operations
        
    Returns:
        Tuple containing:
        - List of dicts with 'url' and 'lastmodified' keys
        - Dictionary mapping URLs to last modified timestamps
        
    Raises:
        SitemapFetchError: If unable to fetch the sitemap
        SitemapParseError: If unable to parse the sitemap
    """
    try:
        content = fetch_sitemap(sitemap_url, timeout=timeout, retries=retries)
        
        # Check if this is a sitemap index
        if "<sitemapindex" in content:
            logger.info("Detected sitemap index file")
            all_urls_list, all_lastmod_map = [], {}
            
            # Process each child sitemap
            child_sitemaps = parse_index_sitemap(content)
            for child_url in child_sitemaps:
                try:
                    child_content = fetch_sitemap(child_url, timeout=timeout, retries=retries)
                    child_list, child_map = parse_sitemap(child_content)
                    all_urls_list.extend(child_list)
                    all_lastmod_map.update(child_map)
                except (SitemapFetchError, SitemapParseError) as e:
                    logger.error(f"Error processing child sitemap {child_url}: {e}")
                    # Continue with other child sitemaps
        else:
            logger.info("Processing regular sitemap file")
            all_urls_list, all_lastmod_map = parse_sitemap(content)
            
        # Add additional URLs if provided
        for url in additional_urls:
            url = url.strip()
            if not url:
                continue
            if not url.lower().startswith(("http://", "https://")):
                logger.warning(f"Skipping additional non‑HTTP URL: {url}")
                continue
            entry = {"url": url, "lastmodified": ""}
            all_urls_list.append(entry)
            all_lastmod_map[url] = ""
                
        # Deduplicate: rebuild the list from our lastmod_map keys
        deduped_list = [
            {"url": url, "lastmodified": lastmod}
            for url, lastmod in all_lastmod_map.items()
        ]
        logger.info(f"Total unique URLs processed: {len(deduped_list)}")
        return deduped_list, all_lastmod_map
        
    except (SitemapFetchError, SitemapParseError) as e:
        # Re-raise these specific exceptions
        raise
    except Exception as e:
        error_msg = f"Unexpected error in sitemap extraction: {e}"
        logger.error(error_msg)
        raise SitemapProcessingError(error_msg) from e


# ─── FILE HANDLING UTILITIES ───────────────────────────────────────────────────

def get_latest_two_sitemap_paths(base_dir: str = "sitemaps") -> Tuple[str, str]:
    """
    Get the paths to the two most recent sitemap JSON files.
    
    Args:
        base_dir: Directory containing sitemap JSON files
        
    Returns:
        Tuple of (yesterday_path, today_path)
        
    Raises:
        SitemapProcessingError: If fewer than two valid sitemap files exist
    """
    if not os.path.isdir(base_dir):
        error_msg = f"Directory not found: {base_dir}"
        logger.error(error_msg)
        raise SitemapProcessingError(error_msg)
    
    pattern = os.path.join(base_dir, "*.json")
    files = glob(pattern)
    
    # Parse filenames into date objects
    dated_files = []
    for file_path in files:
        name = os.path.basename(file_path).rsplit(".", 1)[0]  # "2025-04-17"
        try:
            dt = datetime.strptime(name, "%Y-%m-%d").date()
            dated_files.append((dt, file_path))
        except ValueError:
            logger.warning(f"Skipping non-date filename: {file_path}")
            continue
    
    # Sort by date ascending
    dated_files.sort(key=lambda x: x[0])
    
    if len(dated_files) < 2:
        error_msg = f"Need at least two dated JSON files in {base_dir}/ to compare (found {len(dated_files)})"
        logger.error(error_msg)
        raise SitemapProcessingError(error_msg)
    
    # The last two entries
    yesterday_path = dated_files[-2][1]
    today_path = dated_files[-1][1]
    
    logger.info(f"Using comparison files: {os.path.basename(yesterday_path)} and {os.path.basename(today_path)}")
    return yesterday_path, today_path


def save_sitemap_data(
    data: SitemapUrlList, 
    base_dir: str, 
    filename: Optional[str] = None
) -> str:
    """
    Save sitemap data to a JSON file.
    
    Args:
        data: List of sitemap URL entries
        base_dir: Directory to save the file in
        filename: Custom filename (default: current date)
        
    Returns:
        Path to the saved file
        
    Raises:
        SitemapOutputError: If unable to save the data
    """
    try:
        os.makedirs(base_dir, exist_ok=True)
        
        if not filename:
            today = datetime.utcnow().date().isoformat()  # YYYY-MM-DD
            filename = f"{today}.json"
            
        file_path = os.path.join(base_dir, filename)
        
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            
        logger.info(f"Sitemap data saved to {file_path}")
        return file_path
        
    except IOError as e:
        error_msg = f"I/O error saving sitemap data: {e}"
        logger.error(error_msg)
        raise SitemapOutputError(error_msg) from e
        
    except Exception as e:
        error_msg = f"Unexpected error saving sitemap data: {e}"
        logger.error(error_msg)
        raise SitemapOutputError(error_msg) from e


def load_sitemap_data(file_path: str) -> SitemapUrlList:
    """
    Load sitemap data from a JSON file.
    
    Args:
        file_path: Path to the JSON file
        
    Returns:
        List of sitemap URL entries
        
    Raises:
        SitemapOutputError: If unable to load the data
    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        # Validate data format
        if not isinstance(data, list):
            raise ValueError("Expected a list of URL entries")
            
        for entry in data:
            if not isinstance(entry, dict) or "url" not in entry:
                raise ValueError("Each entry must be a dict with a 'url' key")
                
        return data
        
    except json.JSONDecodeError as e:
        error_msg = f"JSON decode error in {file_path}: {e}"
        logger.error(error_msg)
        raise SitemapOutputError(error_msg) from e
        
    except IOError as e:
        error_msg = f"I/O error loading {file_path}: {e}"
        logger.error(error_msg)
        raise SitemapOutputError(error_msg) from e
        
    except Exception as e:
        error_msg = f"Unexpected error loading {file_path}: {e}"
        logger.error(error_msg)
        raise SitemapOutputError(error_msg) from e


# ─── COMPARISON UTILITIES ─────────────────────────────────────────────────────

def compare_sitemaps(old_path: str, new_path: str) -> List[str]:
    """
    Compare two sitemap JSON files and identify changes.
    
    Args:
        old_path: Path to the older sitemap JSON file
        new_path: Path to the newer sitemap JSON file
        
    Returns:
        List of URLs that are new or have changed
        
    Raises:
        SitemapOutputError: If unable to load sitemap data
        SitemapProcessingError: If general processing error occurs
    """
    logger.info(f"Comparing sitemaps: {old_path} and {new_path}")
    
    try:
        # Load and convert to URL->lastmod maps
        def create_url_map(file_path: str) -> Dict[str, str]:
            data = load_sitemap_data(file_path)
            return {item["url"]: item.get("lastmodified", "") for item in data}
        
        old_map = create_url_map(old_path)
        new_map = create_url_map(new_path)
        
        # Find URLs that are new or have changed lastmod
        changed_urls = []
        for url, lastmod in new_map.items():
            if url not in old_map or old_map[url] != lastmod:
                changed_urls.append(url)
                
        logger.info(f"Found {len(changed_urls)} changed or new URLs")
        return changed_urls
        
    except SitemapOutputError:
        # Re-raise load errors
        raise
    except Exception as e:
        error_msg = f"Error comparing sitemaps: {e}"
        logger.error(error_msg)
        raise SitemapProcessingError(error_msg) from e


# ─── MAIN EXTRACTION FUNCTION ────────────────────────────────────────────────

def extract_sitemap_links(
    sitemap_url: str,
    library: str = "ET",
    save_json: bool = True,
    base_dir: str = "sitemaps",
    json_filename: Optional[str] = None,
    timeout: int = 30,
    retries: int = 3,
    additional_urls: List[str] = []
) -> SitemapUrlList:
    """
    Extract URLs from a sitemap.
    
    Args:
        sitemap_url: URL of the sitemap
        library: Library to use ('ET' for ElementTree or 'usp' for Ultimate Sitemap Parser)
        save_json: Whether to save the results to a JSON file
        base_dir: Directory to save JSON files in
        json_filename: Custom filename for the output JSON
        timeout: Request timeout in seconds
        retries: Number of retries for fetch operations
        additional_urls: Additional URLs to include
        
    Returns:
        List of dicts with 'url' and 'lastmodified' keys
        
    Raises:
        SitemapExtractionError: Base exception for all extraction errors
    """
    logger.info(f"Starting sitemap extraction: {sitemap_url}")
    
    try:
        # Validate sitemap URL (basic check)
        if not isinstance(sitemap_url, str) or not sitemap_url:
            raise ValueError("Sitemap URL cannot be empty")
            
        if "sitemap" not in sitemap_url.lower():
            logger.warning(
                f"URL '{sitemap_url}' may not be a valid sitemap URL (missing 'sitemap' in path)"
            )
        
        # Extract URLs using the specified library
        if library.lower() == "et":
            logger.info("Using ElementTree library for extraction")
            results, _ = get_all_urls_and_last_modified(
                sitemap_url, 
                additional_urls=additional_urls,
                timeout=timeout,
                retries=retries
            )
            
        elif library.lower() == "usp":
            logger.info("Using Ultimate Sitemap Parser library for extraction")
            results = []
            
            try:
                tree = sitemap_tree_for_homepage(sitemap_url)
                for page in tree.all_pages():
                    url = page.url
                    if not url.lower().startswith(("http://", "https://")):
                        logger.warning(f"Skipping non‑HTTP URL: {url}")
                        continue
                    results.append({
                        "url": url,
                        "lastmodified": str(page.last_modified) if page.last_modified else ""
                    })
                    
                # Add additional URLs if provided
                for url in additional_urls:
                    if url:  # Skip empty URLs
                        results.append({"url": url, "lastmodified": ""})
                        
                logger.info(f"USP extraction complete: {len(results)} URLs")
                
            except SitemapException as e:
                error_msg = f"USP library error: {e}"
                logger.error(error_msg)
                raise SitemapParseError(error_msg) from e
                
            except Exception as e:
                error_msg = f"Unexpected error in USP parsing: {e}"
                logger.error(error_msg)
                raise SitemapParseError(error_msg) from e
                
        else:
            error_msg = f"Invalid library name: {library}. Use 'ET' or 'usp'."
            logger.error(error_msg)
            raise ValueError(error_msg)
        
        # Save results if requested
        if save_json:
            save_sitemap_data(results, base_dir, json_filename)
        
        return results
        
    except ValueError as e:
        error_msg = f"Validation error: {e}"
        logger.error(error_msg)
        raise SitemapExtractionError(error_msg) from e
        
    except (SitemapFetchError, SitemapParseError, SitemapOutputError) as e:
        # Re-raise specific errors
        raise
        
    except Exception as e:
        error_msg = f"Unexpected error in extraction: {e}"
        logger.error(error_msg)
        raise SitemapProcessingError(error_msg) from e


# ─── MAIN EXECUTION ────────────────────────────────────────────────────────────

def extract_sitemap(
    sitemap_url: str,
    base_dir: str = "sitemaps",
    library: str = "ET",
    compare: bool = True,
    timeout: int = 30,
    retries: int = 3,
    additional_urls: List[str] = []
) -> Dict[str, Any]:
    """
    Main execution function.
    
    Args:
        sitemap_url: URL of the sitemap
        base_dir: Directory to save JSON files in
        library: Library to use ('ET' or 'usp')
        compare: Whether to compare with previous snapshot
        timeout: Request timeout in seconds
        retries: Number of retries for fetch operations
        additional_urls: Additional URLs to include
        
    Returns:
        Dict with extraction results and any comparison results
    """
    result = {
        "success": False,
        "message": "",
        "urls_count": 0,
        "changed_urls": None,
        "changed_count": 0,
        "error": None
    }
    
    try:
        # 1. Extract today's sitemap (saves to sitemaps/YYYY-MM-DD.json)
        today_list = extract_sitemap_links(
            sitemap_url=sitemap_url,
            library=library,
            save_json=True,
            base_dir=base_dir,
            timeout=timeout,
            retries=retries,
            additional_urls=additional_urls
        )
        
        result["urls_count"] = len(today_list)
        
        # 2. List all existing snapshot files
        pattern = os.path.join(base_dir, "*.json")
        files = glob(pattern)
        
        # 3. Compare with previous snapshot if requested
        if compare and len(files) >= 2:
            try:
                # Get the two most recent files
                yesterday_path, today_path = get_latest_two_sitemap_paths(base_dir)
                logger.info(f"Comparing:\n  old: {yesterday_path}\n  new: {today_path}")
                
                # Compute URLs to re-crawl
                modified_urls = compare_sitemaps(yesterday_path, today_path)
                result["changed_urls"] = modified_urls
                result["changed_count"] = len(modified_urls)
                
                if modified_urls:
                    logger.info(f"URLs to re‑crawl ({len(modified_urls)}):")
                    for url in modified_urls[:10]:  # Log first 10
                        logger.info(f"  - {url}")
                    if len(modified_urls) > 10:
                        logger.info(f"  ... and {len(modified_urls) - 10} more")
                else:
                    logger.info("No URLs have changed since last snapshot")
                    
            except SitemapProcessingError as e:
                logger.warning(f"Comparison failed: {e}")
                result["message"] = f"Extraction successful but comparison failed: {e}"
                # Continue with success since extraction was successful
                
        elif compare:
            logger.info(
                "Not enough sitemap snapshots for comparison "
                f"(found {len(files)}, need at least 2)"
            )
            result["message"] = "Extraction successful but comparison skipped (insufficient snapshots)"
        else:
            result["message"] = "Extraction successful (comparison not requested)"
        
        result["success"] = True
        
    except SitemapExtractionError as e:
        error_msg = f"Sitemap extraction error: {e}"
        logger.error(error_msg)
        result["message"] = error_msg
        result["error"] = str(e)
        
    except Exception as e:
        error_msg = f"Unexpected error: {e}"
        logger.error(error_msg)
        result["message"] = error_msg
        result["error"] = str(e)
    
    return result


if __name__ == "__main__":
    # Configuration
    config = {
        "BASE_DIR": "sitemaps",
        "SITEMAP_URL": "https://webosmotic.com/sitemap.xml",
        "LIBRARY": "ET",
        "COMPARE": True,
        "TIMEOUT": 30,
        "RETRIES": 3,
        "ADDITIONAL_URLS": []
    }
    
    try:
        # Run the main process
        result = extract_sitemap(
            sitemap_url=config["SITEMAP_URL"],
            base_dir=config["BASE_DIR"],
            library=config["LIBRARY"],
            compare=config["COMPARE"],
            timeout=config["TIMEOUT"],
            retries=config["RETRIES"],
            additional_urls=config["ADDITIONAL_URLS"]
        )
        
        # Log final status
        if result["success"]:
            logger.info(f"Process completed successfully: {result['message']}")
            if result["changed_urls"]:
                logger.info(f"Found {result['changed_count']} changed URLs")
        else:
            logger.error(f"Process failed: {result['message']}")
            
    except KeyboardInterrupt:
        logger.info("Process interrupted by user")
        
    except Exception as e:
        logger.critical(f"Fatal error: {e}", exc_info=True)
