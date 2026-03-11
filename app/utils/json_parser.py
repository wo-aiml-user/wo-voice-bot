import re
import json
from loguru import logger

def clean_json_string(json_str):
    """Clean and normalize JSON string before parsing"""

    # Remove any markdown code block markers
    json_str = re.sub(r'```json\s*|\s*```', '', json_str)
    
    # Fix common JSON formatting issues
    json_str = re.sub(r'(?<!\\)"([^"]*?)(?<!\\)":', r'"\1":', json_str)  # Fix key quotes
    
    # Convert string booleans to proper JSON booleans
    json_str = re.sub(r'"(true|false)"', r'\1', json_str, flags=re.IGNORECASE)
    json_str = re.sub(r':\s*"(true|false)"', lambda m: ': ' + m.group(1).lower(), json_str, flags=re.IGNORECASE)
    json_str = re.sub(r'([,{])\s*"([^"]+)":\s*"(yes|no)"', lambda m: f'{m.group(1)} "{m.group(2)}": {m.group(3).lower()}', json_str, flags=re.IGNORECASE)  # Full key-value pairs
    
    # Fix list formatting issues
    json_str = re.sub(r'\[([^\]]*?)\]', lambda m: normalize_list_string(m.group(1)), json_str)
    
    return json_str.strip()

def normalize_list_string(list_str):
    """Normalize the format of list strings"""
    if not list_str.strip():
        return '[]'
    
    # Split by comma, handling both quoted and unquoted values
    items = re.findall(r'"[^"]*"|\'[^\']*\'|\S+', list_str)
    
    # Clean and normalize each item
    normalized = []
    for item in items:
        item = item.strip(' ,"\'')  # Remove quotes and extra spaces
        if item:  # Skip empty items
            # Add quotes if it's not a number
            if not re.match(r'^-?\d+(\.\d+)?$', item):
                item = f'"{item}"'
            normalized.append(item)
    
    return f'[{",".join(normalized)}]'

def parse_json_response(response_string):
    """Parse JSON response with robust error handling"""
    try:
        # First try direct JSON parsing
        return json.loads(response_string)
    except json.JSONDecodeError:
        # Clean and try again
        cleaned_json = clean_json_string(response_string)
        try:
            return json.loads(cleaned_json)
        except json.JSONDecodeError as e:
            logger.info(f"Normal JSON parsing failed and we are going with regex function")
            # Fall back to regex-based parsing for specific fields
            return extract_fields_with_regex(response_string)


def extract_fields_with_regex(text):
    """Extract fields using regex as a last resort"""
    result = {
        "ai": "",
        "document_references": [],
        "title": ""
    }

    # Extract AI response
    ai_match = re.search(r'"ai"\s*:\s*"(.*?)(?="\s*,\s*"[^"]+":|"\s*})', text, re.DOTALL)
    if ai_match:
        result["ai"] = ai_match.group(1).replace('\\n', '\n').replace('\\"', '"')
    
    # Extract document references
    refs_match = re.search(r'"document_references"\s*:\s*\[([^\]]*)\]', text, re.DOTALL)
    if refs_match:
        refs_str = refs_match.group(1).strip()
        if refs_str:
            # Split by comma and clean up
            refs = [ref.strip().strip('"').strip("'") for ref in refs_str.split(',')]
            result["document_references"] = refs

    # Extract title
    title_match = re.search(r'"title"\s*:\s*"([^"]*)"', text)
    if title_match:
        result["title"] = title_match.group(1)

    return result