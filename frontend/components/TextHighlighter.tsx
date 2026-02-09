'use client'

import { useMemo } from 'react'
import type { EvidenceSpan } from '@/lib/api'
import { getColorForPromptType } from '@/lib/colors'

interface TextHighlighterProps {
  text: string
  spans: EvidenceSpan[]
  selectedPromptType?: string
  onSpanClick?: (span: EvidenceSpan) => void
}

interface SpanWithLayers {
  span: EvidenceSpan
  layer: number  // Which layer this span is on (for overlapping)
}

export default function TextHighlighter({
  text,
  spans,
  selectedPromptType,
  onSpanClick,
}: TextHighlighterProps) {
  // Sort spans by start position, then by end position
  const sortedSpans = useMemo(() => {
    return [...spans].sort((a, b) => {
      if (a.start !== b.start) return a.start - b.start
      return a.end - b.end
    })
  }, [spans])

  // Calculate layers for overlapping spans
  const spansWithLayers = useMemo(() => {
    const result: SpanWithLayers[] = []
    const layers: number[] = []  // Track end positions of each layer

    for (const span of sortedSpans) {
      // Find the first layer that doesn't overlap with this span
      let layer = 0
      while (layer < layers.length && layers[layer] > span.start) {
        layer++
      }
      
      // Update layer end position
      if (layer >= layers.length) {
        layers.push(span.end)
      } else {
        layers[layer] = Math.max(layers[layer], span.end)
      }
      
      result.push({ span, layer })
    }
    
    return result
  }, [sortedSpans])

  // Build highlighted text with React elements, handling overlaps
  const highlightedText = useMemo(() => {
    if (spansWithLayers.length === 0) {
      return <span>{text}</span>
    }

    // Create an array to track which spans cover each character
    const charSpans: SpanWithLayers[][] = Array(text.length).fill(null).map(() => [])
    
    spansWithLayers.forEach((spanWithLayer) => {
      for (let i = spanWithLayer.span.start; i < spanWithLayer.span.end; i++) {
        if (i < text.length) {
          charSpans[i].push(spanWithLayer)
        }
      }
    })

    const elements: React.ReactNode[] = []
    let currentSpans: SpanWithLayers[] = []
    let segmentStart = 0

    for (let i = 0; i <= text.length; i++) {
      const spansAtPos = i < text.length ? charSpans[i] : []
      
      // Check if the set of spans changed
      const spansChanged = 
        spansAtPos.length !== currentSpans.length ||
        spansAtPos.some((s, idx) => s.span !== currentSpans[idx]?.span)

      // Also render if we've reached the end of the text and there's remaining content
      const isEndOfText = i === text.length
      const hasRemainingContent = segmentStart < text.length

      if ((spansChanged && i > segmentStart) || (isEndOfText && hasRemainingContent)) {
        // Render the segment
        const segmentText = text.substring(segmentStart, i)
        
        if (segmentText.length > 0) {
          if (currentSpans.length === 0) {
            // No highlighting
            elements.push(<span key={`text-${segmentStart}`}>{segmentText}</span>)
          } else if (currentSpans.length === 1) {
            // Single span - simple highlighting
            const spanWithLayer = currentSpans[0]
            const color = getColorForPromptType(spanWithLayer.span.prompt_type)
            const isSelected = selectedPromptType === spanWithLayer.span.prompt_type
            const opacity = isSelected ? 0.7 : 0.4
            
            elements.push(
              <mark
                key={`span-${segmentStart}`}
                style={{
                  backgroundColor: color,
                  opacity,
                  padding: '2px 0',
                  cursor: onSpanClick ? 'pointer' : 'default',
                  borderRadius: '2px',
                }}
                onClick={() => onSpanClick?.(spanWithLayer.span)}
                title={`${spanWithLayer.span.prompt_type}: ${spanWithLayer.span.text.substring(0, 50)}...`}
              >
                {segmentText}
              </mark>
            )
          } else {
            // Multiple overlapping spans - use alternating colors character by character
            const segmentChars = segmentText.split('')
            segmentChars.forEach((char, charIdx) => {
              const pos = segmentStart + charIdx
              const spansAtChar = charSpans[pos]
              // Use the span with the lowest layer (first one) for this character
              const primarySpan = spansAtChar.sort((a, b) => a.layer - b.layer)[0]
              const color = getColorForPromptType(primarySpan.span.prompt_type)
              const isSelected = selectedPromptType === primarySpan.span.prompt_type
              const opacity = isSelected ? 0.7 : 0.4
              
              elements.push(
                <mark
                  key={`span-${pos}`}
                  style={{
                    backgroundColor: color,
                    opacity,
                    padding: '2px 0',
                    cursor: onSpanClick ? 'pointer' : 'default',
                    borderRadius: '2px',
                  }}
                  onClick={() => onSpanClick?.(primarySpan.span)}
                  title={`${primarySpan.span.prompt_type}: ${primarySpan.span.text.substring(0, 50)}...`}
                >
                  {char}
                </mark>
              )
            })
          }
        }
        
        segmentStart = i
        currentSpans = spansAtPos
      }
    }

    return <>{elements}</>
  }, [text, spansWithLayers, selectedPromptType, onSpanClick])

  return (
    <div className="prose max-w-none">
      <div className="whitespace-pre-wrap text-sm leading-relaxed">
        {highlightedText}
      </div>
    </div>
  )
}

