/**
 * Utility functions for parsing HTML files and extracting JSON from <script> tags.
 */

/**
 * Extract JSON variable from a <script> tag in HTML content.
 * 
 * @param htmlContent - The HTML content as a string
 * @param variableName - Optional name of the variable to extract (e.g., "window.data" or "data")
 *                      If undefined, will try to extract any JSON object from script tags
 * @returns The parsed JSON object, or null if not found
 * 
 * @example
 * // Extract a specific variable: var data = {...};
 * const data = extractJsonFromScriptTag(html, "data");
 * 
 * // Extract window.myData = {...};
 * const data = extractJsonFromScriptTag(html, "window.myData");
 * 
 * // Extract any JSON object from script tags
 * const data = extractJsonFromScriptTag(html);
 */
export function extractJsonFromScriptTag(
  htmlContent: string,
  variableName?: string
): any | null {
  if (variableName) {
    // Method 1: Extract specific variable using regex
    // Pattern matches: var variable_name = {...}; or window.variable_name = {...};
    const patterns = [
      // var variable_name = {...};
      new RegExp(`\\bvar\\s+${escapeRegex(variableName)}\\s*=\\s*(\\{.*?\\})\\s*;`, 's'),
      // let variable_name = {...};
      new RegExp(`\\blet\\s+${escapeRegex(variableName)}\\s*=\\s*(\\{.*?\\})\\s*;`, 's'),
      // const variable_name = {...};
      new RegExp(`\\bconst\\s+${escapeRegex(variableName)}\\s*=\\s*(\\{.*?\\})\\s*;`, 's'),
      // window.variable_name = {...};
      new RegExp(`window\\.${escapeRegex(variableName)}\\s*=\\s*(\\{.*?\\})\\s*;`, 's'),
      // variable_name = {...};
      new RegExp(`\\b${escapeRegex(variableName)}\\s*=\\s*(\\{.*?\\})\\s*;`, 's'),
    ];

    for (const pattern of patterns) {
      const match = htmlContent.match(pattern);
      if (match && match[1]) {
        try {
          return JSON.parse(match[1]);
        } catch (e) {
          continue;
        }
      }
    }

    // Method 2: Using DOMParser to find script tags and search within them
    const parser = new DOMParser();
    const doc = parser.parseFromString(htmlContent, 'text/html');
    const scripts = doc.querySelectorAll('script');

    for (const script of scripts) {
      if (script.textContent) {
        for (const pattern of patterns) {
          const match = script.textContent.match(pattern);
          if (match && match[1]) {
            try {
              return JSON.parse(match[1]);
            } catch (e) {
              continue;
            }
          }
        }
      }
    }
  } else {
    // Extract any JSON object from script tags
    const parser = new DOMParser();
    const doc = parser.parseFromString(htmlContent, 'text/html');
    const scripts = doc.querySelectorAll('script');

    for (const script of scripts) {
      if (script.textContent) {
        // Try to find JSON objects in the script content
        // Look for patterns like {...} or [{...}]
        const jsonPatterns = [
          /(\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\})/s, // Nested objects
          /(\[[^\]]*\])/s, // Arrays
        ];

        for (const pattern of jsonPatterns) {
          const matches = script.textContent.matchAll(pattern);
          for (const match of matches) {
            if (match[1]) {
              try {
                return JSON.parse(match[1]);
              } catch (e) {
                continue;
              }
            }
          }
        }
      }
    }
  }

  return null;
}

/**
 * Extract all JSON objects from <script> tags in HTML content.
 * 
 * @param htmlContent - The HTML content as a string
 * @returns Array of all parsed JSON objects found in script tags
 */
export function extractAllJsonFromScriptTags(htmlContent: string): any[] {
  const results: any[] = [];
  const parser = new DOMParser();
  const doc = parser.parseFromString(htmlContent, 'text/html');
  const scripts = doc.querySelectorAll('script');

  for (const script of scripts) {
    if (script.textContent) {
      // Find all JSON-like objects
      const jsonPattern = /(\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\})/s;
      const matches = script.textContent.matchAll(jsonPattern);

      for (const match of matches) {
        if (match[1]) {
          try {
            const jsonObj = JSON.parse(match[1]);
            results.push(jsonObj);
          } catch (e) {
            continue;
          }
        }
      }
    }
  }

  return results;
}

/**
 * Load an HTML file and extract JSON variable from <script> tag.
 * 
 * @param file - File object or file path
 * @param variableName - Optional name of the variable to extract
 * @returns Promise that resolves to the parsed JSON object, or null if not found
 * 
 * @example
 * const file = event.target.files[0];
 * const data = await loadHtmlAndExtractJson(file, "myData");
 */
export async function loadHtmlAndExtractJson(
  file: File | string,
  variableName?: string
): Promise<any | null> {
  let htmlContent: string;

  if (typeof file === 'string') {
    // If it's a URL or path, fetch it
    const response = await fetch(file);
    htmlContent = await response.text();
  } else {
    // If it's a File object, read it
    htmlContent = await file.text();
  }

  return extractJsonFromScriptTag(htmlContent, variableName);
}

/**
 * Helper function to escape special regex characters
 */
function escapeRegex(str: string): string {
  return str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

// Example usage (for Node.js/server-side, you might need to use a different HTML parser)
// For browser/client-side, the above functions work with DOMParser

