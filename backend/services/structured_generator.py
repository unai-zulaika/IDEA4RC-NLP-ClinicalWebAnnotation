"""
Structured generation service using Outlines and Pydantic
"""
import json
import re
from typing import Optional, Dict, Any, Tuple
from pathlib import Path

# Pre-compiled regex patterns for JSON extraction
_RE_MARKDOWN_JSON = re.compile(r'```(?:json)?\s*\n?(.*?)\n?```', re.DOTALL)
_RE_JSON_OBJ = re.compile(r'\{.*?"evidence".*?"reasoning".*?"final_output".*?\}', re.DOTALL)
_RE_JSON_ARRAY = re.compile(r'\[\s*\{.*?"evidence".*?"reasoning".*?"final_output".*?\}.*?\]', re.DOTALL)
_RE_JSON_OBJ_SINGLE = re.compile(r'\{[^{}]*"evidence"[^{}]*"reasoning"[^{}]*"final_output"[^{}]*\}', re.DOTALL)
_RE_EVIDENCE = re.compile(r'Evidence:\s*(.+?)(?:\.|$|Reasoning:)', re.IGNORECASE | re.DOTALL)
_RE_EVIDENCE_QUOTED = re.compile(r'"([^"]+)"')
_RE_REASONING = re.compile(r'Reasoning:\s*(.+?)(?:\.|$|Final)', re.IGNORECASE | re.DOTALL)
_RE_REASONING_INF = re.compile(r'Inference:\s*(.+?)(?:\.|$)', re.IGNORECASE | re.DOTALL)
_RE_ANNOTATION = re.compile(r'Annotation:\s*(.+?)(?:\.|$)', re.IGNORECASE | re.DOTALL)
_RE_FINAL_OUTPUT = re.compile(r'Final output:\s*(.+?)(?:\.|$)', re.IGNORECASE | re.DOTALL)
_RE_DATE_SLASH = re.compile(r'\d{2}/\d{2}/\d{4}')
_RE_DATE_ISO = re.compile(r'\d{4}-\d{2}-\d{2}')
_RE_DATE_FLEX = re.compile(r'\d{1,2}/\d{1,2}/\d{4}')

try:
    import outlines
    # Version 0.1.11 has a different API that's incompatible with our code
    # Disabling for now and using fallback parsing
    OUTLINES_AVAILABLE = False
    print("[INFO] Outlines v0.1.11 detected but using fallback parsing (API incompatible)")
except ImportError as e:
    OUTLINES_AVAILABLE = False
    print(f"[WARN] Outlines not available: {e}")
except Exception as e:
    OUTLINES_AVAILABLE = False
    print(f"[ERROR] Failed to import Outlines: {e}")
    import traceback
    traceback.print_exc()

from models.annotation_models import StructuredAnnotation


