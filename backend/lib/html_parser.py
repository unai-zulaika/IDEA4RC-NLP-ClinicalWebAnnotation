"""
Utility functions for parsing HTML files and extracting JSON from <script> tags.
"""

import re
import json
from pathlib import Path
from typing import Optional, Dict, Any, List
from bs4 import BeautifulSoup


def extract_json_from_script_tag(html_content: str, variable_name: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Extract JSON variable from a <script> tag in HTML content.
    
    Args:
        html_content: The HTML content as a string
        variable_name: Optional name of the variable to extract (e.g., "window.data" or "data")
                      If None, will try to extract any JSON object from script tags
    
    Returns:
        The parsed JSON object, or None if not found
    
    Examples:
        # Extract a specific variable: var data = {...};
        data = extract_json_from_script_tag(html, "data")
        
        # Extract window.myData = {...};
        data = extract_json_from_script_tag(html, "window.myData")
        
        # Extract any JSON object from script tags
        data = extract_json_from_script_tag(html)
    """
    if variable_name:
        # Method 1: Extract specific variable using regex
        # Pattern matches: var variable_name = {...}; or window.variable_name = {...};
        patterns = [
            # var variable_name = {...};
            rf'\bvar\s+{re.escape(variable_name)}\s*=\s*(\{{.*?\}})\s*;',
            # let variable_name = {...};
            rf'\blet\s+{re.escape(variable_name)}\s*=\s*(\{{.*?\}})\s*;',
            # const variable_name = {...};
            rf'\bconst\s+{re.escape(variable_name)}\s*=\s*(\{{.*?\}})\s*;',
            # window.variable_name = {...};
            rf'window\.{re.escape(variable_name)}\s*=\s*(\{{.*?\}})\s*;',
            # variable_name = {...};
            rf'\b{re.escape(variable_name)}\s*=\s*(\{{.*?\}})\s*;',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, html_content, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(1))
                except json.JSONDecodeError:
                    continue
        
        # Method 2: Using BeautifulSoup to find script tags and search within them
        soup = BeautifulSoup(html_content, 'html.parser')
        for script in soup.find_all('script'):
            if script.string:
                for pattern in patterns:
                    match = re.search(pattern, script.string, re.DOTALL)
                    if match:
                        try:
                            return json.loads(match.group(1))
                        except json.JSONDecodeError:
                            continue
    else:
        # Extract any JSON object from script tags
        soup = BeautifulSoup(html_content, 'html.parser')
        for script in soup.find_all('script'):
            if script.string:
                # Try to find JSON objects in the script content
                # Look for patterns like {...} or [{...}]
                json_patterns = [
                    r'(\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\})',  # Nested objects
                    r'(\[[^\]]*\])',  # Arrays
                ]
                
                for pattern in json_patterns:
                    matches = re.finditer(pattern, script.string, re.DOTALL)
                    for match in matches:
                        try:
                            return json.loads(match.group(1))
                        except json.JSONDecodeError:
                            continue
    
    return None


def extract_all_json_from_script_tags(html_content: str) -> List[Dict[str, Any]]:
    """
    Extract all JSON objects from <script> tags in HTML content.
    
    Args:
        html_content: The HTML content as a string
    
    Returns:
        List of all parsed JSON objects found in script tags
    """
    results = []
    soup = BeautifulSoup(html_content, 'html.parser')
    
    for script in soup.find_all('script'):
        if script.string:
            # Find all JSON-like objects
            json_pattern = r'(\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\})'
            matches = re.finditer(json_pattern, script.string, re.DOTALL)
            
            for match in matches:
                try:
                    json_obj = json.loads(match.group(1))
                    results.append(json_obj)
                except json.JSONDecodeError:
                    continue
    
    return results


def load_html_and_extract_json(file_path: str | Path, variable_name: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Load an HTML file and extract JSON variable from <script> tag.
    
    Args:
        file_path: Path to the HTML file
        variable_name: Optional name of the variable to extract
    
    Returns:
        The parsed JSON object, or None if not found
    
    Example:
        data = load_html_and_extract_json("page.html", "myData")
    """
    file_path = Path(file_path)
    
    if not file_path.exists():
        raise FileNotFoundError(f"HTML file not found: {file_path}")
    
    with open(file_path, 'r', encoding='utf-8') as f:
        html_content = f.read()
    
    return extract_json_from_script_tag(html_content, variable_name)


# Example usage
if __name__ == "__main__":
    # Example HTML content
    example_html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Example</title>
    </head>
    <body>
        <script>
            var myData = {
                "name": "John",
                "age": 30,
                "items": [1, 2, 3]
            };
        </script>
    </body>
    </html>
    """
    
    # Extract the JSON
    data = extract_json_from_script_tag(example_html, "myData")
    print("Extracted data:", data)
    
    # Or extract any JSON
    data = extract_json_from_script_tag(example_html)
    print("Any JSON found:", data)

