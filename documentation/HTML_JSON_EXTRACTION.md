# Extracting JSON from HTML Script Tags

This guide shows how to extract JSON variables from `<script>` tags in HTML files.

## Python (Backend)

### Basic Usage

```python
from backend.lib.html_parser import load_html_and_extract_json, extract_json_from_script_tag

# Method 1: Load from file
data = load_html_and_extract_json("path/to/file.html", variable_name="myData")

# Method 2: Extract from HTML string
html_content = """
<script>
    var myData = {
        "name": "John",
        "age": 30
    };
</script>
"""
data = extract_json_from_script_tag(html_content, "myData")
print(data)  # {'name': 'John', 'age': 30}
```

### Supported Variable Patterns

The parser supports multiple JavaScript variable declaration patterns:

- `var myData = {...};`
- `let myData = {...};`
- `const myData = {...};`
- `window.myData = {...};`
- `myData = {...};`

### Extract All JSON Objects

```python
from backend.lib.html_parser import extract_all_json_from_script_tags

html_content = """
<script>
    var data1 = {"key1": "value1"};
    var data2 = {"key2": "value2"};
</script>
"""

all_json = extract_all_json_from_script_tags(html_content)
# Returns: [{'key1': 'value1'}, {'key2': 'value2'}]
```

### Example: FastAPI Endpoint

```python
from fastapi import APIRouter, UploadFile, File
from backend.lib.html_parser import extract_json_from_script_tag

router = APIRouter()

@router.post("/extract-json")
async def extract_json_from_html(file: UploadFile = File(...)):
    """Upload HTML file and extract JSON from script tag"""
    content = await file.read()
    html_content = content.decode('utf-8')
    
    # Extract JSON (adjust variable_name as needed)
    data = extract_json_from_script_tag(html_content, variable_name="myData")
    
    if data:
        return {"success": True, "data": data}
    else:
        return {"success": False, "error": "JSON not found"}
```

## JavaScript/TypeScript (Frontend)

### Basic Usage

```typescript
import { extractJsonFromScriptTag, loadHtmlAndExtractJson } from '@/lib/htmlParser';

// Method 1: Extract from HTML string
const htmlContent = `
<script>
    var myData = {
        "name": "John",
        "age": 30
    };
</script>
`;

const data = extractJsonFromScriptTag(htmlContent, "myData");
console.log(data); // {name: "John", age: 30}

// Method 2: Load from file
const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
if (fileInput.files && fileInput.files[0]) {
    const data = await loadHtmlAndExtractJson(fileInput.files[0], "myData");
    console.log(data);
}
```

### Extract All JSON Objects

```typescript
import { extractAllJsonFromScriptTags } from '@/lib/htmlParser';

const htmlContent = `
<script>
    var data1 = {"key1": "value1"};
    var data2 = {"key2": "value2"};
</script>
`;

const allJson = extractAllJsonFromScriptTags(htmlContent);
// Returns: [{key1: "value1"}, {key2: "value2"}]
```

### Example: React Component

```typescript
'use client';

import { useState } from 'react';
import { loadHtmlAndExtractJson } from '@/lib/htmlParser';

export default function HtmlJsonExtractor() {
    const [data, setData] = useState<any>(null);

    const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0];
        if (file) {
            const jsonData = await loadHtmlAndExtractJson(file, "myData");
            setData(jsonData);
        }
    };

    return (
        <div>
            <input type="file" accept=".html" onChange={handleFileChange} />
            {data && <pre>{JSON.stringify(data, null, 2)}</pre>}
        </div>
    );
}
```

## HTML File Format

The parser expects HTML files with JSON in script tags like this:

```html
<!DOCTYPE html>
<html>
<head>
    <title>Example</title>
</head>
<body>
    <script>
        var myData = {
            "name": "John Doe",
            "age": 30,
            "items": [1, 2, 3],
            "nested": {
                "key": "value"
            }
        };
    </script>
</body>
</html>
```

## Notes

- The parser handles nested JSON objects and arrays
- Multiple script tags are supported
- If the variable name is not specified, the parser will try to extract any JSON object found
- The parser is case-sensitive for variable names
- Both single-line and multi-line JSON are supported

