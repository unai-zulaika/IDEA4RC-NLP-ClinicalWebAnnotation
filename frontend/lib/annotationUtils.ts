/**
 * Utility functions for annotation processing
 */

/**
 * Extract expected annotation for a specific prompt type from CSV annotations string
 * The annotations string format is typically: "prompt_type_1: annotation1 | prompt_type_2: annotation2"
 * or similar formats
 */
export function extractExpectedAnnotation(
  annotationsString: string | null | undefined,
  promptType: string
): string | undefined {
  if (!annotationsString) return undefined

  // Try different formats:
  // 1. "prompt_type: annotation" format
  const pattern1 = new RegExp(`${promptType}\\s*[:]\\s*([^|\\n]+)`, 'i')
  const match1 = annotationsString.match(pattern1)
  if (match1) {
    return match1[1].trim()
  }

  // 2. Check if the string contains the prompt type (simple contains check)
  if (annotationsString.toLowerCase().includes(promptType.toLowerCase())) {
    // Try to extract the annotation after the prompt type
    const parts = annotationsString.split(/[|,\n]/)
    for (const part of parts) {
      if (part.toLowerCase().includes(promptType.toLowerCase())) {
        const colonIndex = part.indexOf(':')
        if (colonIndex !== -1) {
          return part.substring(colonIndex + 1).trim()
        }
        return part.trim()
      }
    }
  }

  return undefined
}

/**
 * Detect if the annotation contains placeholders indicating the template cannot be filled
 * Common placeholders: [select intent], [provide date], [put date], [select result], [select type], etc.
 */
export function isTemplateIncomplete(annotationText: string | null | undefined): boolean {
  if (!annotationText) return true

  // Common placeholder patterns
  const placeholderPatterns = [
    /\[select\s+\w+\]/i,           // [select intent], [select result], [select type]
    /\[provide\s+\w+\]/i,          // [provide date]
    /\[put\s+\w+\]/i,              // [put date], [put total dose]
    /\[please\s+select\s+\w+\]/i,  // [please select where]
    /\[fill\s+\w+\]/i,             // [fill in]
    /\[choose\s+\w+\]/i,          // [choose option]
    /\[enter\s+\w+\]/i,            // [enter value]
    /\[specify\s+\w+\]/i,          // [specify date]
    /\[unknown\]/i,                // [unknown]
    /\[not\s+specified\]/i,        // [not specified]
    /\[n\/a\]/i,                   // [n/a]
    /\[none\]/i,                   // [none] (when it's a placeholder, not actual "none")
  ]

  for (const pattern of placeholderPatterns) {
    if (pattern.test(annotationText)) {
      return true
    }
  }

  return false
}

/**
 * Get all placeholders found in the annotation text
 */
export function getPlaceholders(annotationText: string | null | undefined): string[] {
  if (!annotationText) return []

  const placeholderPatterns = [
    /\[select\s+\w+\]/gi,
    /\[provide\s+\w+\]/gi,
    /\[put\s+\w+\]/gi,
    /\[please\s+select\s+\w+\]/gi,
    /\[fill\s+\w+\]/gi,
    /\[choose\s+\w+\]/gi,
    /\[enter\s+\w+\]/gi,
    /\[specify\s+\w+\]/gi,
    /\[unknown\]/gi,
    /\[not\s+specified\]/gi,
    /\[n\/a\]/gi,
  ]

  const placeholders: string[] = []
  for (const pattern of placeholderPatterns) {
    const matches = annotationText.match(pattern)
    if (matches) {
      placeholders.push(...matches)
    }
  }

  return [...new Set(placeholders)] // Remove duplicates
}

