#!/usr/bin/env python3
"""
Main Evaluation Script for LLM INT Prompts

Orchestrates the evaluation pipeline:
1. Load notes and expected annotations
2. Adapt prompts and load into model_runner
3. Build/load FAISS indexes for fewshot examples
4. Run LLM inference on each note-prompt combination
5. Evaluate outputs against expected annotations
6. Generate detailed evaluation reports
"""

import json
import pandas as pd
from pathlib import Path
from typing import Dict, List, Tuple, Optional
import sys
import time
from datetime import timedelta

# Import our modules
from prompt_adapter import adapt_int_prompts
from fewshot_builder import FewshotBuilder, map_annotation_to_prompt
from evaluation_engine import evaluate_annotation, batch_evaluate
from model_runner import init_model, run_model_with_prompt, get_prompt
from date_evaluation import evaluate_dates
from confidence_analyzer import (
    calculate_confidence_from_logprobs,
    should_reject_as_no_outcome,
    get_confidence_metrics,
    analyze_output_for_placeholders
)

# Import model_runner module to access _PROMPTS
import model_runner as mr


def load_adapted_prompts(prompts_json_path: str | Path):
    """
    Adapt INT prompts and load them into model_runner's global _PROMPTS.
    
    Args:
        prompts_json_path: Path to FBK_scripts/prompts.json
    """
    print("[INFO] Adapting INT prompts for model_runner...")
    adapted_prompts = adapt_int_prompts(prompts_json_path)
    
    # Load into model_runner's global _PROMPTS
    mr._PROMPTS = adapted_prompts
    print(f"[INFO] Loaded {len(adapted_prompts)} adapted prompts into model_runner")


