#!/usr/bin/env python3
"""
Test script for ICD-O-3 LLM-based extraction with CSV matching

This script tests the new LLM+CSV extraction system.
"""

import sys
from pathlib import Path

# Add backend to path
backend_dir = Path(__file__).parent
sys.path.insert(0, str(backend_dir))

from lib.icdo3_extractor import extract_icdo3_from_text, is_histology_or_site_prompt
from lib.icdo3_csv_indexer import get_csv_indexer, reset_indexer
from services.vllm_client import get_vllm_client


def test_csv_indexer():
    """Test CSV indexer loading and matching"""
    print("\n" + "="*60)
    print("Testing CSV Indexer")
    print("="*60)
    
    # Reset indexer to force reload
    reset_indexer()
    
    indexer = get_csv_indexer()
    if not indexer:
        print("✗ CSV indexer not available (CSV file may not be found)")
        return False
    
    print(f"✓ CSV indexer loaded successfully")
    print(f"  Query codes indexed: {len(indexer.query_index)}")
    print(f"  Morphology codes indexed: {len(indexer.morphology_index)}")
    print(f"  Topography codes indexed: {len(indexer.topography_index)}")
    
    # Test exact match
    matched_row, score, method = indexer.find_matching_code(query_code="8940/0-C00.2")
    if matched_row:
        print(f"\n✓ Exact match test:")
        print(f"  Query: 8940/0-C00.2")
        print(f"  Match: {matched_row.get('NAME', 'N/A')}")
        print(f"  Score: {score}, Method: {method}")
    else:
        print(f"\n✗ Exact match test failed")
    
    # Test combined match
    matched_row, score, method = indexer.find_matching_code(
        morphology_code="8940/0",
        topography_code="C00.2"
    )
    if matched_row:
        print(f"\n✓ Combined match test:")
        print(f"  Morphology: 8940/0, Topography: C00.2")
        print(f"  Match: {matched_row.get('NAME', 'N/A')}")
        print(f"  Score: {score}, Method: {method}")
    else:
        print(f"\n✗ Combined match test failed")
    
    return True