def generate_structured_annotation(
    prompt: str,
    vllm_endpoint: str,
    model_name: str,
    csv_date: Optional[str] = None,
    max_new_tokens: int = 1024,
    temperature: float = 0.0  # Deterministic output
) -> Tuple[StructuredAnnotation, Optional[str]]:
    """
    Generate structured annotation using Outlines with vLLM.
    
    Args:
        prompt: The prompt to send to the LLM
        vllm_endpoint: vLLM server endpoint
        model_name: Model name
        csv_date: Optional CSV date to include in date info
        max_new_tokens: Maximum tokens to generate
        temperature: Sampling temperature
    
    Returns:
        Tuple of (StructuredAnnotation instance, raw_response string or None)
    """
    if not OUTLINES_AVAILABLE:
        raise ImportError("Outlines is not available. Install with: pip install outlines>=0.0.40")
    
    try:
        # Clean endpoint
        base_endpoint = vllm_endpoint.rstrip('/')
        if base_endpoint.endswith('/v1'):
            base_endpoint = base_endpoint[:-3]
        
        # Use Outlines with OpenAI-compatible API
        # Create OpenAI client pointing to vLLM
        try:
            from openai import OpenAI
            client = OpenAI(
                base_url=f"{base_endpoint}/v1",
                api_key="not-needed"  # vLLM doesn't require key
            )
            
            # Create Outlines model from OpenAI client
            # OpenAI constructor: (client, config, system_prompt=None)
            # config can be None or an empty dict
            model = outlines.models.OpenAI(client, None)
            
            # Generate structured JSON using Outlines
            # Outlines will ensure output matches StructuredAnnotation schema
            generator = outlines.generate.json(model, StructuredAnnotation)
            result = generator(prompt, max_tokens=max_new_tokens, temperature=temperature)
            
            # Store raw response - try to get the actual API response
            # Outlines might not expose the raw response, so we'll serialize the result
            raw_response_str = None
            if isinstance(result, StructuredAnnotation):
                try:
                    raw_response_str = json.dumps(result.dict(), indent=2, ensure_ascii=False)
                except:
                    raw_response_str = str(result)
            elif isinstance(result, dict):
                raw_response_str = json.dumps(result, indent=2, ensure_ascii=False)
            else:
                raw_response_str = str(result)
        except Exception as e1:
            # Fallback: try creating client and model again with different approach
            print(f"[WARN] OpenAI client approach failed: {e1}, trying alternative client creation")
            try:
                # Create OpenAI client with different parameters
                from openai import OpenAI
                client = OpenAI(
                    base_url=f"{base_endpoint}/v1",
                    api_key="not-needed"
                )
                # Create Outlines model
                model = outlines.models.OpenAI(client, None)
                # Generate JSON
                generator = outlines.generate.json(model, StructuredAnnotation)
                result = generator(prompt, max_tokens=max_new_tokens, temperature=temperature)
                
                # Set raw_response_str for this path too
                if isinstance(result, StructuredAnnotation):
                    try:
                        raw_response_str = json.dumps(result.dict(), indent=2, ensure_ascii=False)
                    except:
                        raw_response_str = str(result)
                elif isinstance(result, dict):
                    raw_response_str = json.dumps(result, indent=2, ensure_ascii=False)
                else:
                    raw_response_str = str(result)
            except Exception as e2:
                print(f"[ERROR] Direct Outlines approach also failed: {e2}")
                import traceback
                traceback.print_exc()
                raise
        
        # Parse result - handle markdown code blocks
        if isinstance(result, StructuredAnnotation):
            ann = result
        elif isinstance(result, dict):
            ann = StructuredAnnotation(**result)
        elif isinstance(result, str):
            # Try to extract JSON from markdown code blocks first
            json_str = result
            # Look for ```json ... ``` or ``` ... ```
            markdown_match = _RE_MARKDOWN_JSON.search(result)
            if markdown_match:
                json_str = markdown_match.group(1).strip()
            # Also try to find JSON object directly
            json_obj_match = _RE_JSON_OBJ.search(json_str)
            if json_obj_match:
                json_str = json_obj_match.group(0)
            
            try:
                parsed_json = json.loads(json_str)
                # Handle case where LLM returns an array instead of a single object
                if isinstance(parsed_json, list):
                    if len(parsed_json) > 0:
                        # Use the first item in the array
                        parsed_json = parsed_json[0]
                        print(f"[INFO] LLM returned array with {len(parsed_json)} items, using first item")
                    else:
                        raise ValueError("LLM returned empty array")
                ann = StructuredAnnotation(**parsed_json)
            except json.JSONDecodeError as e:
                print(f"[WARN] Failed to parse JSON string: {e}")
                print(f"[DEBUG] JSON string was: {json_str[:500]}")
                raise
            except (TypeError, ValueError) as e:
                print(f"[WARN] Failed to create StructuredAnnotation: {e}")
                if 'parsed_json' in locals():
                    print(f"[DEBUG] Parsed JSON was: {parsed_json}")
                raise
        else:
            raise ValueError(f"Unexpected result type: {type(result)}")
        
        # Update date info if CSV date is provided
        if csv_date and ann.date and ann.date.source == "derived_from_csv":
            ann.date.csv_date = csv_date
        
        # Fallback: If date is None but csv_date is available, use csv_date
        if not ann.date and csv_date:
            from models.annotation_models import AnnotationDateInfo
            ann.date = AnnotationDateInfo(
                date_value=csv_date,
                source="derived_from_csv",
                csv_date=csv_date
            )
        
        # Try to get raw response
        # Use the raw_response_str we set above if available
        final_raw_response = None
        if 'raw_response_str' in locals() and raw_response_str:
            final_raw_response = raw_response_str
        elif isinstance(result, str):
            final_raw_response = result
        elif isinstance(ann, StructuredAnnotation):
            # Convert StructuredAnnotation to JSON string
            try:
                final_raw_response = json.dumps(ann.dict(), indent=2, ensure_ascii=False)
            except:
                final_raw_response = str(ann)
        elif hasattr(result, '__str__'):
            final_raw_response = str(result)
        else:
            final_raw_response = None
        
        return ann, final_raw_response
        
    except Exception as e:
        print(f"[ERROR] Structured generation with Outlines failed: {e}")
        import traceback
        traceback.print_exc()
        # Fallback: return a basic structure
        return (
            StructuredAnnotation(
                evidence="",
                reasoning=f"Generation failed: {str(e)}",
                final_output="",
                is_negated=False,
                date=None
            ),
            None
        )


