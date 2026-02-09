#!/usr/bin/env python3
"""Test Full Ingestion Pipeline

Tests the complete pipeline:
1. Load unstructured texts from CSV
2. Load existing structured data (optional)
3. Run LLM annotation
4. Process with regex to extract structured entities
5. Save outputs
6. Analyze results
"""

import pandas as pd
import sys
import argparse
import json
from pathlib import Path
from typing import Dict, List

# Fix imports: add api/ to path
script_dir = Path(__file__).resolve().parent
api_dir = script_dir.parent
if str(api_dir) not in sys.path:
    sys.path.insert(0, str(api_dir))

from nlp.process_texts import process_texts


def create_empty_structured_data() -> pd.DataFrame:
    """Create an empty structured data DataFrame with required columns."""
    return pd.DataFrame(columns=[
        "patient_id", "original_source", "core_variable",
        "date_ref", "value", "record_id", "note_id", "prompt_type", "types"
    ])


def load_structured_data(csv_path: Path) -> pd.DataFrame:
    """
    Load structured data from CSV.
    
    Args:
        csv_path: Path to structured data CSV
    
    Returns:
        DataFrame with structured data
    """
    if not csv_path.exists():
        raise FileNotFoundError(f"Structured data file not found: {csv_path}")
    
    # Detect delimiter
    with open(csv_path, 'r', encoding='utf-8') as f:
        first_line = f.readline()
        delimiter = ';' if first_line.count(';') > first_line.count(',') else ','
    
    df = pd.read_csv(csv_path, delimiter=delimiter, encoding='utf-8', quoting=1)
    
    # Normalize column names
    if 'patient_id' not in df.columns and 'p_id' in df.columns:
        df['patient_id'] = df['p_id']
    
    return df


def load_report_type_prompt_mapping(mapping_json_path: str | Path | None) -> Dict[str, List[str]]:
    """
    Load report type to prompt type mapping from JSON file.
    
    Args:
        mapping_json_path: Path to report_type_prompt_mapping.json, or None to disable filtering
    
    Returns:
        Dictionary mapping report_type -> list of prompt types (empty dict if not provided or not found)
    """
    # Only load if explicitly provided - don't use default
    if mapping_json_path is None:
        return {}
    
    mapping_json_path = Path(mapping_json_path)
    
    if not mapping_json_path.exists():
        print(f"[WARN] Report type prompt mapping file not found: {mapping_json_path}")
        print(f"[WARN] Will run all prompts for all report types")
        return {}
    
    print(f"[INFO] Loading report type prompt mapping from: {mapping_json_path}")
    
    with open(mapping_json_path, 'r', encoding='utf-8') as f:
        mapping = json.load(f)
    
    print(f"[INFO] Loaded mapping for {len(mapping)} report types")
    return mapping


def load_unstructured_texts(csv_path: Path) -> pd.DataFrame:
    """
    Load unstructured texts from CSV.
    
    Args:
        csv_path: Path to texts CSV
    
    Returns:
        DataFrame with texts
    """
    if not csv_path.exists():
        raise FileNotFoundError(f"Texts file not found: {csv_path}")
    
    # Detect delimiter
    with open(csv_path, 'r', encoding='utf-8') as f:
        first_line = f.readline()
        delimiter = ';' if first_line.count(';') > first_line.count(',') else ','
    
    df = pd.read_csv(csv_path, delimiter=delimiter, encoding='utf-8', quoting=1)
    
    # Verify required columns
    required_cols = ['text', 'date', 'p_id', 'note_id', 'report_type']
    missing_cols = [col for col in required_cols if col not in df.columns]
    if missing_cols:
        raise ValueError(f"Missing required columns in texts CSV: {missing_cols}")
    
    return df