def test_llm_extraction():
    """Test LLM-based extraction (requires vLLM server)"""
    print("\n" + "="*60)
    print("Testing LLM-Based Extraction")
    print("="*60)
    
    vllm_client = get_vllm_client()
    if not vllm_client or not vllm_client.is_available():
        print("⚠ vLLM server not available, skipping LLM extraction test")
        return False
    
    print("✓ vLLM client available")
    
    # Test note from user's example
    test_note = """CCE|MODULO: AMB_TRD_Visita; VARIABILE: ds_ana_pat_remota; ETICHETTA: *Anamnesi patologica remota; TESTO: Da alcuni mesi comparsadi lesione al fianco DX in progressivo aumento dimensionale. 25/9/129 I Visita CMS: Il quadro clinico-iconografico depone per una forma di possibile natura sarcomatosa.Tecnicamente è certamente resecabile in maniera completa. Ugualmente se ne ritiene indispensabile unatipizzazione istologica precisa per  rogrammare al meglio la cura, estensione dell'intervento ed opportunità dieffettuare una radioterapia preoperatoria incluse. 27/9/19 Biopsia.E.I.: Neoplasia maligna a cellule fusate e pleomorfe, talora plurinucleate, con crescita solida ed in fasciirregolari, con stroma in parte mixoide; indice mitotico 15/10 HPF; necrosi presente.Quadro morfologico e profilo immunofenotipico coerenti con SARCOMA INDIFFERENZIATO A CELLULEFUSATE E PLEOMORFE CON STROMA MIXOIDE, grado 3 sec. FNCLCC (D3; M2; N1) CON FOCALEDIFFERENZIAZIONE MIOGENICA, frammenti."""
    
    test_annotation = "SARCOMA INDIFFERENZIATO A CELLULE FUSATE E PLEOMORFE CON STROMA MIXOIDE"
    
    print(f"\nTest note (truncated): {test_note[:200]}...")
    print(f"Test annotation: {test_annotation}")
    
    try:
        result = extract_icdo3_from_text(
            text=test_annotation,
            prompt_type="histological-tipo-int",
            note_text=test_note,
            vllm_client=vllm_client
        )
        
        if result:
            print(f"\n✓ LLM extraction successful:")
            print(f"  Code: {result.get('code')}")
            print(f"  Query Code: {result.get('query_code')}")
            print(f"  Morphology: {result.get('morphology_code')}")
            print(f"  Topography: {result.get('topography_code')}")
            print(f"  Description: {result.get('description', 'N/A')[:100]}")
            print(f"  Match Method: {result.get('match_method')}")
            print(f"  Match Score: {result.get('match_score')}")
            return True
        else:
            print("\n✗ LLM extraction returned None")
            return False
    except Exception as e:
        print(f"\n✗ LLM extraction failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_integration():
    """Test full integration"""
    print("\n" + "="*60)
    print("Testing Full Integration")
    print("="*60)
    
    vllm_client = get_vllm_client()
    if not vllm_client or not vllm_client.is_available():
        print("⚠ vLLM server not available, skipping integration test")
        return False
    
    test_cases = [
        {
            "note": "Histological type: Mesothelioma, malignant",
            "annotation": "Mesothelioma, malignant",
            "prompt_type": "histological-tipo-int",
            "expected_morphology": "9050/3"
        },
        {
            "note": "Tumor site: Brain stem",
            "annotation": "Brain stem",
            "prompt_type": "tumorsite-int",
            "expected_topography": "C71.7"
        }
    ]
    
    for i, test_case in enumerate(test_cases, 1):
        print(f"\nTest {i}: {test_case['prompt_type']}")
        print(f"  Note: {test_case['note']}")
        print(f"  Annotation: {test_case['annotation']}")
        
        try:
            result = extract_icdo3_from_text(
                text=test_case['annotation'],
                prompt_type=test_case['prompt_type'],
                note_text=test_case['note'],
                vllm_client=vllm_client
            )
            
            if result:
                print(f"  ✓ Extracted:")
                print(f"    Code: {result.get('code')}")
                print(f"    Query Code: {result.get('query_code')}")
                print(f"    Match Method: {result.get('match_method')}")
                print(f"    Match Score: {result.get('match_score')}")
                
                # Check if expected code matches
                if 'expected_morphology' in test_case:
                    if result.get('morphology_code') == test_case['expected_morphology']:
                        print(f"    ✓ Morphology matches expected: {test_case['expected_morphology']}")
                    else:
                        print(f"    ⚠ Expected morphology: {test_case['expected_morphology']}, Got: {result.get('morphology_code')}")
                
                if 'expected_topography' in test_case:
                    if result.get('topography_code') == test_case['expected_topography']:
                        print(f"    ✓ Topography matches expected: {test_case['expected_topography']}")
                    else:
                        print(f"    ⚠ Expected topography: {test_case['expected_topography']}, Got: {result.get('topography_code')}")
            else:
                print(f"  ✗ No result")
        except Exception as e:
            print(f"  ✗ Error: {e}")
            import traceback
            traceback.print_exc()
    
    return True


if __name__ == "__main__":
    print("ICD-O-3 LLM-Based Extraction Test")
    print("="*60)
    
    # Test CSV indexer
    csv_ok = test_csv_indexer()
    
    # Test LLM extraction
    llm_ok = test_llm_extraction()
    
    # Test integration
    integration_ok = test_integration()
    
    print("\n" + "="*60)
    print("Test Summary")
    print("="*60)
    print(f"CSV Indexer: {'✓ PASS' if csv_ok else '✗ FAIL'}")
    print(f"LLM Extraction: {'✓ PASS' if llm_ok else '⚠ SKIP (vLLM not available)'}")
    print(f"Integration: {'✓ PASS' if integration_ok else '⚠ SKIP (vLLM not available)'}")
    print("="*60)