def load_annotations_from_json(json_file_path: str | Path) -> Dict[str, Dict[str, str]]:
    """
    Load annotations from JSON file and create a lookup dictionary.
    
    Args:
        json_file_path: Path to annotated_patient_notes_with_spans_full_verified.json
    
    Returns:
        Dictionary mapping (note_id, prompt_type) -> annotation text
    """
    json_file_path = Path(json_file_path)
    
    if not json_file_path.exists():
        raise FileNotFoundError(f"JSON file not found: {json_file_path}")
    
    print(f"[INFO] Loading annotations from JSON: {json_file_path}")
    
    with open(json_file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    # Create lookup dictionary: note_id -> {'_all_annotations': [list of annotations]}
    annotations_lookup = {}
    
    for patient in data:
        for note in patient.get('notes', []):
            note_id = note.get('note_id', '')
            if not note_id:
                continue
            
            annotations = note.get('annotations', [])
            
            # For each annotation, determine which prompt type it matches
            for annotation in annotations:
                # Try to match this annotation to a prompt type
                # We need to check against common prompt types
                # Since we don't have the prompts loaded yet, we'll match dynamically
                # Store all annotations for this note, and we'll match them later
                if note_id not in annotations_lookup:
                    annotations_lookup[note_id] = {}
                
                # Store annotation text - we'll match to prompt_type when needed
                annotations_lookup[note_id]['_all_annotations'] = annotations
    
    print(f"[INFO] Loaded annotations for {len(annotations_lookup)} notes")
    return annotations_lookup


def get_expected_annotation_from_json(
    annotations_lookup: Dict[str, Dict[str, str]],
    note_id: str,
    prompt_type: str
) -> str:
    """
    Get expected annotation for a note-prompt combination from JSON lookup.
    
    Args:
        annotations_lookup: Dictionary from load_annotations_from_json
        note_id: The note ID
        prompt_type: The prompt type (e.g., 'gender-int')
    
    Returns:
        Expected annotation text, or empty string if not found
    """
    if note_id not in annotations_lookup:
        return ""
    
    note_annotations = annotations_lookup[note_id].get('_all_annotations', [])
    
    # Find matching annotation for this prompt type
    for annotation in note_annotations:
        if map_annotation_to_prompt(annotation, prompt_type):
            return annotation
    
    return ""


def generate_date_html_report(date_df: pd.DataFrame, date_stats: Dict, output_path: Path) -> None:
    """
    Generate an HTML comparison report for date evaluation.
    
    Args:
        date_df: DataFrame with date evaluation results
        date_stats: Dictionary with date statistics
        output_path: Path to save HTML file
    """
    html_content = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Date Evaluation Comparison Report</title>
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
        .stats {
            background-color: white;
            padding: 15px;
            border-radius: 5px;
            margin-bottom: 20px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        .stat-item {
            display: inline-block;
            margin: 10px;
            padding: 10px 15px;
            background-color: #ecf0f1;
            border-radius: 3px;
        }
        .stat-value {
            font-size: 24px;
            font-weight: bold;
            color: #2c3e50;
        }
        .stat-label {
            font-size: 12px;
            color: #7f8c8d;
        }
        .fewshot-section {
            margin-top: 20px;
            padding: 15px;
            background-color: #f8f9fa;
            border-radius: 5px;
            border-left: 4px solid #3498db;
        }
        .fewshot-header {
            font-weight: bold;
            color: #2c3e50;
            margin-bottom: 10px;
            font-size: 14px;
        }
        .fewshot-example {
            margin-bottom: 15px;
            padding: 10px;
            background-color: white;
            border-radius: 3px;
            border: 1px solid #dee2e6;
        }
        .fewshot-example:last-child {
            margin-bottom: 0;
        }
        .fewshot-example-label {
            font-weight: bold;
            color: #495057;
            font-size: 12px;
            margin-bottom: 5px;
        }
        .fewshot-note {
            font-size: 12px;
            color: #6c757d;
            margin-bottom: 8px;
            padding: 5px;
            background-color: #f8f9fa;
            border-radius: 2px;
        }
        .fewshot-annotation {
            font-size: 12px;
            color: #28a745;
            font-weight: 500;
            padding: 5px;
            background-color: #d4edda;
            border-radius: 2px;
        }
        .fewshot-toggle {
            background-color: #3498db;
            color: white;
            border: none;
            padding: 5px 10px;
            border-radius: 3px;
            cursor: pointer;
            font-size: 11px;
            margin-top: 5px;
        }
        .fewshot-toggle:hover {
            background-color: #2980b9;
        }
        .fewshot-container {
            max-height: 300px;
            overflow-y: auto;
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
        .result-card {
            background-color: white;
            border-radius: 5px;
            margin-bottom: 15px;
            padding: 15px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        .result-card.exact {
            border-left: 5px solid #27ae60;
        }
        .result-card.partial {
            border-left: 5px solid #f39c12;
        }
        .result-card.year {
            border-left: 5px solid #e67e22;
        }
        .result-card.none {
            border-left: 5px solid #e74c3c;
        }
        .result-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 10px;
            padding-bottom: 10px;
            border-bottom: 1px solid #eee;
        }
        .result-id {
            font-weight: bold;
            color: #2c3e50;
        }
        .match-badge {
            padding: 5px 10px;
            border-radius: 3px;
            font-weight: bold;
            font-size: 12px;
        }
        .match-badge.exact {
            background-color: #27ae60;
            color: white;
        }
        .match-badge.partial {
            background-color: #f39c12;
            color: white;
        }
        .match-badge.year {
            background-color: #e67e22;
            color: white;
        }
        .match-badge.none {
            background-color: #e74c3c;
            color: white;
        }
        .date-comparison {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 15px;
            margin-top: 10px;
        }
        .date-column {
            padding: 10px;
            border-radius: 3px;
        }
        .date-column.expected {
            background-color: #ecf0f1;
        }
        .date-column.predicted {
            background-color: #e8f5e9;
        }
        .column-label {
            font-weight: bold;
            margin-bottom: 8px;
            color: #2c3e50;
        }
        .date-list {
            font-size: 14px;
            line-height: 1.8;
        }
        .date-item {
            padding: 5px;
            margin: 3px 0;
            background-color: white;
            border-radius: 3px;
            border-left: 3px solid #3498db;
        }
        .date-item.matched {
            border-left-color: #27ae60;
            background-color: #d5f4e6;
        }
        .metrics {
            display: flex;
            gap: 15px;
            margin-top: 10px;
            font-size: 12px;
            color: #7f8c8d;
        }
        .metric {
            padding: 5px 10px;
            background-color: #ecf0f1;
            border-radius: 3px;
        }
        .metric-value {
            font-weight: bold;
            color: #2c3e50;
        }
        .no-dates {
            color: #95a5a6;
            font-style: italic;
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>Date Evaluation Comparison Report</h1>
        <p>Comparison of expected vs predicted dates in LLM annotations</p>
    </div>
    
    <div class="stats" id="stats">
        <div class="stat-item">
            <div class="stat-value" id="total-count">0</div>
            <div class="stat-label">Total Evaluations</div>
        </div>
        <div class="stat-item">
            <div class="stat-value" id="with-dates-count">0</div>
            <div class="stat-label">With Expected Dates</div>
        </div>
        <div class="stat-item">
            <div class="stat-value" id="exact-match-count">0</div>
            <div class="stat-label">Exact Matches</div>
        </div>
        <div class="stat-item">
            <div class="stat-value" id="accuracy">0%</div>
            <div class="stat-label">Date Accuracy</div>
        </div>
    </div>
    
    <div class="filters">
        <input type="text" id="search-input" placeholder="Search by note_id, p_id, or prompt_type..." style="width: 300px;">
        <select id="match-filter">
            <option value="all">All Results</option>
            <option value="exact">Exact Matches</option>
            <option value="partial">Partial Matches</option>
            <option value="year">Year Matches</option>
            <option value="none">No Match</option>
        </select>
        <select id="prompt-filter">
            <option value="all">All Prompt Types</option>
        </select>
    </div>
    
    <div id="results-container"></div>
    
    <script>
        const results = """ + date_df.to_json(orient='records', force_ascii=False) + """;
        const stats = """ + json.dumps(date_stats, ensure_ascii=False) + """;
        
        // Populate filters
        const promptTypes = [...new Set(results.map(r => r.prompt_type))].sort();
        const promptFilter = document.getElementById('prompt-filter');
        promptTypes.forEach(pt => {
            const option = document.createElement('option');
            option.value = pt;
            option.textContent = pt;
            promptFilter.appendChild(option);
        });
        
        function updateStats(filteredResults) {
            const total = filteredResults.length;
            const withDates = filteredResults.filter(r => r.expected_count > 0).length;
            const exactMatches = filteredResults.filter(r => r.date_match_type === 'exact').length;
            const accuracy = withDates > 0 ? Math.round((exactMatches / withDates) * 100) : 0;
            
            document.getElementById('total-count').textContent = total;
            document.getElementById('with-dates-count').textContent = withDates;
            document.getElementById('exact-match-count').textContent = exactMatches;
            document.getElementById('accuracy').textContent = accuracy + '%';
        }
        
        function parseDates(dateStr) {
            if (!dateStr || dateStr.trim() === '') return [];
            return dateStr.split(',').map(d => d.trim()).filter(d => d);
        }
        
        function renderResults(filteredResults) {
            const container = document.getElementById('results-container');
            container.innerHTML = '';
            
            filteredResults.forEach((result, index) => {
                const card = document.createElement('div');
                const matchType = result.date_match_type || 'none';
                card.className = 'result-card ' + matchType;
                
                const expectedDates = parseDates(result.expected_dates || '');
                const predictedDates = parseDates(result.predicted_dates || '');
                const exactMatchDates = parseDates(result.exact_match_dates || '');
                
                // Create date lists
                const expectedDatesHtml = expectedDates.length > 0 
                    ? expectedDates.map(d => `<div class="date-item ${exactMatchDates.includes(d) ? 'matched' : ''}">${d}</div>`).join('')
                    : '<div class="no-dates">No expected dates</div>';
                
                const predictedDatesHtml = predictedDates.length > 0
                    ? predictedDates.map(d => `<div class="date-item ${exactMatchDates.includes(d) ? 'matched' : ''}">${d}</div>`).join('')
                    : '<div class="no-dates">No predicted dates</div>';
                
                const matchTypeLabels = {
                    'exact': '✓ Exact Match',
                    'partial': '~ Partial Match',
                    'year': '≈ Year Match',
                    'none': '✗ No Match'
                };
                
                card.innerHTML = `
                    <div class="result-header">
                        <div class="result-id">
                            Note: ${result.note_id || 'N/A'} | Patient: ${result.p_id || 'N/A'} | Prompt: ${result.prompt_type || 'N/A'}
                        </div>
                        <div class="match-badge ${matchType}">${matchTypeLabels[matchType] || 'Unknown'}</div>
                    </div>
                    <div class="date-comparison">
                        <div class="date-column expected">
                            <div class="column-label">Expected Dates (${result.expected_count || 0})</div>
                            <div class="date-list">${expectedDatesHtml}</div>
                        </div>
                        <div class="date-column predicted">
                            <div class="column-label">Predicted Dates (${result.predicted_count || 0})</div>
                            <div class="date-list">${predictedDatesHtml}</div>
                        </div>
                    </div>
                    <div class="metrics">
                        <div class="metric">
                            <span class="metric-value">Precision:</span> ${(result.date_precision || 0).toFixed(3)}
                        </div>
                        <div class="metric">
                            <span class="metric-value">Recall:</span> ${(result.date_recall || 0).toFixed(3)}
                        </div>
                        <div class="metric">
                            <span class="metric-value">F1 Score:</span> ${(result.date_f1_score || 0).toFixed(3)}
                        </div>
                        <div class="metric">
                            <span class="metric-value">Exact Matches:</span> ${result.exact_matches || 0}
                        </div>
                        <div class="metric">
                            <span class="metric-value">Partial Matches:</span> ${result.partial_matches || 0}
                        </div>
                        <div class="metric">
                            <span class="metric-value">Year Matches:</span> ${result.year_matches || 0}
                        </div>
                    </div>
                `;
                
                container.appendChild(card);
            });
            
            updateStats(filteredResults);
        }
        
        function filterResults() {
            const searchTerm = document.getElementById('search-input').value.toLowerCase();
            const matchFilter = document.getElementById('match-filter').value;
            const promptFilter = document.getElementById('prompt-filter').value;
            
            // All results already have expected_count > 0 (filtered before HTML generation)
            let filtered = results.filter(r => {
                const matchesSearch = !searchTerm || 
                    (r.note_id && r.note_id.toString().toLowerCase().includes(searchTerm)) ||
                    (r.p_id && r.p_id.toString().toLowerCase().includes(searchTerm)) ||
                    (r.prompt_type && r.prompt_type.toLowerCase().includes(searchTerm));
                
                const matchesMatchFilter = matchFilter === 'all' ||
                    (matchFilter === 'exact' && r.date_match_type === 'exact') ||
                    (matchFilter === 'partial' && r.date_match_type === 'partial') ||
                    (matchFilter === 'year' && r.date_match_type === 'year') ||
                    (matchFilter === 'none' && r.date_match_type === 'none');
                
                const matchesPromptFilter = promptFilter === 'all' || r.prompt_type === promptFilter;
                
                return matchesSearch && matchesMatchFilter && matchesPromptFilter;
            });
            
            renderResults(filtered);
        }
        
        document.getElementById('search-input').addEventListener('input', filterResults);
        document.getElementById('match-filter').addEventListener('change', filterResults);
        document.getElementById('prompt-filter').addEventListener('change', filterResults);
        
        // Initial render
        renderResults(results);
    </script>
</body>
</html>"""
    
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html_content)


def generate_html_report(results_df: pd.DataFrame, output_path: Path) -> None:
    """
    Generate an HTML comparison report with side-by-side view of expected vs predicted annotations.
    
    Args:
        results_df: DataFrame with evaluation results
        output_path: Path to save HTML file
    """
    html_content = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>LLM Evaluation Comparison Report</title>
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
        .result-card {
            background-color: white;
            border-radius: 5px;
            margin-bottom: 15px;
            padding: 15px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        .result-card.match {
            border-left: 5px solid #27ae60;
        }
        .result-card.mismatch {
            border-left: 5px solid #e74c3c;
        }
        .result-card.false-positive {
            border-left: 5px solid #e67e22;
            background-color: #fff5e6;
        }
        .result-card.partial {
            border-left: 5px solid #f39c12;
        }
        .result-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 10px;
            padding-bottom: 10px;
            border-bottom: 1px solid #eee;
        }
        .result-id {
            font-weight: bold;
            color: #2c3e50;
        }
        .match-badge {
            padding: 5px 10px;
            border-radius: 3px;
            font-weight: bold;
            font-size: 12px;
        }
        .match-badge.match {
            background-color: #27ae60;
            color: white;
        }
        .match-badge.mismatch {
            background-color: #e74c3c;
            color: white;
        }
        .match-badge.false-positive {
            background-color: #e67e22;
            color: white;
        }
        .match-badge.partial {
            background-color: #f39c12;
            color: white;
        }
        .comparison-grid {
            display: grid;
            grid-template-columns: 1fr 1fr 1fr;
            gap: 15px;
            margin-top: 10px;
        }
        .comparison-column {
            padding: 10px;
            border-radius: 3px;
        }
        .comparison-column.expected {
            background-color: #ecf0f1;
        }
        .comparison-column.predicted {
            background-color: #e8f5e9;
        }
        .comparison-column.original {
            background-color: #fff3e0;
        }
        .column-label {
            font-weight: bold;
            margin-bottom: 8px;
            color: #2c3e50;
        }
        .annotation-text {
            white-space: pre-wrap;
            word-wrap: break-word;
            font-size: 14px;
            line-height: 1.5;
        }
        .note-text-full {
            max-height: 400px;
            overflow-y: auto;
            padding: 10px;
            background-color: #f8f9fa;
            border-radius: 3px;
            border: 1px solid #dee2e6;
            white-space: pre-wrap;
            word-wrap: break-word;
            font-size: 13px;
            line-height: 1.6;
        }
        .note-text-preview {
            padding: 10px;
            background-color: #f8f9fa;
            border-radius: 3px;
            border: 1px solid #dee2e6;
            white-space: pre-wrap;
            word-wrap: break-word;
            font-size: 13px;
            line-height: 1.6;
            max-height: 150px;
            overflow: hidden;
            position: relative;
        }
        .note-text-preview::after {
            content: '...';
            position: absolute;
            bottom: 0;
            right: 0;
            background: linear-gradient(to right, transparent, #f8f9fa 50%);
            padding-left: 20px;
        }
        .toggle-note-text {
            background-color: #3498db;
            color: white;
            border: none;
            padding: 5px 15px;
            border-radius: 3px;
            cursor: pointer;
            font-size: 12px;
            margin-top: 5px;
        }
        .toggle-note-text:hover {
            background-color: #2980b9;
        }
        .note-text-container {
            margin-top: 10px;
        }
        .metrics {
            display: flex;
            gap: 15px;
            margin-top: 10px;
            font-size: 12px;
            color: #7f8c8d;
        }
        .metric {
            padding: 5px 10px;
            background-color: #ecf0f1;
            border-radius: 3px;
        }
        .metric-value {
            font-weight: bold;
            color: #2c3e50;
        }
        .confidence-rejected {
            background-color: #ffebee;
            border-left: 3px solid #c62828;
        }
        .confidence-high {
            background-color: #e8f5e9;
        }
        .confidence-low {
            background-color: #fff3e0;
        }
        .hidden {
            display: none;
        }
        .stats {
            background-color: white;
            padding: 15px;
            border-radius: 5px;
            margin-bottom: 20px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        .stat-item {
            display: inline-block;
            margin: 10px;
            padding: 10px 15px;
            background-color: #ecf0f1;
            border-radius: 3px;
        }
        .stat-value {
            font-size: 24px;
            font-weight: bold;
            color: #2c3e50;
        }
        .stat-label {
            font-size: 12px;
            color: #7f8c8d;
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>LLM Evaluation Comparison Report</h1>
        <p>Side-by-side comparison of expected vs predicted annotations</p>
    </div>
    
    <div class="stats" id="stats">
        <div class="stat-item">
            <div class="stat-value" id="total-count">0</div>
            <div class="stat-label">Total Evaluations</div>
        </div>
        <div class="stat-item">
            <div class="stat-value" id="match-count">0</div>
            <div class="stat-label">Matches</div>
        </div>
        <div class="stat-item">
            <div class="stat-value" id="mismatch-count">0</div>
            <div class="stat-label">Mismatches</div>
        </div>
        <div class="stat-item">
            <div class="stat-value" id="false-positive-count">0</div>
            <div class="stat-label">False Positives<br/>(Predicted when None Expected)</div>
        </div>
        <div class="stat-item">
            <div class="stat-value" id="rejected-count">0</div>
            <div class="stat-label">Rejected<br/>(Low Confidence)</div>
        </div>
    </div>
    
    <div class="stats" id="confidence-stats" style="display: none; margin-top: 20px;">
        <h3 style="margin-bottom: 15px; color: #2c3e50;">Confidence Statistics</h3>
        <div class="stat-item">
            <div class="stat-value" id="conf-total">0</div>
            <div class="stat-label">With Confidence Data</div>
        </div>
        <div class="stat-item">
            <div class="stat-value" id="conf-avg">-</div>
            <div class="stat-label">Avg Confidence</div>
        </div>
        <div class="stat-item">
            <div class="stat-value" id="conf-min">-</div>
            <div class="stat-label">Min Confidence</div>
        </div>
        <div class="stat-item">
            <div class="stat-value" id="conf-max">-</div>
            <div class="stat-label">Max Confidence</div>
        </div>
        <div class="stat-item">
            <div class="stat-value" id="conf-fp-avg">-</div>
            <div class="stat-label">False Positives<br/>Avg Confidence</div>
        </div>
        <div class="stat-item">
            <div class="stat-value" id="conf-correct-avg">-</div>
            <div class="stat-label">Correct Predictions<br/>Avg Confidence</div>
        </div>
    </div>
    
    <div class="stats" id="min-confidence-stats" style="display: none; margin-top: 20px;">
        <h3 style="margin-bottom: 15px; color: #2c3e50;">Average Min Token Confidence by Category</h3>
        <div class="stat-item">
            <div class="stat-value" id="conf-match-min-avg">-</div>
            <div class="stat-label">Matches<br/>Avg Min Logprob</div>
        </div>
        <div class="stat-item">
            <div class="stat-value" id="conf-mismatch-min-avg">-</div>
            <div class="stat-label">Mismatches<br/>Avg Min Logprob</div>
        </div>
        <div class="stat-item">
            <div class="stat-value" id="conf-fp-min-avg">-</div>
            <div class="stat-label">False Positives<br/>Avg Min Logprob</div>
        </div>
    </div>
    
    <div class="filters">
        <input type="text" id="search-input" placeholder="Search by note_id, p_id, or prompt_type..." style="width: 300px;">
        <select id="match-filter">
            <option value="all">All Results</option>
            <option value="match">Matches Only</option>
            <option value="mismatch">Mismatches Only</option>
            <option value="false-positive">False Positives Only</option>
        </select>
        <select id="prompt-filter">
            <option value="all">All Prompt Types</option>
        </select>
    </div>
    
    <div class="pagination-controls" id="pagination-controls" style="background-color: white; padding: 15px; border-radius: 5px; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); display: none;">
        <div style="display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 10px;">
            <div style="display: flex; align-items: center; gap: 10px;">
                <label for="page-size-select" style="font-weight: bold;">Results per page:</label>
                <select id="page-size-select" style="padding: 5px; border: 1px solid #ddd; border-radius: 3px;">
                    <option value="25">25</option>
                    <option value="50" selected>50</option>
                    <option value="100">100</option>
                    <option value="200">200</option>
                </select>
            </div>
            <div id="results-info" style="color: #7f8c8d; font-weight: bold;">
                Showing 0-0 of 0 results
            </div>
            <div style="display: flex; align-items: center; gap: 5px;">
                <button id="pagination-prev" style="padding: 5px 15px; border: 1px solid #ddd; border-radius: 3px; background-color: #ecf0f1; cursor: pointer;" disabled>Previous</button>
                <div id="pagination-pages" style="display: flex; gap: 5px; align-items: center;">
                    <!-- Page numbers will be inserted here -->
                </div>
                <button id="pagination-next" style="padding: 5px 15px; border: 1px solid #ddd; border-radius: 3px; background-color: #ecf0f1; cursor: pointer;" disabled>Next</button>
            </div>
            <div style="display: flex; align-items: center; gap: 5px;">
                <label for="jump-to-page" style="font-size: 12px;">Jump to:</label>
                <input type="number" id="jump-to-page" min="1" value="1" style="width: 60px; padding: 5px; border: 1px solid #ddd; border-radius: 3px;">
                <button id="jump-to-page-btn" style="padding: 5px 10px; border: 1px solid #ddd; border-radius: 3px; background-color: #3498db; color: white; cursor: pointer;">Go</button>
            </div>
        </div>
    </div>
    
    <div id="results-container"></div>
    
    <script>
        const results = """ + results_df.to_json(orient='records', force_ascii=False) + """;
        
        // Pagination state
        let currentPage = 0;
        let pageSize = 50;
        let totalPages = 0;
        
        // Populate prompt filter
        const promptTypes = [...new Set(results.map(r => r.prompt_type))].sort();
        const promptFilter = document.getElementById('prompt-filter');
        promptTypes.forEach(pt => {
            const option = document.createElement('option');
            option.value = pt;
            option.textContent = pt;
            promptFilter.appendChild(option);
        });
        
        function isFalsePositive(result) {
            const hasExpected = result.expected_annotation && 
                result.expected_annotation.trim() !== '' && 
                result.expected_annotation !== '[NO EXPECTED ANNOTATION]';
            const hasPredicted = result.predicted_annotation && 
                result.predicted_annotation.trim() !== '' && 
                result.predicted_annotation !== '[NO PREDICTION]';
            return !hasExpected && hasPredicted;
        }
        
        function updateStats(filteredResults) {
            const total = filteredResults.length;
            const matches = filteredResults.filter(r => r.overall_match).length;
            const mismatches = total - matches;
            
            // Count false positives: LLM predicted something when no expected annotation
            const falsePositives = filteredResults.filter(isFalsePositive).length;
            
            // Count rejected predictions
            const rejected = filteredResults.filter(r => r.confidence_rejected).length;
            
            document.getElementById('total-count').textContent = total;
            document.getElementById('match-count').textContent = matches;
            document.getElementById('mismatch-count').textContent = mismatches;
            document.getElementById('false-positive-count').textContent = falsePositives;
            document.getElementById('rejected-count').textContent = rejected;
            
            // Update confidence statistics
            updateConfidenceStats(filteredResults);
        }
        
        function updateConfidenceStats(filteredResults) {
            // Filter results with confidence data
            const withConfidence = filteredResults.filter(r => 
                r.confidence_score !== null && r.confidence_score !== undefined
            );
            
            if (withConfidence.length === 0) {
                document.getElementById('confidence-stats').style.display = 'none';
                return;
            }
            
            document.getElementById('confidence-stats').style.display = 'block';
            
            // Calculate overall confidence statistics
            const confScores = withConfidence.map(r => r.confidence_score);
            const avgConf = confScores.reduce((a, b) => a + b, 0) / confScores.length;
            const minConf = Math.min(...confScores);
            const maxConf = Math.max(...confScores);
            
            document.getElementById('conf-total').textContent = withConfidence.length;
            document.getElementById('conf-avg').textContent = avgConf.toFixed(3);
            document.getElementById('conf-min').textContent = minConf.toFixed(3);
            document.getElementById('conf-max').textContent = maxConf.toFixed(3);
            
            // Calculate false positives confidence
            const falsePositives = withConfidence.filter(isFalsePositive);
            if (falsePositives.length > 0) {
                const fpScores = falsePositives.map(r => r.confidence_score);
                const fpAvg = fpScores.reduce((a, b) => a + b, 0) / fpScores.length;
                document.getElementById('conf-fp-avg').textContent = fpAvg.toFixed(3);
            } else {
                document.getElementById('conf-fp-avg').textContent = 'N/A';
            }
            
            // Calculate correct predictions confidence
            const correctPredictions = withConfidence.filter(r => r.overall_match);
            if (correctPredictions.length > 0) {
                const correctScores = correctPredictions.map(r => r.confidence_score);
                const correctAvg = correctScores.reduce((a, b) => a + b, 0) / correctScores.length;
                document.getElementById('conf-correct-avg').textContent = correctAvg.toFixed(3);
            } else {
                document.getElementById('conf-correct-avg').textContent = 'N/A';
            }
            
            // Calculate average min logprob by category
            updateMinLogprobStats(filteredResults);
        }
        
        function updateMinLogprobStats(filteredResults) {
            // Filter results with min logprob data
            const withMinLogprob = filteredResults.filter(r => 
                r.confidence_min_logprob !== null && r.confidence_min_logprob !== undefined
            );
            
            if (withMinLogprob.length === 0) {
                document.getElementById('min-confidence-stats').style.display = 'none';
                return;
            }
            
            document.getElementById('min-confidence-stats').style.display = 'block';
            
            // Separate into matches, mismatches, and false positives
            const matches = withMinLogprob.filter(r => r.overall_match);
            const mismatches = withMinLogprob.filter(r => !r.overall_match && !isFalsePositive(r));
            const falsePositives = withMinLogprob.filter(isFalsePositive);
            
            // Calculate average min logprob for matches
            if (matches.length > 0) {
                const matchMinLogprobs = matches.map(r => r.confidence_min_logprob);
                const matchMinAvg = matchMinLogprobs.reduce((a, b) => a + b, 0) / matchMinLogprobs.length;
                document.getElementById('conf-match-min-avg').textContent = matchMinAvg.toFixed(3);
            } else {
                document.getElementById('conf-match-min-avg').textContent = 'N/A';
            }
            
            // Calculate average min logprob for mismatches
            if (mismatches.length > 0) {
                const mismatchMinLogprobs = mismatches.map(r => r.confidence_min_logprob);
                const mismatchMinAvg = mismatchMinLogprobs.reduce((a, b) => a + b, 0) / mismatchMinLogprobs.length;
                document.getElementById('conf-mismatch-min-avg').textContent = mismatchMinAvg.toFixed(3);
            } else {
                document.getElementById('conf-mismatch-min-avg').textContent = 'N/A';
            }
            
            // Calculate average min logprob for false positives
            if (falsePositives.length > 0) {
                const fpMinLogprobs = falsePositives.map(r => r.confidence_min_logprob);
                const fpMinAvg = fpMinLogprobs.reduce((a, b) => a + b, 0) / fpMinLogprobs.length;
                document.getElementById('conf-fp-min-avg').textContent = fpMinAvg.toFixed(3);
            } else {
                document.getElementById('conf-fp-min-avg').textContent = 'N/A';
            }
        }
        
        function toggleNoteText(noteIdSafe) {
            const fullText = document.getElementById('note-text-full-' + noteIdSafe);
            const preview = document.getElementById('note-preview-' + noteIdSafe);
            const btn = document.getElementById('toggle-btn-' + noteIdSafe);
            
            if (!fullText || !preview || !btn) return;
            
            if (fullText.style.display === 'none') {
                fullText.style.display = 'block';
                preview.style.display = 'none';
                btn.textContent = 'Show Preview';
            } else {
                fullText.style.display = 'none';
                preview.style.display = 'block';
                btn.textContent = 'Show Full Text';
            }
        }
        
        function toggleFewshotNote(noteIdFewshot) {
            const fullText = document.getElementById('fewshot-note-full-' + noteIdFewshot);
            const preview = document.getElementById('fewshot-note-preview-' + noteIdFewshot);
            const btn = document.getElementById('fewshot-toggle-btn-' + noteIdFewshot);
            
            if (!fullText || !preview || !btn) return;
            
            if (fullText.style.display === 'none') {
                fullText.style.display = 'block';
                preview.style.display = 'none';
                btn.textContent = 'Show Preview';
            } else {
                fullText.style.display = 'none';
                preview.style.display = 'block';
                btn.textContent = 'Show Full Note';
            }
        }
        
        function renderResults(filteredResults) {
            const container = document.getElementById('results-container');
            container.innerHTML = '';
            
            // Calculate pagination
            totalPages = Math.ceil(filteredResults.length / pageSize);
            if (totalPages === 0) totalPages = 1;
            
            // Ensure currentPage is within valid range
            if (currentPage >= totalPages) {
                currentPage = Math.max(0, totalPages - 1);
            }
            
            // Calculate slice indices
            const startIndex = currentPage * pageSize;
            const endIndex = Math.min(startIndex + pageSize, filteredResults.length);
            const pageResults = filteredResults.slice(startIndex, endIndex);
            
            // Update pagination UI
            updatePaginationUI(filteredResults.length, startIndex, endIndex);
            
            // Render only current page results
            pageResults.forEach((result, index) => {
                // Use original index from filteredResults for unique IDs
                const originalIndex = startIndex + index;
                const card = document.createElement('div');
                
                // Check if this is a false positive
                const hasExpected = result.expected_annotation && 
                    result.expected_annotation.trim() !== '' && 
                    result.expected_annotation !== '[NO EXPECTED ANNOTATION]';
                const hasPredicted = result.predicted_annotation && 
                    result.predicted_annotation.trim() !== '' && 
                    result.predicted_annotation !== '[NO PREDICTION]';
                const isFalsePositive = !hasExpected && hasPredicted;
                
                // Determine card class and match text
                let matchClass, matchText;
                if (result.overall_match) {
                    matchClass = 'match';
                    matchText = '✓ Match';
                } else if (isFalsePositive) {
                    matchClass = 'false-positive';
                    matchText = '⚠ False Positive';
                } else {
                    matchClass = 'mismatch';
                    matchText = '✗ Mismatch';
                }
                
                card.className = 'result-card ' + matchClass;
                
                // Create unique ID for this note
                const noteId = 'note-' + (result.note_id || '') + '-' + (result.prompt_type || '') + '-' + originalIndex;
                const noteIdSafe = noteId.replace(/[^a-zA-Z0-9-]/g, '-');
                
                // Get full note text
                const noteText = result.note_text || result.note_text_preview || '[NO TEXT]';
                const noteTextEscaped = noteText.replace(/\\n/g, '<br>').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
                
                // Check if text is long enough to need truncation
                const isLongText = noteText.length > 200;
                const previewText = isLongText ? noteText.substring(0, 200) + '...' : noteText;
                const previewTextEscaped = previewText.replace(/\\n/g, '<br>').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
                
                card.innerHTML = `
                    <div class="result-header">
                        <div class="result-id">
                            Note: ${result.note_id || 'N/A'} | Patient: ${result.p_id || 'N/A'} | Prompt: ${result.prompt_type || 'N/A'}
                        </div>
                        <div class="match-badge ${matchClass}">${matchText}</div>
                    </div>
                    <div class="comparison-grid">
                        <div class="comparison-column expected">
                            <div class="column-label">Expected Annotation</div>
                            <div class="annotation-text">${(result.expected_annotation || '[NO EXPECTED ANNOTATION]').replace(/\\n/g, '<br>')}</div>
                        </div>
                        <div class="comparison-column predicted">
                            <div class="column-label">Predicted Annotation</div>
                            <div class="annotation-text">${(result.predicted_annotation || '[NO PREDICTION]').replace(/\\n/g, '<br>')}</div>
                        </div>
                        <div class="comparison-column original">
                            <div class="column-label">Original Note Text</div>
                            <div class="note-text-container">
                                <div class="note-text-full" id="note-text-full-${noteIdSafe}" style="display: ${isLongText ? 'none' : 'block'};">
                                    ${noteTextEscaped}
                                </div>
                                ${isLongText ? `
                                <div class="note-text-preview" id="note-preview-${noteIdSafe}" style="display: block;">
                                    ${previewTextEscaped}
                                </div>
                                <button class="toggle-note-text" onclick="toggleNoteText('${noteIdSafe}')" id="toggle-btn-${noteIdSafe}">
                                    Show Full Text
                                </button>
                                ` : ''}
                            </div>
                        </div>
                    </div>
                    <div class="metrics">
                        <div class="metric">Similarity: ${(result.similarity_score || 0).toFixed(3)}</div>
                        <div class="metric">Exact Match: ${result.exact_match ? 'Yes' : 'No'}</div>
                        <div class="metric">Processing Time: ${(result.processing_time_seconds || 0).toFixed(2)}s</div>
                        ${result.fewshots_used > 0 ? `<div class="metric">Few-shots: ${result.fewshots_used}</div>` : ''}
                        ${result.confidence_score !== null && result.confidence_score !== undefined ? `
                            <div class="metric" style="background-color: ${result.confidence_rejected ? '#ffebee' : '#e8f5e9'};">
                                Confidence: ${result.confidence_score.toFixed(3)}
                                ${result.confidence_rejected ? ' <span style="color: #c62828; font-weight: bold;">(REJECTED)</span>' : ''}
                            </div>
                        ` : ''}
                        ${result.confidence_avg_logprob !== null && result.confidence_avg_logprob !== undefined ? `
                            <div class="metric">Avg Logprob: ${result.confidence_avg_logprob.toFixed(3)}</div>
                        ` : ''}
                        ${result.confidence_min_logprob !== null && result.confidence_min_logprob !== undefined ? `
                            <div class="metric">Min Logprob: ${result.confidence_min_logprob.toFixed(3)}</div>
                        ` : ''}
                        ${result.confidence_max_logprob !== null && result.confidence_max_logprob !== undefined ? `
                            <div class="metric">Max Logprob: ${result.confidence_max_logprob.toFixed(3)}</div>
                        ` : ''}
                        ${result.confidence_token_count > 0 ? `
                            <div class="metric">Tokens: ${result.confidence_token_count}</div>
                        ` : ''}
                    </div>
                    ${result.confidence_rejected ? `
                    <div style="background-color: #ffebee; padding: 10px; border-radius: 3px; margin-top: 10px; border-left: 4px solid #c62828;">
                        <strong style="color: #c62828;">⚠ Prediction Rejected Due to Low Confidence</strong>
                        <div style="margin-top: 5px; font-size: 12px; color: #666;">
                            Confidence score: ${result.confidence_score !== null && result.confidence_score !== undefined ? result.confidence_score.toFixed(3) : 'N/A'}<br/>
                            ${result.original_llm_output ? `Original output: ${(result.original_llm_output || '').replace(/\\n/g, '<br>')}` : ''}
                        </div>
                    </div>
                    ` : ''}
                    ${result.fewshot_examples && result.fewshot_examples.length > 0 ? `
                    <div class="fewshot-section">
                        <div class="fewshot-header">Few-Shot Examples Used (${result.fewshot_examples.length})</div>
                        <div class="fewshot-container">
                            ${result.fewshot_examples.map((example, idx) => {
                                const noteText = (example.note || '').replace(/\\n/g, '<br>');
                                const annotationText = (example.annotation || '').replace(/\\n/g, '<br>');
                                const isLongNote = (example.note || '').length > 200;
                                const notePreview = isLongNote ? (example.note || '').substring(0, 200) + '...' : (example.note || '');
                                const notePreviewEscaped = notePreview.replace(/\\n/g, '<br>');
                                const noteIdFewshot = 'fewshot-note-' + noteIdSafe + '-' + idx;
                                
                                return `
                                <div class="fewshot-example">
                                    <div class="fewshot-example-label">Example ${idx + 1}:</div>
                                    <div class="fewshot-note">
                                        <strong>Medical Note:</strong><br/>
                                        <div class="note-text-full" id="fewshot-note-full-${noteIdFewshot}" style="display: ${isLongNote ? 'none' : 'block'};">
                                            ${noteText}
                                        </div>
                                        ${isLongNote ? `
                                        <div class="note-text-preview" id="fewshot-note-preview-${noteIdFewshot}" style="display: block;">
                                            ${notePreviewEscaped}
                                        </div>
                                        <button class="fewshot-toggle" onclick="toggleFewshotNote('${noteIdFewshot}')" id="fewshot-toggle-btn-${noteIdFewshot}">
                                            Show Full Note
                                        </button>
                                        ` : ''}
                                    </div>
                                    <div class="fewshot-annotation">
                                        <strong>Annotation:</strong><br/>
                                        ${annotationText}
                                    </div>
                                </div>
                                `;
                            }).join('')}
                        </div>
                    </div>
                    ` : ''}
                `;
                
                container.appendChild(card);
            });
            
            updateStats(filteredResults);
        }
        
        function filterResults() {
            const searchTerm = document.getElementById('search-input').value.toLowerCase();
            const matchFilter = document.getElementById('match-filter').value;
            const promptFilter = document.getElementById('prompt-filter').value;
            
            // Reset to page 1 when filters change (unless this is initial load)
            const wasFiltered = document.getElementById('results-container').children.length > 0;
            if (wasFiltered) {
                currentPage = 0;
            }
            
            let filtered = results.filter(r => {
                const matchesSearch = !searchTerm || 
                    (r.note_id && r.note_id.toString().toLowerCase().includes(searchTerm)) ||
                    (r.p_id && r.p_id.toString().toLowerCase().includes(searchTerm)) ||
                    (r.prompt_type && r.prompt_type.toLowerCase().includes(searchTerm));
                
                // Check if this is a false positive
                const rHasExpected = r.expected_annotation && 
                    r.expected_annotation.trim() !== '' && 
                    r.expected_annotation !== '[NO EXPECTED ANNOTATION]';
                const rHasPredicted = r.predicted_annotation && 
                    r.predicted_annotation.trim() !== '' && 
                    r.predicted_annotation !== '[NO PREDICTION]';
                const rIsFalsePositive = !rHasExpected && rHasPredicted;
                
                const matchesMatchFilter = matchFilter === 'all' ||
                    (matchFilter === 'match' && r.overall_match) ||
                    (matchFilter === 'mismatch' && !r.overall_match && !rIsFalsePositive) ||
                    (matchFilter === 'false-positive' && rIsFalsePositive);
                
                const matchesPromptFilter = promptFilter === 'all' || r.prompt_type === promptFilter;
                
                return matchesSearch && matchesMatchFilter && matchesPromptFilter;
            });
            
            renderResults(filtered);
        }
        
        function updatePaginationUI(totalResults, startIndex, endIndex) {
            const paginationControls = document.getElementById('pagination-controls');
            const resultsInfo = document.getElementById('results-info');
            const prevBtn = document.getElementById('pagination-prev');
            const nextBtn = document.getElementById('pagination-next');
            const pagesContainer = document.getElementById('pagination-pages');
            const jumpToPageInput = document.getElementById('jump-to-page');
            
            // Show/hide pagination controls
            if (totalResults === 0) {
                paginationControls.style.display = 'none';
                return;
            }
            paginationControls.style.display = 'block';
            
            // Update results info
            resultsInfo.textContent = `Showing ${startIndex + 1}-${endIndex} of ${totalResults} results`;
            
            // Update prev/next buttons
            prevBtn.disabled = currentPage === 0;
            nextBtn.disabled = currentPage >= totalPages - 1;
            
            // Update jump to page input
            jumpToPageInput.value = currentPage + 1;
            jumpToPageInput.max = totalPages;
            
            // Generate page number buttons (show max 10 pages)
            pagesContainer.innerHTML = '';
            const maxPageButtons = 10;
            let startPage = Math.max(0, currentPage - Math.floor(maxPageButtons / 2));
            let endPage = Math.min(totalPages - 1, startPage + maxPageButtons - 1);
            
            // Adjust if we're near the end
            if (endPage - startPage < maxPageButtons - 1) {
                startPage = Math.max(0, endPage - maxPageButtons + 1);
            }
            
            // Add first page button if not visible
            if (startPage > 0) {
                const firstBtn = document.createElement('button');
                firstBtn.textContent = '1';
                firstBtn.style.padding = '5px 10px';
                firstBtn.style.border = '1px solid #ddd';
                firstBtn.style.borderRadius = '3px';
                firstBtn.style.backgroundColor = '#ecf0f1';
                firstBtn.style.cursor = 'pointer';
                firstBtn.onclick = () => goToPage(0);
                pagesContainer.appendChild(firstBtn);
                
                if (startPage > 1) {
                    const ellipsis = document.createElement('span');
                    ellipsis.textContent = '...';
                    ellipsis.style.padding = '0 5px';
                    pagesContainer.appendChild(ellipsis);
                }
            }
            
            // Add page number buttons
            for (let i = startPage; i <= endPage; i++) {
                const pageBtn = document.createElement('button');
                pageBtn.textContent = (i + 1).toString();
                pageBtn.style.padding = '5px 10px';
                pageBtn.style.border = '1px solid #ddd';
                pageBtn.style.borderRadius = '3px';
                pageBtn.style.cursor = 'pointer';
                
                if (i === currentPage) {
                    pageBtn.style.backgroundColor = '#3498db';
                    pageBtn.style.color = 'white';
                    pageBtn.style.fontWeight = 'bold';
                } else {
                    pageBtn.style.backgroundColor = '#ecf0f1';
                }
                
                pageBtn.onclick = () => goToPage(i);
                pagesContainer.appendChild(pageBtn);
            }
            
            // Add last page button if not visible
            if (endPage < totalPages - 1) {
                if (endPage < totalPages - 2) {
                    const ellipsis = document.createElement('span');
                    ellipsis.textContent = '...';
                    ellipsis.style.padding = '0 5px';
                    pagesContainer.appendChild(ellipsis);
                }
                
                const lastBtn = document.createElement('button');
                lastBtn.textContent = totalPages.toString();
                lastBtn.style.padding = '5px 10px';
                lastBtn.style.border = '1px solid #ddd';
                lastBtn.style.borderRadius = '3px';
                lastBtn.style.backgroundColor = '#ecf0f1';
                lastBtn.style.cursor = 'pointer';
                lastBtn.onclick = () => goToPage(totalPages - 1);
                pagesContainer.appendChild(lastBtn);
            }
        }
        
        function goToPage(page) {
            if (page >= 0 && page < totalPages) {
                currentPage = page;
                // Re-filter and re-render
                filterResults();
            }
        }
        
        document.getElementById('search-input').addEventListener('input', filterResults);
        document.getElementById('match-filter').addEventListener('change', filterResults);
        document.getElementById('prompt-filter').addEventListener('change', filterResults);
        
        // Pagination event handlers
        document.getElementById('pagination-prev').addEventListener('click', () => {
            if (currentPage > 0) {
                currentPage--;
                filterResults();
            }
        });
        
        document.getElementById('pagination-next').addEventListener('click', () => {
            if (currentPage < totalPages - 1) {
                currentPage++;
                filterResults();
            }
        });
        
        document.getElementById('page-size-select').addEventListener('change', (e) => {
            pageSize = parseInt(e.target.value);
            currentPage = 0; // Reset to first page
            filterResults();
        });
        
        document.getElementById('jump-to-page-btn').addEventListener('click', () => {
            const jumpInput = document.getElementById('jump-to-page');
            const targetPage = parseInt(jumpInput.value) - 1; // Convert to 0-based
            if (targetPage >= 0 && targetPage < totalPages) {
                goToPage(targetPage);
            } else {
                alert(`Please enter a page number between 1 and ${totalPages}`);
            }
        });
        
        document.getElementById('jump-to-page').addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                document.getElementById('jump-to-page-btn').click();
            }
        });
        
        // Initial render
        renderResults(results);
    </script>
</body>
</html>"""
    
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html_content)


def load_confidence_config(config_path: str | Path | None) -> Dict:
    """
    Load confidence threshold configuration from JSON file.
    
    Args:
        config_path: Path to confidence_config.json, or None to use defaults
    
    Returns:
        Dictionary with confidence configuration
    """
    default_config = {
        "enabled": False,
        "default_threshold": -2.0,
        "prompt_type_thresholds": {},
        "logprobs_mode": "raw_logprobs"
    }
    
    if config_path is None:
        return default_config
    
    config_path = Path(config_path)
    
    if not config_path.exists():
        print(f"[WARN] Confidence config file not found: {config_path}")
        print(f"[WARN] Using default threshold: {default_config['default_threshold']}")
        return default_config
    
    print(f"[INFO] Loading confidence config from: {config_path}")
    
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        # Merge with defaults
        default_config.update(config)
        print(f"[INFO] Loaded confidence config: default_threshold={default_config['default_threshold']}, "
              f"{len(default_config.get('prompt_type_thresholds', {}))} prompt-specific thresholds")
        return default_config
    except Exception as e:
        print(f"[WARN] Failed to load confidence config: {e}, using defaults")
        return default_config


def load_report_type_prompt_mapping(mapping_json_path: str | Path | None) -> Dict[str, List[str]]:
    """
    Load report type to prompt type mapping from JSON file.
    
    Args:
        mapping_json_path: Path to report_type_prompt_mapping.json, or None to disable filtering
    
    Returns:
        Dictionary mapping report_type -> list of prompt types (empty dict if not provided or not found)
    """
    script_dir = Path(__file__).resolve().parent
    
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


def main(
    notes_csv_path: str | Path = None,
    mapping_csv_path: str | Path = None,  # Deprecated: kept for backward compatibility, not used
    json_file_path: str | Path = None,
    prompts_json_path: str | Path = None,
    model_path: str | Path = None,
    faiss_store_dir: str | Path = "faiss_store",
    fewshot_k: int = 5,
    use_fewshots: bool = True,
    force_rebuild_faiss: bool = False,
    report_type_mapping_path: str | Path = None,  # Path to report_type_prompt_mapping.json
    use_confidence_threshold: bool = False,  # Enable confidence-based filtering
    confidence_threshold: float = -2.0,  # Logprob threshold (lower = more strict)
    confidence_config_path: str | Path = None  # Path to confidence_config.json for per-prompt thresholds
):
    """
    Main evaluation pipeline.
    
    Args:
        notes_csv_path: Path to first_patient_notes.csv
        mapping_csv_path: DEPRECATED - kept for backward compatibility but not used. 
                         Annotations are now loaded from json_file_path instead.
        json_file_path: Path to annotated_patient_notes_with_spans_full_verified.json 
                       (used for both few-shot examples and gold annotations)
        prompts_json_path: Path to FBK_scripts/prompts.json
        model_path: Path to LLM model file
        faiss_store_dir: Directory for FAISS indexes
        fewshot_k: Number of fewshot examples to retrieve (ignored if use_fewshots=False)
        use_fewshots: If False, run without few-shot examples (zero-shot mode)
        force_rebuild_faiss: Force rebuild FAISS indexes even if they exist
        report_type_mapping_path: Path to report_type_prompt_mapping.json. If None, uses default.
                                  If mapping is provided, only runs prompts relevant to each note's report_type.
        use_confidence_threshold: If True, use logprobs to filter low-confidence predictions (VLLM only)
        confidence_threshold: Logprob threshold for rejecting predictions (default: -2.0)
        confidence_config_path: Path to confidence_config.json with per-prompt-type thresholds
    """
    script_dir = Path(__file__).resolve().parent
    
    # Set default paths
    if notes_csv_path is None:
        notes_csv_path = script_dir / "first_patient_notes.csv"
    if json_file_path is None:
        # Default to the new file with spans for better few-shot examples and gold annotations
        json_file_path = script_dir / "annotated_patient_notes_with_spans_full_verified.json"
        # Fallback to original file if new one doesn't exist
        if not Path(json_file_path).exists():
            json_file_path = script_dir / "annotated_patient_notes.json"
    if prompts_json_path is None:
        prompts_json_path = script_dir / "FBK_scripts" / "prompts.json"
    if model_path is None:
        model_path = script_dir / "meta-llama-3.1-8b-instruct-q4_k_m.gguf"
    
    notes_csv_path = Path(notes_csv_path)
    json_file_path = Path(json_file_path)
    prompts_json_path = Path(prompts_json_path)
    model_path = Path(model_path)
    
    # Load report type to prompt mapping (if provided)
    report_type_mapping = load_report_type_prompt_mapping(report_type_mapping_path)
    use_report_type_filtering = len(report_type_mapping) > 0
    
    # Load confidence configuration (if provided)
    confidence_config = load_confidence_config(confidence_config_path)
    use_confidence = use_confidence_threshold and confidence_config.get("enabled", True)
    default_confidence_threshold = confidence_config.get("default_threshold", confidence_threshold)
    prompt_type_thresholds = confidence_config.get("prompt_type_thresholds", {})
    
    print("=" * 80)
    print("LLM Evaluation Pipeline for INT Prompts")
    print("=" * 80)
    if use_fewshots:
        print(f"Mode: Few-shot (k={fewshot_k})")
    else:
        print("Mode: Zero-shot (no few-shot examples)")
    if use_report_type_filtering:
        print(f"Report type filtering: ENABLED ({len(report_type_mapping)} report types mapped)")
    else:
        print("Report type filtering: DISABLED (running all prompts for all notes)")
    if use_confidence:
        print(f"Confidence thresholding: ENABLED (default threshold: {default_confidence_threshold})")
        if prompt_type_thresholds:
            print(f"  Using {len(prompt_type_thresholds)} prompt-specific thresholds")
    else:
        print("Confidence thresholding: DISABLED")
    print("=" * 80)
    
    # Start overall timer
    overall_start_time = time.time()
    
    # Step 1: Load data
    step_start = time.time()
    print("\n[STEP 1] Loading data...")
    print(f"  Loading notes from: {notes_csv_path}")
    notes_df = pd.read_csv(notes_csv_path, delimiter=';', encoding='utf-8')
    print(f"  Loaded {len(notes_df)} notes")
    
    print(f"  Loading expected annotations from JSON: {json_file_path}")
    annotations_lookup = load_annotations_from_json(json_file_path)
    print(f"  Loaded annotations for {len(annotations_lookup)} notes")
    step_duration = time.time() - step_start
    print(f"  [Time: {step_duration:.2f}s]")
    
    # Step 2: Adapt and load prompts
    step_start = time.time()
    print("\n[STEP 2] Adapting prompts...")
    load_adapted_prompts(prompts_json_path)
    step_duration = time.time() - step_start
    print(f"  [Time: {step_duration:.2f}s]")
    
    # Step 3: Initialize FAISS builder (with GPU for embeddings) - skip if not using fewshots
    builder = None
    if use_fewshots:
        step_start = time.time()
        print("\n[STEP 3] Setting up FAISS indexes for few-shot examples...")
        builder = FewshotBuilder(store_dir=faiss_store_dir, use_gpu=True)
        
        # Get prompt types for preloading
        prompt_types = list(mr._PROMPTS.keys())
        
        # Build indexes if needed
        if force_rebuild_faiss or not (Path(faiss_store_dir) / "gender-int.index").exists():
            print("  Building FAISS indexes from patients 2-3...")
            builder.build_all_int_prompts(
                json_file_path,
                prompts_json_path,
                patient_indices=[8, 9], # last two indices
                force_rebuild=force_rebuild_faiss
            )
        else:
            print("  FAISS indexes already exist, preloading into memory...")
            # Preload all indexes for faster retrieval
            builder.preload_all_indexes(prompt_types)
        step_duration = time.time() - step_start
        print(f"  [Time: {step_duration:.2f}s]")
    else:
        print("\n[STEP 3] Skipping FAISS setup (running in zero-shot mode without few-shot examples)")
        prompt_types = list(mr._PROMPTS.keys())
    
    # Step 4: Initialize model (ensure GPU usage with larger context)
    step_start = time.time()
    print("\n[STEP 4] Initializing LLM model...")
    print(f"  Model path: {model_path}")
    if not model_path.exists():
        print(f"[ERROR] Model file not found: {model_path}")
        sys.exit(1)
    
    # Force GPU usage by setting environment variable if not set
    import os
    if 'LLAMA_N_GPU_LAYERS' not in os.environ:
        os.environ['LLAMA_N_GPU_LAYERS'] = '-1'  # Use all layers on GPU
        print("  [INFO] Setting LLAMA_N_GPU_LAYERS=-1 for maximum GPU usage")
    
    # Initialize with larger context window to use more VRAM
    # Note: llama.cpp doesn't support true batch inference (multiple prompts in parallel)
    # Each prompt is processed sequentially. To maximize VRAM usage:
    # - Increased n_ctx from 4096 to 8192 (larger context window = more VRAM)
    # - Increased n_batch from 512 to 1024 (more efficient prompt processing)
    # - Added n_ubatch=512 and flash_attn=True for better memory efficiency
    print("  [INFO] Using optimized settings: n_ctx=8192, n_batch=1024, flash_attn=True")
    print("  [INFO] Note: Processing is sequential (one prompt at a time), not batched")
    init_model(str(model_path), n_ctx=8192)  # Increased from 4096 to 8192
    print("  Model initialized successfully")
    
    # Verify GPU usage (check after model load)
    try:
        import pynvml
        pynvml.nvmlInit()
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        mem_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
        util = pynvml.nvmlDeviceGetUtilizationRates(handle)
        print(f"  GPU memory usage: {mem_info.used / (1024**3):.2f}GB / {mem_info.total / (1024**3):.2f}GB")
        print(f"  GPU utilization: {util.gpu}% (compute), {util.memory}% (memory)")
        
        # Check for active processes
        procs = pynvml.nvmlDeviceGetComputeRunningProcesses(handle)
        if procs:
            print(f"  Active GPU processes: {len(procs)}")
            for proc in procs:
                print(f"    PID {proc.pid}: {proc.usedGpuMemory / (1024**3):.2f}GB")
        else:
            print(f"  Note: llama.cpp may use GPU but not show as process (CUDA context)")
            print(f"  GPU memory will be used during inference")
        pynvml.nvmlShutdown()
    except ImportError:
        print("  [INFO] pynvml not available for detailed GPU monitoring")
    except Exception as e:
        print(f"  [WARN] Could not check GPU status: {e}")
    
    step_duration = time.time() - step_start
    print(f"  [Time: {step_duration:.2f}s]")
    
    # Step 5: Run LLM inference and evaluation
    step_start = time.time()
    print("\n[STEP 5] Running LLM inference and evaluation...")
    print("  This may take a while...")
    
    results = []
    # Calculate total combinations (accounting for report type filtering)
    if use_report_type_filtering:
        total_combinations = 0
        for _, note_row in notes_df.iterrows():
            report_type = note_row['report_type']
            allowed_prompts = report_type_mapping.get(report_type, prompt_types)
            total_combinations += len(allowed_prompts)
    else:
        total_combinations = len(notes_df) * len(prompt_types)
    
    current = 0
    note_timings = []  # Track timing per note
    
    # Optimize: Reduce max_new_tokens for faster inference (most annotations are short)
    max_new_tokens = 128  # Reduced from 256 for speed
    
    for _, note_row in notes_df.iterrows():
        note_start_time = time.time()
        note_id = note_row['note_id']
        note_text = note_row['text']
        note_date = note_row['date']
        p_id = note_row['p_id']
        report_type = note_row['report_type']
        
        print(f"\n  Processing note: {note_id} ({report_type})")
        
        # Filter prompts based on report_type if mapping is provided
        if use_report_type_filtering:
            allowed_prompts = report_type_mapping.get(report_type, prompt_types)
            if len(allowed_prompts) < len(prompt_types):
                print(f"    Filtered prompts: {len(allowed_prompts)}/{len(prompt_types)} prompts relevant to {report_type}")
        else:
            allowed_prompts = prompt_types
        
        prompt_timings = []  # Track timing per prompt for this note
        
        for prompt_type in allowed_prompts:
            current += 1
            prompt_start_time = time.time()
            
            # Get expected annotation from JSON lookup
            expected_annotation = get_expected_annotation_from_json(
                annotations_lookup,
                note_id,
                prompt_type
            )
            
            print(f"    [{current}/{total_combinations}] {prompt_type}", end=" ... ", flush=True)
            
            try:
                # Get fewshot examples (or use empty list if disabled)
                if use_fewshots and builder is not None:
                    fewshot_examples = builder.get_fewshot_examples(
                        prompt_type,
                        note_text,
                        k=fewshot_k
                    )
                else:
                    fewshot_examples = []  # Zero-shot mode
                
                # Build prompt using model_runner's get_prompt
                prompt = get_prompt(
                    task_key=prompt_type,
                    fewshots=fewshot_examples,
                    note_text=note_text
                )
                
                # Print the full prompt
                print(f"\n    Prompt ({len(prompt)} chars):")
                print(f"    {'-' * 70}")
                # Truncate very long prompts for readability, but show substantial portion
                prompt_display = prompt
                if len(prompt_display) > 800:
                    prompt_display = prompt_display[:800] + f"\n    ... [truncated {len(prompt) - 800} more characters] ..."
                # Indent each line for readability
                prompt_lines = prompt_display.split('\n')
                for line in prompt_lines:
                    print(f"    {line}")
                print(f"    {'-' * 70}")
                
                # Run LLM (optimized for speed)
                # Request logprobs if confidence thresholding is enabled
                return_logprobs = use_confidence
                output = run_model_with_prompt(
                    prompt=prompt,
                    max_new_tokens=max_new_tokens,  # Reduced for speed
                    temperature=0.1,
                    return_logprobs=return_logprobs
                )
                
                llm_output = output["normalized"]
                raw_output = output["raw"]
                logprobs_data = output.get("logprobs")
                
                # Clean annotation: remove "Annotation: " prefix if present
                import re
                # Ensure llm_output is a string
                if llm_output is None:
                    llm_output = ""
                elif not isinstance(llm_output, str):
                    llm_output = str(llm_output)
                
                if llm_output:
                    llm_output = re.sub(
                        r'^\s*annotation\s*:\s*', '', llm_output, flags=re.IGNORECASE).strip()
                
                # Confidence analysis and thresholding (VLLM only)
                confidence_score = None
                confidence_rejected = False
                confidence_metrics = None
                original_llm_output = llm_output  # Keep original for comparison
                
                if use_confidence and logprobs_data is not None:
                    # Calculate confidence from logprobs
                    confidence_score = calculate_confidence_from_logprobs(
                        logprobs_data, 
                        prompt_type=prompt_type,
                        method="average"
                    )
                    
                    # Get confidence metrics
                    confidence_metrics = get_confidence_metrics(logprobs_data)
                    
                    # Get threshold for this prompt type (or use default)
                    threshold = prompt_type_thresholds.get(prompt_type, default_confidence_threshold)
                    
                    # Check if should reject based on confidence
                    if confidence_score is not None:
                        confidence_rejected = should_reject_as_no_outcome(
                            confidence_score,
                            threshold,
                            prompt_type=prompt_type,
                            use_normalized=False
                        )
                        
                        # Also check for placeholder patterns in output
                        has_placeholders = analyze_output_for_placeholders(llm_output)
                        
                        # Reject if confidence is low AND output has placeholders/unknown patterns
                        if confidence_rejected and has_placeholders:
                            llm_output = ""  # Convert to empty string (no outcome)
                            print(f"    [CONFIDENCE] Rejected prediction (confidence: {confidence_score:.3f} < threshold: {threshold:.3f})")
                        elif confidence_rejected:
                            # Low confidence but no placeholders - log but don't reject
                            print(f"    [CONFIDENCE] Low confidence ({confidence_score:.3f}) but no placeholders, keeping prediction")
                            confidence_rejected = False
                elif use_confidence and logprobs_data is None:
                    # Confidence requested but not available (llama.cpp fallback)
                    print(f"    [CONFIDENCE] Logprobs not available (using llama.cpp), skipping confidence analysis")
                    # Debug: log when logprobs are expected but missing
                    print(f"    [DEBUG] Confidence enabled but logprobs_data is None for prompt_type={prompt_type}")
                
                # Evaluate
                evaluation = evaluate_annotation(
                    expected=expected_annotation,
                    predicted=llm_output,
                    note_id=note_id,
                    prompt_type=prompt_type
                )
                
                # Add additional metadata
                evaluation['note_date'] = note_date
                evaluation['p_id'] = p_id
                evaluation['report_type'] = report_type
                evaluation['raw_output'] = raw_output
                evaluation['fewshots_used'] = len(fewshot_examples)
                # Store few-shot examples as list of dicts for JSON serialization
                evaluation['fewshot_examples'] = [
                    {'note': note, 'annotation': annotation}
                    for note, annotation in fewshot_examples
                ]
                evaluation['note_text'] = note_text  # Include full note text for comparison
                evaluation['note_text_preview'] = note_text[:200] + '...' if len(note_text) > 200 else note_text  # Preview for CSV
                evaluation['expected_annotation'] = expected_annotation  # Already in evaluation but making explicit
                evaluation['llm_output'] = llm_output  # Explicit LLM output (same as predicted_annotation but clearer naming)
                evaluation['original_llm_output'] = original_llm_output  # Original output before confidence filtering
                
                # Add confidence metrics
                evaluation['confidence_score'] = round(confidence_score, 4) if confidence_score is not None else None
                evaluation['confidence_rejected'] = confidence_rejected
                if confidence_metrics:
                    evaluation['confidence_min_logprob'] = round(confidence_metrics.get('min_logprob', 0), 4) if confidence_metrics.get('min_logprob') is not None else None
                    evaluation['confidence_max_logprob'] = round(confidence_metrics.get('max_logprob', 0), 4) if confidence_metrics.get('max_logprob') is not None else None
                    evaluation['confidence_avg_logprob'] = round(confidence_metrics.get('avg_logprob', 0), 4) if confidence_metrics.get('avg_logprob') is not None else None
                    evaluation['confidence_token_count'] = confidence_metrics.get('count', 0)
                else:
                    evaluation['confidence_min_logprob'] = None
                    evaluation['confidence_max_logprob'] = None
                    evaluation['confidence_avg_logprob'] = None
                    evaluation['confidence_token_count'] = 0
                
                # Add timing
                prompt_duration = time.time() - prompt_start_time
                evaluation['processing_time_seconds'] = round(prompt_duration, 3)
                prompt_timings.append(prompt_duration)
                
                # Add match indicator for CSV
                evaluation['match_indicator'] = '✓' if evaluation['overall_match'] else '✗'
                
                results.append(evaluation)
                
                # Print status with annotations
                match_status = "✓ Match" if evaluation['overall_match'] else "✗ Mismatch"
                print(f"{match_status} (sim: {evaluation['similarity_score']:.2f}, {prompt_duration:.2f}s)")
                
                # Print expected and predicted annotations
                expected_display = expected_annotation if expected_annotation else "[NO EXPECTED ANNOTATION]"
                predicted_display = llm_output if llm_output else "[NO PREDICTION]"
                
                # Truncate long annotations for readability (show first 150 chars)
                max_display_len = 150
                if len(expected_display) > max_display_len:
                    expected_display = expected_display[:max_display_len] + "..."
                if len(predicted_display) > max_display_len:
                    predicted_display = predicted_display[:max_display_len] + "..."
                
                print(f"  Expected:  {expected_display}")
                print(f"  Predicted: {predicted_display}")
                
            except Exception as e:
                prompt_duration = time.time() - prompt_start_time
                print(f"✗ ERROR: {e} ({prompt_duration:.2f}s)")
                # Add error result - ensure all values are strings
                error_expected = str(expected_annotation) if expected_annotation else ""
                results.append({
                    'note_id': str(note_id) if note_id else "",
                    'prompt_type': str(prompt_type) if prompt_type else "",
                    'exact_match': False,
                    'similarity_score': 0.0,
                    'error': str(e),
                    'expected_annotation': error_expected,
                    'predicted_annotation': '',
                    'llm_output': '',
                    'raw_output': '',
                    'overall_match': False,
                    'processing_time_seconds': round(prompt_duration, 3),
                    'note_text': str(note_text) if note_text else "",
                    'note_text_preview': (str(note_text)[:200] + '...') if note_text and len(str(note_text)) > 200 else (str(note_text) if note_text else ""),
                    'note_date': str(note_date) if note_date else "",
                    'p_id': str(p_id) if p_id else "",
                    'report_type': str(report_type) if report_type else "",
                    'fewshots_used': 0,
                    'fewshot_examples': [],
                    'expected_annotation': error_expected,
                    'predicted_annotation': '',
                    'llm_output': '',
                    'raw_output': '',
                    'original_llm_output': '',
                    'confidence_score': None,
                    'confidence_rejected': False,
                    'confidence_min_logprob': None,
                    'confidence_max_logprob': None,
                    'confidence_avg_logprob': None,
                    'confidence_token_count': 0
                })
                prompt_timings.append(prompt_duration)
        
        # Record note-level timing
        note_duration = time.time() - note_start_time
        num_prompts_for_note = len(allowed_prompts)
        note_timings.append({
            'note_id': note_id,
            'total_time_seconds': round(note_duration, 2),
            'num_prompts': num_prompts_for_note,
            'avg_time_per_prompt_seconds': round(note_duration / num_prompts_for_note, 3) if num_prompts_for_note > 0 else 0,
            'prompt_timings': prompt_timings
        })
        print(f"  Note {note_id} completed in {note_duration:.2f}s (avg {note_duration/num_prompts_for_note:.3f}s per prompt)")
    
    step_duration = time.time() - step_start
    print(f"\n  [STEP 5 completed in {step_duration:.2f}s]")
    
    # Step 6: Generate reports
    step_start = time.time()
    print("\n[STEP 6] Generating evaluation reports...")
    
    results_df = pd.DataFrame(results)
    
    # Detailed CSV with note text and annotations for comparison
    detailed_csv_path = script_dir / "llm_evaluation_detailed.csv"
    # Convert value_details to JSON string for CSV
    results_df_csv = results_df.copy()
    if 'value_details' in results_df_csv.columns:
        results_df_csv['value_details'] = results_df_csv['value_details'].apply(
            lambda x: json.dumps(x) if isinstance(x, (list, dict)) else x
        )
    
    # Ensure columns are in a logical order for comparison
    column_order = [
        'match_indicator',  # Visual indicator first
        'note_id', 'p_id', 'note_date', 'report_type', 'prompt_type',
        'note_text_preview', 'note_text',  # Note text (preview + full)
        'expected_annotation', 'predicted_annotation', 'llm_output', 'original_llm_output', 'raw_output',  # Annotations for comparison
        'exact_match', 'similarity_score', 'overall_match',  # Match results
        'total_values', 'values_matched', 'value_match_rate', 'value_details',  # Value-level details
        'confidence_score', 'confidence_rejected', 'confidence_avg_logprob', 'confidence_min_logprob', 'confidence_max_logprob', 'confidence_token_count',  # Confidence metrics
        'processing_time_seconds', 'fewshots_used'  # Metadata
    ]
    # Add any remaining columns not in the order list
    existing_cols = list(results_df_csv.columns)
    for col in existing_cols:
        if col not in column_order:
            column_order.append(col)
    # Reorder columns (only include columns that exist)
    results_df_csv = results_df_csv[[col for col in column_order if col in results_df_csv.columns]]
    
    results_df_csv.to_csv(detailed_csv_path, index=False, encoding='utf-8', sep=';')
    print(f"  Detailed results saved to: {detailed_csv_path}")
    print(f"    Includes note text and annotations for easy comparison")
    
    # Generate HTML comparison report
    html_report_path = script_dir / "llm_evaluation_comparison.html"
    generate_html_report(results_df_csv, html_report_path)
    print(f"  HTML comparison report saved to: {html_report_path}")
    
    # Summary CSV (per prompt type)
    summary_rows = []
    for prompt_type in prompt_types:
        prompt_results = results_df[results_df['prompt_type'] == prompt_type]
        if len(prompt_results) > 0:
            summary = batch_evaluate(prompt_results.to_dict('records'))
            summary['prompt_type'] = prompt_type
            summary_rows.append(summary)
    
    summary_df = pd.DataFrame(summary_rows)
    summary_csv_path = script_dir / "llm_evaluation_summary.csv"
    summary_df.to_csv(summary_csv_path, index=False, encoding='utf-8')
    print(f"  Summary saved to: {summary_csv_path}")
    
    step_duration = time.time() - step_start
    print(f"  [Time: {step_duration:.2f}s]")
    
    # Calculate timing statistics
    overall_duration = time.time() - overall_start_time
    processing_times = [r.get('processing_time_seconds', 0) for r in results if 'processing_time_seconds' in r]
    avg_processing_time = sum(processing_times) / len(processing_times) if processing_times else 0
    
    # JSON report
    overall_stats = batch_evaluate(results)
    
    # Calculate confidence statistics
    confidence_scores = [r.get('confidence_score') for r in results if r.get('confidence_score') is not None]
    confidence_rejected_count = sum(1 for r in results if r.get('confidence_rejected', False))
    confidence_stats = None
    if confidence_scores:
        confidence_stats = {
            'total_with_confidence': len(confidence_scores),
            'average_confidence': round(sum(confidence_scores) / len(confidence_scores), 4),
            'min_confidence': round(min(confidence_scores), 4),
            'max_confidence': round(max(confidence_scores), 4),
            'rejected_count': confidence_rejected_count,
            'rejection_rate': round(confidence_rejected_count / len(confidence_scores), 4) if confidence_scores else 0.0
        }
    
    json_report = {
        'overall_statistics': overall_stats,
        'timing_statistics': {
            'total_time_seconds': round(overall_duration, 2),
            'total_time_formatted': str(timedelta(seconds=int(overall_duration))),
            'average_time_per_evaluation_seconds': round(avg_processing_time, 3),
            'total_evaluations': len(results),
            'total_notes': len(notes_df),
            'notes_timings': note_timings
        },
        'per_prompt_type': {
            row['prompt_type']: {k: v for k, v in row.items() if k != 'prompt_type'}
            for row in summary_rows
        },
        'confidence_statistics': confidence_stats,
        'confidence_config': {
            'enabled': use_confidence,
            'default_threshold': default_confidence_threshold,
            'prompt_type_thresholds': prompt_type_thresholds
        } if use_confidence else None,
        'total_evaluations': len(results),
        'total_notes': len(notes_df),
        'total_prompt_types': len(prompt_types)
    }
    
    json_report_path = script_dir / "llm_evaluation_report.json"
    with open(json_report_path, 'w', encoding='utf-8') as f:
        json.dump(json_report, f, indent=2, ensure_ascii=False)
    print(f"  JSON report saved to: {json_report_path}")
    
    # Generate date evaluation report
    print("\n[STEP 7] Evaluating date extraction...")
    date_start = time.time()
    date_df, date_stats = evaluate_dates(results_df)
    
    # Save date evaluation CSV
    date_csv_path = script_dir / "llm_evaluation_dates.csv"
    date_df.to_csv(date_csv_path, index=False, encoding='utf-8', sep=';')
    print(f"  Date evaluation CSV saved to: {date_csv_path}")
    
    # Generate HTML report for date evaluation (only for rows with expected dates)
    date_html_path = script_dir / "llm_evaluation_dates_comparison.html"
    # Filter to only show rows where dates were expected
    date_df_with_dates = date_df[date_df['expected_count'] > 0].copy()
    generate_date_html_report(date_df_with_dates, date_stats, date_html_path)
    print(f"  Date evaluation HTML report saved to: {date_html_path}")
    print(f"    Showing {len(date_df_with_dates)} evaluations with expected dates (out of {len(date_df)} total)")
    
    # Add date statistics to JSON report
    json_report['date_evaluation'] = date_stats
    with open(json_report_path, 'w', encoding='utf-8') as f:
        json.dump(json_report, f, indent=2, ensure_ascii=False)
    
    date_duration = time.time() - date_start
    print(f"  [Time: {date_duration:.2f}s]")
    print(f"  Date accuracy: {date_stats['overall_date_accuracy']*100:.1f}% ({date_stats['rows_with_exact_match']}/{date_stats['rows_with_expected_dates']} rows with dates matched)")
    
    # Print summary
    print("\n" + "=" * 80)
    print("EVALUATION SUMMARY")
    print("=" * 80)
    print(f"Total evaluations: {overall_stats['total']}")
    print(f"Exact matches: {overall_stats['exact_matches']} ({overall_stats['exact_match_rate']*100:.1f}%)")
    print(f"High similarity (≥0.8): {overall_stats['high_similarity_matches']} ({overall_stats['high_similarity_rate']*100:.1f}%)")
    print(f"Overall matches: {overall_stats['overall_matches']} ({overall_stats['overall_match_rate']*100:.1f}%)")
    print(f"Average similarity: {overall_stats['avg_similarity']:.3f}")
    if overall_stats['avg_value_match_rate'] is not None:
        print(f"Average value match rate: {overall_stats['avg_value_match_rate']*100:.1f}%")
    if confidence_stats:
        print("\n" + "-" * 80)
        print("CONFIDENCE SUMMARY")
        print("-" * 80)
        print(f"Evaluations with confidence data: {confidence_stats['total_with_confidence']}")
        print(f"Average confidence (logprob): {confidence_stats['average_confidence']:.3f}")
        print(f"Confidence range: {confidence_stats['min_confidence']:.3f} to {confidence_stats['max_confidence']:.3f}")
        print(f"Rejected predictions: {confidence_stats['rejected_count']} ({confidence_stats['rejection_rate']*100:.1f}%)")
    print("\n" + "-" * 80)
    print("TIMING SUMMARY")
    print("-" * 80)
    print(f"Total execution time: {timedelta(seconds=int(overall_duration))} ({overall_duration:.2f} seconds)")
    print(f"Average time per evaluation: {avg_processing_time:.3f} seconds")
    if note_timings:
        avg_note_time = sum(nt['total_time_seconds'] for nt in note_timings) / len(note_timings)
        print(f"Average time per note: {avg_note_time:.2f} seconds")
        print(f"Fastest note: {min(nt['total_time_seconds'] for nt in note_timings):.2f}s")
        print(f"Slowest note: {max(nt['total_time_seconds'] for nt in note_timings):.2f}s")
    print("=" * 80)


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Evaluate LLM outputs on INT prompts for first patient notes"
    )
    parser.add_argument(
        "--notes-csv",
        type=str,
        help="Path to first_patient_notes.csv"
    )
    parser.add_argument(
        "--mapping-csv",
        type=str,
        help="DEPRECATED: Annotations are now loaded from --json-file. This argument is kept for backward compatibility but ignored."
    )
    parser.add_argument(
        "--json-file",
        type=str,
        help="Path to annotated_patient_notes_with_spans_full_verified.json (used for both few-shot examples and gold annotations)"
    )
    parser.add_argument(
        "--prompts-json",
        type=str,
        help="Path to FBK_scripts/prompts.json"
    )
    parser.add_argument(
        "--model-path",
        type=str,
        help="Path to LLM model file"
    )
    parser.add_argument(
        "--faiss-dir",
        type=str,
        default="faiss_store",
        help="Directory for FAISS indexes"
    )
    parser.add_argument(
        "--fewshot-k",
        type=int,
        default=5,
        help="Number of fewshot examples to retrieve (ignored if --no-fewshots is used)"
    )
    parser.add_argument(
        "--no-fewshots",
        action="store_true",
        help="Run in zero-shot mode without few-shot examples"
    )
    parser.add_argument(
        "--force-rebuild-faiss",
        action="store_true",
        help="Force rebuild FAISS indexes"
    )
    parser.add_argument(
        "--report-type-mapping",
        type=str,
        help="Path to report_type_prompt_mapping.json. If provided, only runs prompts relevant to each note's report_type."
    )
    parser.add_argument(
        "--use-confidence-threshold",
        action="store_true",
        help="Enable confidence-based filtering using VLLM logprobs (VLLM only, ignored for llama.cpp)"
    )
    parser.add_argument(
        "--confidence-threshold",
        type=float,
        default=-2.0,
        help="Logprob threshold for rejecting low-confidence predictions (default: -2.0)"
    )
    parser.add_argument(
        "--confidence-config",
        type=str,
        help="Path to confidence_config.json with per-prompt-type thresholds"
    )
    
    args = parser.parse_args()
    
    main(
        notes_csv_path=args.notes_csv,
        mapping_csv_path=args.mapping_csv,
        json_file_path=args.json_file,
        prompts_json_path=args.prompts_json,
        model_path=args.model_path,
        faiss_store_dir=args.faiss_dir,
        fewshot_k=args.fewshot_k,
        use_fewshots=not args.no_fewshots,  # Invert: --no-fewshots means use_fewshots=False
        force_rebuild_faiss=args.force_rebuild_faiss,
        report_type_mapping_path=args.report_type_mapping,
        use_confidence_threshold=args.use_confidence_threshold,
        confidence_threshold=args.confidence_threshold,
        confidence_config_path=args.confidence_config
    )

