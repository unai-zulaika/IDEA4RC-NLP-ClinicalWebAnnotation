#!/usr/bin/env python3
"""
Pipeline Analysis Script

Analyzes the full ingestion pipeline results:
- Summary statistics
- Input vs Output comparison
- Entity extraction coverage
- Date extraction summary
- Processing time breakdown
"""

import json
import pandas as pd
import argparse
from pathlib import Path
from typing import Dict, List, Optional
from collections import Counter
import time


def load_data(input_texts_path: Path, output_structured_path: Path, 
              llm_annotations_path: Optional[Path] = None) -> tuple:
    """
    Load input and output data.
    
    Args:
        input_texts_path: Path to input texts CSV
        output_structured_path: Path to structured output CSV
        llm_annotations_path: Optional path to LLM annotations CSV
    
    Returns:
        Tuple of (texts_df, structured_df, llm_df)
    """
    # Detect delimiter
    def detect_delimiter(file_path):
        with open(file_path, 'r', encoding='utf-8') as f:
            first_line = f.readline()
            return ';' if first_line.count(';') > first_line.count(',') else ','
    
    delimiter_texts = detect_delimiter(input_texts_path)
    delimiter_output = detect_delimiter(output_structured_path)
    
    texts_df = pd.read_csv(input_texts_path, delimiter=delimiter_texts, encoding='utf-8')
    structured_df = pd.read_csv(output_structured_path, delimiter=delimiter_output, encoding='utf-8')
    
    llm_df = None
    if llm_annotations_path and llm_annotations_path.exists():
        delimiter_llm = detect_delimiter(llm_annotations_path)
        llm_df = pd.read_csv(llm_annotations_path, delimiter=delimiter_llm, encoding='utf-8')
    
    return texts_df, structured_df, llm_df


def generate_summary_statistics(texts_df: pd.DataFrame, structured_df: pd.DataFrame,
                                llm_df: Optional[pd.DataFrame] = None) -> Dict:
    """
    Generate summary statistics.
    
    Args:
        texts_df: Input texts DataFrame
        structured_df: Structured output DataFrame
        llm_df: Optional LLM annotations DataFrame
    
    Returns:
        Dictionary with summary statistics
    """
    stats = {}
    
    # Basic counts
    stats['total_notes_processed'] = len(texts_df)
    stats['total_entities_extracted'] = len(structured_df)
    
    # Normalize column names for compatibility
    # Structured data may have 'patient_id', input texts have 'p_id'
    if 'patient_id' in structured_df.columns and 'p_id' not in structured_df.columns:
        structured_df['p_id'] = structured_df['patient_id']
    
    # Entities per note
    if 'note_id' in structured_df.columns and 'note_id' in texts_df.columns:
        entities_per_note = structured_df.groupby('note_id').size()
        stats['entities_per_note'] = {
            'avg': float(entities_per_note.mean()) if len(entities_per_note) > 0 else 0.0,
            'min': int(entities_per_note.min()) if len(entities_per_note) > 0 else 0,
            'max': int(entities_per_note.max()) if len(entities_per_note) > 0 else 0,
            'median': float(entities_per_note.median()) if len(entities_per_note) > 0 else 0.0
        }
        
        # Notes with entities vs without
        notes_with_entities = set(structured_df['note_id'].unique())
        all_notes = set(texts_df['note_id'].unique())
        stats['notes_with_entities'] = len(notes_with_entities)
        stats['notes_without_entities'] = len(all_notes - notes_with_entities)
        stats['entity_extraction_rate'] = round(len(notes_with_entities) / len(all_notes), 4) if len(all_notes) > 0 else 0.0
    else:
        stats['entities_per_note'] = {'avg': 0.0, 'min': 0, 'max': 0, 'median': 0.0}
        stats['notes_with_entities'] = 0
        stats['notes_without_entities'] = len(texts_df)
        stats['entity_extraction_rate'] = 0.0
    
    # Core variables coverage
    if 'core_variable' in structured_df.columns:
        core_vars = structured_df['core_variable'].value_counts().to_dict()
        stats['core_variables_coverage'] = {
            'total_unique_variables': len(core_vars),
            'top_10_variables': dict(list(core_vars.items())[:10])
        }
    else:
        stats['core_variables_coverage'] = {'total_unique_variables': 0, 'top_10_variables': {}}
    
    # Date extraction
    date_fields = ['date_ref', 'date', 'extracted_dates']
    date_count = 0
    for field in date_fields:
        if field in structured_df.columns:
            date_count += structured_df[field].notna().sum()
    
    stats['date_extraction'] = {
        'total_dates_extracted': int(date_count),
        'date_extraction_rate': round(date_count / len(structured_df), 4) if len(structured_df) > 0 else 0.0
    }
    
    # Error rate (from LLM annotations if available)
    if llm_df is not None and 'annotation' in llm_df.columns:
        error_annotations = llm_df[llm_df['annotation'].astype(str).str.startswith('ERROR:', na=False)]
        stats['error_rate'] = {
            'total_errors': len(error_annotations),
            'error_percentage': round(len(error_annotations) / len(llm_df) * 100, 2) if len(llm_df) > 0 else 0.0
        }
    else:
        stats['error_rate'] = {'total_errors': 0, 'error_percentage': 0.0}
    
    # Processing time (if available in structured data)
    if 'processing_time_seconds' in structured_df.columns:
        stats['processing_time'] = {
            'total_seconds': float(structured_df['processing_time_seconds'].sum()),
            'avg_per_entity': float(structured_df['processing_time_seconds'].mean()) if len(structured_df) > 0 else 0.0
        }
    else:
        stats['processing_time'] = {'total_seconds': 0.0, 'avg_per_entity': 0.0}
    
    # Source distribution
    if 'original_source' in structured_df.columns:
        source_dist = structured_df['original_source'].value_counts().to_dict()
        stats['source_distribution'] = source_dist
    else:
        stats['source_distribution'] = {}
    
    return stats


