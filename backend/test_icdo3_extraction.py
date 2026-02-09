#!/usr/bin/env python3
"""
Test script for ICD-O-3 code extraction

This script tests the ICD-O-3 extraction functionality with sample histology and site texts.
Tests pattern extraction, LLM+CSV matching, and lookup table fallback.
"""

import sys
from pathlib import Path

# Add backend to path
backend_dir = Path(__file__).parent
sys.path.insert(0, str(backend_dir))

from lib.icdo3_extractor import extract_icdo3_from_text, is_histology_or_site_prompt


def test_histology_extraction():
    """Test histology code extraction"""
    print("\n" + "="*60)
    print("Testing Histology Code Extraction")
    print("="*60)
    
    test_cases = [
        {
            "text": "Histological type: Mesothelioma, malignant",
            "prompt_type": "histological-tipo-int",
            "expected": "9050/3"  # Mesothelioma, malignant
        },
        {
            "text": "Histological type: Sarcoma, undifferentiated, pleomorphic, NOS",
            "prompt_type": "histological-tipo-int",
            "expected": "8805/3"  # Sarcoma, undifferentiated, NOS
        },
        {
            "text": "Histological type: Leiomyosarcoma NOS",
            "prompt_type": "histological-tipo-int",
            "expected": "8890/3"  # Leiomyosarcoma, NOS
        },
        {
            "text": "Histological type: Myxoid liposarcoma",
            "prompt_type": "histological-tipo-int",
            "expected": "8852/3"  # Myxoid liposarcoma
        },
        {
            "text": "The patient has undifferentiated sarcoma",
            "prompt_type": "histological-tipo-int",
            "expected": "8805/3"
        }
    ]
    
    for i, test_case in enumerate(test_cases, 1):
        print(f"\nTest {i}: {test_case['text']}")
        print(f"Prompt Type: {test_case['prompt_type']}")
        
        result = extract_icdo3_from_text(test_case['text'], test_case['prompt_type'])
        
        if result:
            print(f"✓ Extracted Code: {result.get('code')}")
            print(f"  Morphology: {result.get('morphology_code')}")
            print(f"  Histology: {result.get('histology_code')}")
            print(f"  Behavior: {result.get('behavior_code')}")
            print(f"  Description: {result.get('description', 'N/A')}")
            print(f"  Confidence: {result.get('confidence', 'N/A')}")
            
            if test_case['expected']:
                if result.get('code') == test_case['expected'] or \
                   result.get('morphology_code') == test_case['expected']:
                    print(f"  ✓ Matches expected: {test_case['expected']}")
                else:
                    print(f"  ⚠ Expected: {test_case['expected']}, Got: {result.get('code')}")
        else:
            print("✗ No code extracted")
            if test_case['expected']:
                print(f"  ⚠ Expected: {test_case['expected']}")


def test_site_extraction():
    """Test site/topography code extraction"""
    print("\n" + "="*60)
    print("Testing Site/Topography Code Extraction")
    print("="*60)
    
    test_cases = [
        {
            "text": "Tumor site: Brain stem",
            "prompt_type": "tumorsite-int",
            "expected": "C71.7"  # Brain stem
        },
        {
            "text": "Tumor site: Thoracic Wall",
            "prompt_type": "tumorsite-int",
            "expected": "C76.1"  # Thorax, NOS (or similar)
        },
        {
            "text": "Tumor site: Uterus",
            "prompt_type": "tumorsite-int",
            "expected": "C55.9"  # Uterus, NOS
        },
        {
            "text": "Tumor site: Bladder",
            "prompt_type": "tumorsite-int",
            "expected": "C67.9"  # Bladder, NOS
        },
        {
            "text": "The lesion is located in the brain",
            "prompt_type": "tumorsite-int",
            "expected": "C71.9"  # Brain, NOS
        }
    ]
    
    for i, test_case in enumerate(test_cases, 1):
        print(f"\nTest {i}: {test_case['text']}")
        print(f"Prompt Type: {test_case['prompt_type']}")
        
        result = extract_icdo3_from_text(test_case['text'], test_case['prompt_type'])
        
        if result:
            print(f"✓ Extracted Code: {result.get('code')}")
            print(f"  Topography: {result.get('topography_code')}")
            print(f"  Description: {result.get('description', 'N/A')}")
            print(f"  Confidence: {result.get('confidence', 'N/A')}")
            
            if test_case['expected']:
                if result.get('code') == test_case['expected'] or \
                   result.get('topography_code') == test_case['expected']:
                    print(f"  ✓ Matches expected: {test_case['expected']}")
                else:
                    print(f"  ⚠ Expected: {test_case['expected']}, Got: {result.get('code')}")
        else:
            print("✗ No code extracted")
            if test_case['expected']:
                print(f"  ⚠ Expected: {test_case['expected']}")


def test_existing_codes():
    """Test extraction of codes already present in text"""
    print("\n" + "="*60)
    print("Testing Existing Code Extraction")
    print("="*60)
    
    test_cases = [
        {
            "text": "Histological type: Sarcoma (8805/3)",
            "prompt_type": "histological-tipo-int",
            "expected_code": "8805/3"
        },
        {
            "text": "Tumor site: Brain (C71.7)",
            "prompt_type": "tumorsite-int",
            "expected_code": "C71.7"
        },
        {
            "text": "Histological type: Leiomyosarcoma (8890/3-C55.9)",
            "prompt_type": "histological-tipo-int",
            "expected_morphology": "8890/3",
            "expected_topography": "C55.9"
        }
    ]
    
    for i, test_case in enumerate(test_cases, 1):
        print(f"\nTest {i}: {test_case['text']}")
        
        result = extract_icdo3_from_text(test_case['text'], test_case['prompt_type'])
        
        if result:
            print(f"✓ Extracted Code: {result.get('code')}")
            if 'expected_code' in test_case:
                if result.get('code') == test_case['expected_code']:
                    print(f"  ✓ Matches expected: {test_case['expected_code']}")
                else:
                    print(f"  ⚠ Expected: {test_case['expected_code']}, Got: {result.get('code')}")
            if 'expected_morphology' in test_case:
                if result.get('morphology_code') == test_case['expected_morphology']:
                    print(f"  ✓ Morphology matches: {test_case['expected_morphology']}")
            if 'expected_topography' in test_case:
                if result.get('topography_code') == test_case['expected_topography']:
                    print(f"  ✓ Topography matches: {test_case['expected_topography']}")
        else:
            print("✗ No code extracted")


if __name__ == "__main__":
    print("ICD-O-3 Code Extraction Test")
    print("="*60)
    print("\nNote: This test uses pattern extraction and lookup tables.")
    print("For LLM+CSV extraction, use test_icdo3_llm_extraction.py\n")
    
    # Test existing code extraction (always works)
    test_existing_codes()
    
    # Test histology extraction (uses pattern matching)
    test_histology_extraction()
    
    # Test site extraction (uses pattern matching)
    test_site_extraction()
    
    print("\n" + "="*60)
    print("Test Complete")
    print("="*60)