def generate_structured_annotation_fallback(
    prompt: str,
    raw_output: str,
    csv_date: Optional[str] = None
) -> StructuredAnnotation:
    """
    Fallback method to parse raw LLM output into structured format.
    Used when Outlines is not available or fails.
    
    Args:
        prompt: The prompt (for context)
        raw_output: Raw LLM output
        csv_date: Optional CSV date
    
    Returns:
        StructuredAnnotation instance
    """
    # Try to extract JSON from output
    json_match = None
    json_str = None

    # First, try to extract JSON from markdown code blocks
    markdown_match = _RE_MARKDOWN_JSON.search(raw_output)
    if markdown_match:
        json_str = markdown_match.group(1).strip()
        try:
            json_match = json.loads(json_str)
        except json.JSONDecodeError as e:
            print(f"[DEBUG] Failed to parse JSON from markdown block: {e}")
            print(f"[DEBUG] JSON string was: {json_str[:200]}")
            json_str = None

    # If markdown extraction didn't work, try direct JSON patterns
    if not json_match:
        # Try to match JSON array first (in case LLM returns array)
        array_match = _RE_JSON_ARRAY.search(raw_output)
        if array_match:
            try:
                json_match = json.loads(array_match.group(0))
            except json.JSONDecodeError as e:
                print(f"[DEBUG] Failed to parse JSON array from pattern: {e}")

        # If no array found, try single object patterns
        if not json_match:
            for compiled_re in [_RE_JSON_OBJ, _RE_JSON_OBJ_SINGLE]:
                match = compiled_re.search(raw_output)
                if match:
                    try:
                        json_match = json.loads(match.group(0))
                        break
                    except json.JSONDecodeError as e:
                        print(f"[DEBUG] Failed to parse JSON from pattern: {e}")
                        continue
    
    # If JSON found, use it
    if json_match:
        # Handle case where LLM returns an array instead of a single object
        if isinstance(json_match, list):
            if len(json_match) > 0:
                # Use the first item in the array
                json_match = json_match[0]
                print(f"[INFO] LLM returned array with {len(json_match)} items, using first item")
            else:
                print(f"[WARN] LLM returned empty array")
                json_match = None
        
        if json_match and isinstance(json_match, dict):
            # Handle date info
            if csv_date and json_match.get("date") and isinstance(json_match["date"], dict) and json_match["date"].get("source") == "derived_from_csv":
                json_match["date"]["csv_date"] = csv_date
            try:
                return StructuredAnnotation(**json_match)
            except Exception as e:
                print(f"[WARN] Failed to parse JSON into StructuredAnnotation: {e}")
                print(f"[DEBUG] JSON object was: {json_match}")
    
    # Fallback: create basic structure from raw output
    print(f"[DEBUG] Fallback parsing, raw_output length: {len(raw_output)}")
    print(f"[DEBUG] Fallback parsing, raw_output preview: {raw_output[:300]}")
    
    # Try to extract evidence (look for quoted text or "Evidence:" pattern)
    evidence = ""
    for compiled_re in [_RE_EVIDENCE, _RE_EVIDENCE_QUOTED]:
        match = compiled_re.search(raw_output)
        if match:
            evidence = match.group(1).strip()
            break

    # Extract reasoning
    reasoning = ""
    for compiled_re in [_RE_REASONING, _RE_REASONING_INF]:
        match = compiled_re.search(raw_output)
        if match:
            reasoning = match.group(1).strip()
            break

    # Extract final output (look for "Annotation:" or template format)
    final_output = raw_output
    for compiled_re in [_RE_ANNOTATION, _RE_FINAL_OUTPUT]:
        match = compiled_re.search(raw_output)
        if match:
            final_output = match.group(1).strip()
            break

    # Check for negation
    is_negated = any(neg_word in raw_output.lower() for neg_word in [
        'no ', 'not ', 'absence of', 'ruled out', 'negative', 'none',
        'no evidence', 'without', 'excluded'
    ])

    # Try to extract date
    date_info = None
    for compiled_re in [_RE_DATE_SLASH, _RE_DATE_ISO, _RE_DATE_FLEX]:
        match = compiled_re.search(raw_output)
        if match:
            date_info = {
                "date_value": match.group(0),
                "source": "extracted_from_text",
                "csv_date": None
            }
            break
    
    # If no date in text but CSV date provided, use it
    if not date_info and csv_date:
        date_info = {
            "date_value": csv_date,
            "source": "derived_from_csv",
            "csv_date": csv_date
        }
    
    return StructuredAnnotation(
        evidence=evidence or "Not extracted",
        reasoning=reasoning or "Not extracted",
        final_output=final_output.strip(),
        is_negated=is_negated,
        date=date_info
    )