def generate_comparison_report(texts_df: pd.DataFrame, structured_df: pd.DataFrame,
                               output_path: Path) -> pd.DataFrame:
    """
    Generate input vs output comparison report.
    
    Args:
        texts_df: Input texts DataFrame
        structured_df: Structured output DataFrame
        output_path: Path to save comparison report
    
    Returns:
        DataFrame with comparison data
    """
    comparison_rows = []
    
    # Normalize column names for compatibility
    # Structured data may have 'patient_id', input texts have 'p_id'
    if 'patient_id' in structured_df.columns and 'p_id' not in structured_df.columns:
        structured_df['p_id'] = structured_df['patient_id']
    
    # Group entities by note_id
    if 'note_id' in structured_df.columns and 'note_id' in texts_df.columns:
        entities_by_note = structured_df.groupby('note_id').apply(
            lambda x: x[['core_variable', 'value']].to_dict('records') if 'core_variable' in x.columns and 'value' in x.columns else []
        ).to_dict()
    else:
        entities_by_note = {}
    
    # Process each note
    for _, note_row in texts_df.iterrows():
        note_id = note_row.get('note_id', '')
        p_id = note_row.get('p_id', '')
        note_date = note_row.get('date', '')
        report_type = note_row.get('report_type', '')
        note_text = note_row.get('text', '')
        
        # Get entities for this note
        entities = entities_by_note.get(note_id, [])
        entity_count = len(entities)
        
        # Format entities as JSON
        entities_json = json.dumps(entities, ensure_ascii=False) if entities else '[]'
        
        # Determine extraction success
        extraction_success = entity_count > 0
        
        comparison_rows.append({
            'note_id': note_id,
            'p_id': p_id,
            'note_date': note_date,
            'report_type': report_type,
            'note_text_preview': note_text[:200] + '...' if len(str(note_text)) > 200 else str(note_text),
            'note_text': str(note_text),
            'entities_extracted': entities_json,
            'entity_count': entity_count,
            'extraction_success': extraction_success
        })
    
    comparison_df = pd.DataFrame(comparison_rows)
    
    # Save CSV
    csv_path = output_path.with_suffix('.csv')
    comparison_df.to_csv(csv_path, index=False, encoding='utf-8', sep=';')
    print(f"  Comparison report CSV saved to: {csv_path}")
    
    # Generate HTML report
    html_path = output_path.with_suffix('.html')
    generate_pipeline_html_report(comparison_df, html_path)
    print(f"  Comparison report HTML saved to: {html_path}")
    
    return comparison_df


