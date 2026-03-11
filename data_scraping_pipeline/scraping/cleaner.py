def should_skip_url(url: str) -> bool:
    """
    Check if the URL should be completely skipped during content extraction.
    
    Args:
        url: URL to check
        
    Returns:
        True if URL should be skipped, False otherwise
    """
    # URLs to be completely skipped (e.g., pages irrelevant for content storage)
    skip_urls = [
        "https://webosmotic.com/services/custom-ai-development-services/",
        "https://webosmotic.com/service/"
    ]
    
    # Check URL against the skip list, ignoring trailing slashes
    return any(url.rstrip('/') == skip_url.rstrip('/') for skip_url in skip_urls)


def should_keep_promo_text(url: str) -> bool:
    """
    Determine if promotional text at the end of the content should be preserved for this URL.
    
    Args:
        url: URL to check
        
    Returns:
        True if promotional text should be retained, False otherwise
    """
    # URLs for which promotional text is relevant and should remain
    keep_promo_urls = [
        "https://webosmotic.com/about-us/",
        "https://webosmotic.com/apply-job/",
        "https://webosmotic.com"
    ]
    
    # Check URL against the keep list, ignoring trailing slashes
    return any(url.rstrip('/') == keep_url.rstrip('/') for keep_url in keep_promo_urls)


def is_blog_post(url: str) -> bool:
    """
    Determine if the URL represents an individual blog post rather than the main blog page.
    
    Args:
        url: URL to check
        
    Returns:
        True if URL is a blog post, False otherwise
    """
    # Blog posts start with the blog base URL but aren't the blog homepage itself
    return url.startswith('https://webosmotic.com/blog/') and url != 'https://webosmotic.com/blog/'


def clean_blog_content(content: str) -> str:
    """
    Clean blog content by removing unnecessary navigation and social sharing links.
    
    This ensures that only the main informative content remains.
    
    Args:
        content: The raw blog content string
    
    Returns:
        Cleaned blog content with navigation and social sharing removed
    """
    lines = content.split('\n')
    title_line_index = -1
    
    # Find the line with the blog title, identified by a markdown bullet that isn't a link
    for i, line in enumerate(lines):
        if line.strip().startswith('* ') and not line.strip().startswith('* ['):
            title_line_index = i
            break

    # Locate the index of "Table of Contents" to identify start of actual blog content
    table_of_contents_index = next((i for i, line in enumerate(lines) if 'Table of Contents' in line), -1)
    
    if title_line_index >= 0 and table_of_contents_index > title_line_index:
        # Identify the first meaningful line after "Table of Contents"
        start_content_index = next((i for i in range(table_of_contents_index + 1, len(lines)) if lines[i].strip()), -1)
        
        if start_content_index > 0:
            # Construct cleaned content combining the blog title, table of contents, and main body
            new_content = '\n'.join(lines[title_line_index:table_of_contents_index + 1]) + '\n' + '\n'.join(lines[start_content_index:])
            return new_content
    
    # Return original content if no specific pattern found
    return content


def remove_promo_text(content: str) -> str:
    """
    Remove promotional text appended to the end of the content.
    
    Args:
        content: The original content string
    
    Returns:
        Content stripped of promotional message at the end
    """
    promo_text = "🚀 Get Instant Access to Your Exclusive Link!"
    
    # Remove promotional text and anything following it
    if promo_text in content:
        content = content.split(promo_text)[0].rstrip()
    
    return content


def clean_content(url: str, content: str) -> str:
    """
    Apply all validations and cleaning rules to the provided content.
    
    The sequence ensures irrelevant URLs are skipped, blog posts are specifically cleaned,
    and promotional texts are conditionally removed based on URL.

    Args:
        url: The URL of the content
        content: The raw content string

    Returns:
        Fully cleaned content or empty string if the URL should be skipped
    """
    # Skip URLs explicitly marked to be ignored
    if should_skip_url(url):
        return ""

    # Apply specific cleaning rules if content is identified as a blog post
    if is_blog_post(url):
        content = clean_blog_content(content)

    # Conditionally remove promotional text based on URL
    if not should_keep_promo_text(url):
        content = remove_promo_text(content)

    return content