def main():
    parser = argparse.ArgumentParser(
        description="Test full ingestion pipeline with unstructured texts and optional structured data"
    )
    parser.add_argument(
        "--input-texts",
        type=str,
        default=None,
        help="Path to input unstructured texts CSV (default: first_patient_notes.csv in script directory)"
    )
    parser.add_argument(
        "--structured-data",
        type=str,
        default=None,
        help="Path to existing structured data CSV to append to (optional, creates empty if not provided)"
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Output directory for results (default: pipeline_test_results in script directory)"
    )
    parser.add_argument(
        "--model-path",
        type=str,
        default=None,
        help="Path to LLM model file (default: uses default from process_texts)"
    )
    parser.add_argument(
        "--prompts-json",
        type=str,
        default=None,
        help="Path to prompts.json (default: FBK_scripts/prompts.json in script directory)"
    )
    parser.add_argument(
        "--num-notes",
        type=int,
        default=None,
        help="Number of notes to process (default: all notes, or 3 if --small-test)"
    )
    parser.add_argument(
        "--small-test",
        action="store_true",
        help="Use small test subset (first 3 notes) - overrides --num-notes"
    )
    parser.add_argument(
        "--skip-analysis",
        action="store_true",
        help="Skip running analyze_pipeline_results.py"
    )
    parser.add_argument(
        "--report-type-mapping",
        type=str,
        default=None,
        help="Path to report_type_prompt_mapping.json. If provided, only runs prompts relevant to each note's report_type."
    )
    
    args = parser.parse_args()
    
    # Set default paths
    if args.input_texts is None:
        input_texts_path = script_dir / "first_patient_notes.csv"
    else:
        input_texts_path = Path(args.input_texts).resolve()
    
    if args.output_dir is None:
        output_dir = script_dir / "pipeline_test_results"
    else:
        output_dir = Path(args.output_dir).resolve()
    
    output_dir.mkdir(parents=True, exist_ok=True)
    
    print("=" * 80)
    print("Full Ingestion Pipeline Test")
    print("=" * 80)
    
    # Step 1: Load unstructured texts
    print("\n[STEP 1] Loading unstructured texts...")
    try:
        texts_df = load_unstructured_texts(input_texts_path)
        print(f"  Loaded {len(texts_df)} notes from {input_texts_path}")
    except Exception as e:
        print(f"  [ERROR] Failed to load texts: {e}")
        sys.exit(1)
    
    # Apply subset if requested
    if args.small_test:
        print("\n[STEP 2] Using small test subset (first 3 notes)...")
        texts_df = texts_df.head(3)
    elif args.num_notes:
        print(f"\n[STEP 2] Using subset (first {args.num_notes} notes)...")
        texts_df = texts_df.head(args.num_notes)
    else:
        print("\n[STEP 2] Processing all notes...")
    
    print(f"  Processing {len(texts_df)} notes")
    
    # Step 3: Load or create structured data
    print("\n[STEP 3] Loading structured data...")
    if args.structured_data:
        structured_data_path = Path(args.structured_data).resolve()
        try:
            excel_data = load_structured_data(structured_data_path)
            print(f"  Loaded {len(excel_data)} existing structured entities from {structured_data_path}")
        except Exception as e:
            print(f"  [ERROR] Failed to load structured data: {e}")
            sys.exit(1)
    else:
        excel_data = create_empty_structured_data()
        print("  Created empty structured data DataFrame (will be populated by pipeline)")
    
    # Step 4: Load report type mapping if provided
    report_type_mapping = None
    if args.report_type_mapping:
        print("\n[STEP 4a] Loading report type prompt mapping...")
        report_type_mapping = load_report_type_prompt_mapping(args.report_type_mapping)
        if len(report_type_mapping) > 0:
            print(f"  Report type filtering: ENABLED ({len(report_type_mapping)} report types mapped)")
        else:
            print("  Report type filtering: DISABLED (mapping file empty or not found)")
    
    # Step 5: Run the full pipeline
    print("\n[STEP 5] Running full ingestion pipeline...")
    print("  This will:")
    if report_type_mapping and len(report_type_mapping) > 0:
        print("    - Run LLM on each note for prompts relevant to its report_type")
    else:
        print("    - Run LLM on each note for all prompt types")
    print("    - Extract structured entities using regex")
    print("  This may take a while...")
    
    # Set default prompts path to FBK_scripts/prompts.json if not provided
    if args.prompts_json is None:
        prompts_json_path = script_dir / "FBK_scripts" / "prompts.json"
        if not prompts_json_path.exists():
            print(f"[WARN] Default prompts file not found: {prompts_json_path}")
            print(f"[WARN] Falling back to prompts.json in script directory")
            prompts_json_path = script_dir / "prompts.json"
    else:
        prompts_json_path = Path(args.prompts_json).resolve()
    
    try:
        structured_data, llm_results = process_texts(
            texts=texts_df,
            excel_data=excel_data,
            model_path=args.model_path,
            prompts_json_path=str(prompts_json_path),
            report_type_mapping=report_type_mapping
        )
        
        print(f"\n[STEP 5 COMPLETE]")
        print(f"  Generated {len(llm_results)} LLM annotations")
        print(f"  Extracted {len(structured_data)} structured entities")
        if args.structured_data:
            print(f"  Total entities (including existing): {len(structured_data)}")
        
    except Exception as e:
        print(f"\n[ERROR] Pipeline failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    
    # Step 6: Save outputs
    print("\n[STEP 6] Saving outputs...")
    
    structured_output_path = output_dir / "structured_output.csv"
    structured_data.to_csv(
        structured_output_path,
        index=False, sep=';', encoding='utf-8'
    )
    print(f"  Structured data saved to: {structured_output_path}")
    
    llm_output_path = output_dir / "llm_annotations.csv"
    llm_results.to_csv(
        llm_output_path,
        index=False, sep=';', encoding='utf-8'
    )
    print(f"  LLM annotations saved to: {llm_output_path}")
    
    # Step 7: Analyze results
    if not args.skip_analysis:
        print("\n[STEP 7] Analyzing pipeline results...")
        try:
            import subprocess
            result = subprocess.run([
                'python', str(script_dir / 'analyze_pipeline_results.py'),
                '--input-texts', str(input_texts_path),
                '--output-structured', str(structured_output_path),
                '--llm-annotations', str(llm_output_path),
                '--output-dir', str(output_dir)
            ], capture_output=True, text=True, cwd=str(script_dir))
            
            if result.returncode == 0:
                print("  Analysis complete!")
                # Print key parts of output
                lines = result.stdout.split('\n')
                for line in lines:
                    if any(keyword in line for keyword in ['saved to', 'SUMMARY', 'Total', 'Extracted']):
                        print(f"    {line}")
            else:
                print(f"  [WARN] Analysis had issues: {result.stderr}")
        except Exception as e:
            print(f"  [WARN] Analysis failed: {e}")
            print("  You can run it manually:")
            print(f"    python analyze_pipeline_results.py \\")
            print(f"      --input-texts {input_texts_path} \\")
            print(f"      --output-structured {structured_output_path} \\")
            print(f"      --llm-annotations {llm_output_path} \\")
            print(f"      --output-dir {output_dir}")
    else:
        print("\n[STEP 7 SKIPPED] Analysis skipped (use --skip-analysis to suppress this message)")
    
    # Summary
    print("\n" + "=" * 80)
    print("PIPELINE TEST SUMMARY")
    print("=" * 80)
    print(f"Input notes: {len(texts_df)}")
    print(f"LLM annotations generated: {len(llm_results)}")
    print(f"Structured entities extracted: {len(structured_data)}")
    if args.structured_data:
        print(f"  (Including {len(excel_data)} existing entities)")
    print(f"\nOutput files:")
    print(f"  - Structured data: {structured_output_path}")
    print(f"  - LLM annotations: {llm_output_path}")
    if not args.skip_analysis:
        print(f"  - Analysis reports: {output_dir}/pipeline_*.csv/html")
    print("=" * 80)
    
    print("\nNext steps:")
    print(f"1. Review {structured_output_path} to see extracted entities")
    print(f"2. Review {llm_output_path} to see LLM outputs")
    if not args.skip_analysis:
        print(f"3. Open {output_dir}/pipeline_comparison_report.html for visual analysis")
    else:
        print(f"2. Run analysis: python analyze_pipeline_results.py \\")
        print(f"      --input-texts {input_texts_path} \\")
        print(f"      --output-structured {structured_output_path} \\")
        print(f"      --llm-annotations {llm_output_path}")


if __name__ == "__main__":
    main()