def generate_pipeline_html_report(comparison_df: pd.DataFrame, output_path: Path) -> None:
    """Generate HTML report for pipeline comparison."""
    html_content = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Pipeline Analysis Report</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            margin: 20px;
            background-color: #f5f5f5;
        }
        .header {
            background-color: #2c3e50;
            color: white;
            padding: 20px;
            border-radius: 5px;
            margin-bottom: 20px;
        }
        .filters {
            background-color: white;
            padding: 15px;
            border-radius: 5px;
            margin-bottom: 20px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        .filters input, .filters select {
            margin: 5px;
            padding: 8px;
            border: 1px solid #ddd;
            border-radius: 3px;
        }
        .note-card {
            background-color: white;
            border-radius: 5px;
            margin-bottom: 15px;
            padding: 15px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        .note-card.success {
            border-left: 5px solid #27ae60;
        }
        .note-card.no-entities {
            border-left: 5px solid #e74c3c;
        }
        .note-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 10px;
            padding-bottom: 10px;
            border-bottom: 1px solid #eee;
        }
        .note-id {
            font-weight: bold;
            color: #2c3e50;
        }
        .entity-badge {
            padding: 5px 10px;
            border-radius: 3px;
            font-weight: bold;
            font-size: 12px;
        }
        .entity-badge.success {
            background-color: #27ae60;
            color: white;
        }
        .entity-badge.no-entities {
            background-color: #e74c3c;
            color: white;
        }
        .note-text {
            margin: 10px 0;
            padding: 10px;
            background-color: #f8f9fa;
            border-radius: 3px;
            white-space: pre-wrap;
            word-wrap: break-word;
        }
        .entities-section {
            margin-top: 10px;
        }
        .entity-item {
            padding: 5px 10px;
            margin: 5px 0;
            background-color: #e8f5e9;
            border-radius: 3px;
            border-left: 3px solid #27ae60;
        }
        .entity-variable {
            font-weight: bold;
            color: #2c3e50;
        }
        .entity-value {
            color: #555;
        }
        .hidden {
            display: none;
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>Pipeline Analysis Report</h1>
        <p>Input texts vs extracted entities comparison</p>
    </div>
    
    <div class="filters">
        <input type="text" id="search-input" placeholder="Search by note_id, p_id, or report_type..." style="width: 300px;">
        <select id="success-filter">
            <option value="all">All Notes</option>
            <option value="success">With Entities</option>
            <option value="no-entities">No Entities</option>
        </select>
        <select id="report-type-filter">
            <option value="all">All Report Types</option>
        </select>
    </div>
    
    <div id="notes-container"></div>
    
    <script>
        const notes = """ + comparison_df.to_json(orient='records', force_ascii=False) + """;
        
        // Populate report type filter
        const reportTypes = [...new Set(notes.map(n => n.report_type || 'N/A'))].sort();
        const reportTypeFilter = document.getElementById('report-type-filter');
        reportTypes.forEach(rt => {
            const option = document.createElement('option');
            option.value = rt;
            option.textContent = rt;
            reportTypeFilter.appendChild(option);
        });
        
        function renderNotes(filteredNotes) {
            const container = document.getElementById('notes-container');
            container.innerHTML = '';
            
            filteredNotes.forEach(note => {
                const card = document.createElement('div');
                const hasEntities = note.entity_count > 0;
                card.className = 'note-card ' + (hasEntities ? 'success' : 'no-entities');
                
                const entities = JSON.parse(note.entities_extracted || '[]');
                const entitiesHtml = entities.map(e => `
                    <div class="entity-item">
                        <span class="entity-variable">${e.core_variable || 'N/A'}:</span>
                        <span class="entity-value">${e.value || 'N/A'}</span>
                    </div>
                `).join('');
                
                card.innerHTML = `
                    <div class="note-header">
                        <div class="note-id">
                            Note: ${note.note_id || 'N/A'} | Patient: ${note.p_id || 'N/A'} | Type: ${note.report_type || 'N/A'}
                        </div>
                        <div class="entity-badge ${hasEntities ? 'success' : 'no-entities'}">
                            ${note.entity_count} entities
                        </div>
                    </div>
                    <div class="note-text">${(note.note_text_preview || note.note_text || '[NO TEXT]').replace(/\\n/g, '<br>')}</div>
                    <div class="entities-section">
                        <strong>Extracted Entities:</strong>
                        ${entities.length > 0 ? entitiesHtml : '<div style="color: #999; font-style: italic;">No entities extracted</div>'}
                    </div>
                `;
                
                container.appendChild(card);
            });
        }
        
        function filterNotes() {
            const searchTerm = document.getElementById('search-input').value.toLowerCase();
            const successFilter = document.getElementById('success-filter').value;
            const reportTypeFilter = document.getElementById('report-type-filter').value;
            
            let filtered = notes.filter(note => {
                const matchesSearch = !searchTerm || 
                    (note.note_id && note.note_id.toString().toLowerCase().includes(searchTerm)) ||
                    (note.p_id && note.p_id.toString().toLowerCase().includes(searchTerm)) ||
                    (note.report_type && note.report_type.toLowerCase().includes(searchTerm));
                
                const matchesSuccessFilter = successFilter === 'all' ||
                    (successFilter === 'success' && note.entity_count > 0) ||
                    (successFilter === 'no-entities' && note.entity_count === 0);
                
                const matchesReportType = reportTypeFilter === 'all' || note.report_type === reportTypeFilter;
                
                return matchesSearch && matchesSuccessFilter && matchesReportType;
            });
            
            renderNotes(filtered);
        }
        
        document.getElementById('search-input').addEventListener('input', filterNotes);
        document.getElementById('success-filter').addEventListener('change', filterNotes);
        document.getElementById('report-type-filter').addEventListener('change', filterNotes);
        
        // Initial render
        renderNotes(notes);
    </script>
</body>
</html>"""
    
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html_content)


def main():
    """Main analysis function."""
    parser = argparse.ArgumentParser(
        description="Analyze full ingestion pipeline results"
    )
    parser.add_argument(
        "--input-texts",
        type=str,
        required=True,
        help="Path to input texts CSV"
    )
    parser.add_argument(
        "--output-structured",
        type=str,
        required=True,
        help="Path to structured output CSV"
    )
    parser.add_argument(
        "--llm-annotations",
        type=str,
        default=None,
        help="Optional path to LLM annotations CSV"
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Output directory for reports (default: same as input-texts directory)"
    )
    
    args = parser.parse_args()
    
    input_texts_path = Path(args.input_texts)
    output_structured_path = Path(args.output_structured)
    llm_annotations_path = Path(args.llm_annotations) if args.llm_annotations else None
    
    if args.output_dir:
        output_dir = Path(args.output_dir)
    else:
        output_dir = input_texts_path.parent
    
    output_dir.mkdir(parents=True, exist_ok=True)
    
    print("=" * 80)
    print("Pipeline Analysis")
    print("=" * 80)
    
    # Load data
    print("\n[STEP 1] Loading data...")
    texts_df, structured_df, llm_df = load_data(
        input_texts_path, output_structured_path, llm_annotations_path
    )
    print(f"  Loaded {len(texts_df)} input notes")
    print(f"  Loaded {len(structured_df)} structured entities")
    if llm_df is not None:
        print(f"  Loaded {len(llm_df)} LLM annotations")
    
    # Generate summary statistics
    print("\n[STEP 2] Generating summary statistics...")
    stats = generate_summary_statistics(texts_df, structured_df, llm_df)
    
    # Save statistics
    stats_json_path = output_dir / "pipeline_summary_statistics.json"
    with open(stats_json_path, 'w', encoding='utf-8') as f:
        json.dump(stats, f, indent=2, ensure_ascii=False)
    print(f"  Summary statistics JSON saved to: {stats_json_path}")
    
    # Convert to DataFrame for CSV
    stats_flat = {
        'total_notes_processed': stats['total_notes_processed'],
        'total_entities_extracted': stats['total_entities_extracted'],
        'entities_per_note_avg': stats['entities_per_note']['avg'],
        'entities_per_note_min': stats['entities_per_note']['min'],
        'entities_per_note_max': stats['entities_per_note']['max'],
        'entities_per_note_median': stats['entities_per_note']['median'],
        'notes_with_entities': stats['notes_with_entities'],
        'notes_without_entities': stats['notes_without_entities'],
        'entity_extraction_rate': stats['entity_extraction_rate'],
        'total_unique_variables': stats['core_variables_coverage']['total_unique_variables'],
        'total_dates_extracted': stats['date_extraction']['total_dates_extracted'],
        'date_extraction_rate': stats['date_extraction']['date_extraction_rate'],
        'total_errors': stats['error_rate']['total_errors'],
        'error_percentage': stats['error_rate']['error_percentage']
    }
    
    stats_csv_path = output_dir / "pipeline_summary_statistics.csv"
    stats_df = pd.DataFrame([stats_flat])
    stats_df.to_csv(stats_csv_path, index=False, encoding='utf-8', sep=';')
    print(f"  Summary statistics CSV saved to: {stats_csv_path}")
    
    # Generate comparison report
    print("\n[STEP 3] Generating comparison report...")
    comparison_path = output_dir / "pipeline_comparison_report"
    comparison_df = generate_comparison_report(texts_df, structured_df, comparison_path)
    
    # Print summary
    print("\n" + "=" * 80)
    print("ANALYSIS SUMMARY")
    print("=" * 80)
    print(f"Total notes processed: {stats['total_notes_processed']}")
    print(f"Total entities extracted: {stats['total_entities_extracted']}")
    print(f"Entities per note (avg): {stats['entities_per_note']['avg']:.2f}")
    print(f"Notes with entities: {stats['notes_with_entities']}/{stats['total_notes_processed']} ({stats['entity_extraction_rate']*100:.1f}%)")
    print(f"Date extraction rate: {stats['date_extraction']['date_extraction_rate']*100:.1f}%")
    if stats['error_rate']['total_errors'] > 0:
        print(f"Error rate: {stats['error_rate']['error_percentage']:.2f}% ({stats['error_rate']['total_errors']} errors)")
    print("=" * 80)


if __name__ == "__main__":
    main()
