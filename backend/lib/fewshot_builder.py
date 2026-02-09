"""
Fewshot Builder for INT Prompts

Extracts patients 2-3 from annotated_patient_notes.json (or annotated_patient_notes_with_spans_full_verified.json),
filters notes by prompt type, and builds FAISS indexes for RAG-based fewshot example retrieval.

If annotations_with_spans is available in the JSON, uses only the relevant text spans for each annotation
instead of the full note text, providing more focused context for few-shot examples.
"""

import json
import re
import pandas as pd
import faiss
import numpy as np
from pathlib import Path
from sentence_transformers import SentenceTransformer
from typing import List, Tuple, Dict, Optional


# Reuse the annotation mapping logic from convert_json_to_csv.py
def map_annotation_to_prompt(annotation_text: str, prompt_key: str) -> bool:
    """
    Check if an annotation matches a specific prompt type.
    
    Args:
        annotation_text: The annotation string from the JSON
        prompt_key: The prompt key (e.g., 'gender-int', 'biopsygrading-int')
    
    Returns:
        bool: True if the annotation matches the prompt type
    """
    annotation_lower = annotation_text.lower().strip()
    
    # Mapping of prompt keys to annotation patterns (must match at the start or be a key phrase)
    prompt_patterns = {
        'gender-int': [r'^patient\'?s gender', r'^gender'],
        'biopsygrading-int': [r'biopsy grading.*fnclcc', r'^biopsy grading'],
        'surgerymargins-int': [r'^margins after surgery', r'^margins'],
        'tumordepth-int': [r'^tumor depth'],
        'biopsymitoticcount-int': [r'^biopsy mitotic count', r'unknown biopsy mitotic count'],
        'reexcision-int': [r're-?excision', r'radicalization'],
        'necrosis_in_biopsy-int': [r'necrosis in biopsy'],
        'previous_cancer_treatment-int': [r'^previous cancer treatment', r'no previous cancer'],
        'chemotherapy_start-int': [r'chemotherapy.*started on', r'pre-operative chemotherapy', r'post-operative chemotherapy'],
        'surgerytype-fs30-int': [r'^primary surgery was performed', r'^surgery was performed', r'^surgery was not performed'],
        'radiotherapy_start-int': [r'radiotherapy.*started', r'pre-operative radiotherapy', r'post-operative radiotherapy'],
        'recurrencetype-int': [r'^type of recurrence', r'recurrence/progression'],
        'radiotherapy_end-int': [r'radiotherapy.*ended on', r'radiotherapy in total of'],
        'tumorbiopsytype-int': [r'baseline/primary tumor.*biopsy has been performed', r'biopsy has been performed'],
        'necrosis_in_surgical-int': [r'necrosis in surgical'],
        'tumordiameter-int': [r'^tumor longest diameter', r'tumor longest diameter unknown'],
        'patient-status-int': [r'^status of the patient', r'last follow-up'],
        'response-to-int': [r'^response to.*radiotherapy', r'^response to.*chemotherapy'],
        'stage_at_diagnosis-int': [r'^stage at diagnosis', r'unknown.*stage at diagnosis', r'unknown stage'],
        'chemotherapy_end-int': [r'chemotherapy ended on', r'pre-operative chemotherapy ended', r'post-operative chemotherapy ended'],
        'occurrence_cancer-int': [r'^occurrence of other cancer', r'^no previous or concurrent cancers', r'no information about occurrence'],
        'surgical-specimen-grading-int': [r'surgical specimen grading.*fnclcc', r'^surgical specimen grading'],
        'ageatdiagnosis-int': [r'^age at diagnosis'],
        'recur_or_prog-int': [r'^there was.*progression', r'^there was.*recurrence', r'no progression/recurrence'],
        'histological-tipo-int': [r'^histological type', r'icd-o-3'],
        'surgical-mitotic-count-int': [r'^surgical specimen mitotic count', r'unknown surgical specimen mitotic count'],
        'tumorsite-int': [r'^tumor site']
    }
    
    patterns = prompt_patterns.get(prompt_key, [])
    for pattern in patterns:
        if re.search(pattern, annotation_lower, re.IGNORECASE):
            return True
    return False


class FewshotBuilder:
    """Build and manage FAISS indexes for fewshot examples."""
    
    def __init__(self, store_dir: str | Path = "faiss_store", use_gpu: bool = True):
        """
        Initialize the fewshot builder.
        
        Args:
            store_dir: Directory to store FAISS indexes and metadata
            use_gpu: If True, use GPU for embeddings (faster)
        """
        self.store_dir = Path(store_dir)
        self.store_dir.mkdir(exist_ok=True)
        self.use_gpu = use_gpu
        # Initialize embedder with GPU if available
        device = "cuda" if use_gpu else "cpu"
        self.embedder = SentenceTransformer("sentence-transformers/all-mpnet-base-v2", device=device)
        if use_gpu:
            print(f"[INFO] SentenceTransformer using device: {device}")
        self.indexes: Dict[str, faiss.Index] = {}
        self.metadata: Dict[str, pd.DataFrame] = {}
    
    def extract_patients_for_fewshot(
        self,
        json_file_path: str | Path,
        patient_indices: List[int] = [1, 2]
    ) -> List[Dict]:
        """
        Extract specific patients from annotated_patient_notes.json.
        
        Args:
            json_file_path: Path to annotated_patient_notes.json
            patient_indices: List of patient indices to extract (default: [1, 2] for patients 2-3)
        
        Returns:
            List of patient dictionaries
        """
        json_file_path = Path(json_file_path)
        
        with open(json_file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        if not data or len(data) == 0:
            raise ValueError("JSON file is empty or has no patients.")
        
        extracted_patients = []
        for idx in patient_indices:
            if idx < 0 or idx >= len(data):
                print(f"[WARN] Patient index {idx} out of range (total: {len(data)})")
                continue
            extracted_patients.append(data[idx])
        
        return extracted_patients
    
    def build_index_for_prompt_type(
        self,
        prompt_key: str,
        patients: List[Dict],
        min_examples: int = 1
    ) -> bool:
        """
        Build FAISS index for a specific prompt type from extracted patients.
        
        Uses text spans from annotations_with_spans if available, otherwise falls back to full note text.
        
        Args:
            prompt_key: The prompt key (e.g., 'gender-int')
            patients: List of patient dictionaries from JSON
            min_examples: Minimum number of examples required to build index
        
        Returns:
            True if index was built successfully, False otherwise
        """
        # Collect all notes with matching annotations for this prompt type
        examples = []
        
        for patient in patients:
            if 'notes' not in patient:
                continue
            
            for note in patient.get('notes', []):
                note_text = note.get('text', '')
                annotations = note.get('annotations', [])
                annotations_with_spans = note.get('annotations_with_spans', [])
                
                # Find matching annotations for this prompt type
                for annotation in annotations:
                    if map_annotation_to_prompt(annotation, prompt_key):
                        # Try to find corresponding annotation_with_spans
                        context_text = note_text  # Default to full note text
                        
                        if annotations_with_spans:
                            # Find the matching annotation_with_spans entry
                            for ann_with_spans in annotations_with_spans:
                                if ann_with_spans.get('template_text') == annotation:
                                    # Extract all text spans and combine them
                                    supporting_spans = ann_with_spans.get('supporting_text_spans', [])
                                    if supporting_spans:
                                        # Extract text from each span and join with separator
                                        span_texts = [span.get('text', '').strip() 
                                                     for span in supporting_spans 
                                                     if span.get('text', '').strip()]
                                        if span_texts:
                                            # Join spans with " ... " separator for readability
                                            context_text = " ... ".join(span_texts)
                                        break  # Found matching annotation, use its spans
                        
                        examples.append({
                            'note_original_text': context_text,  # Use span text if available, else full note
                            'annotation': annotation
                        })
                        break  # Only take first matching annotation per note
        
        if len(examples) < min_examples:
            print(f"[WARN] Only {len(examples)} examples found for '{prompt_key}', "
                  f"minimum {min_examples} required. Skipping.")
            return False
        
        # Create DataFrame
        df = pd.DataFrame(examples)
        
        # Remove duplicates (same note_text and annotation combination)
        df = df.drop_duplicates(subset=['note_original_text', 'annotation'], keep='first')
        
        if len(df) < min_examples:
            print(f"[WARN] After deduplication, only {len(df)} examples for '{prompt_key}'. Skipping.")
            return False
        
        # Build embeddings (use GPU if available)
        texts = df['note_original_text'].tolist()
        embeddings = self.embedder.encode(
            texts,
            convert_to_numpy=True,
            normalize_embeddings=True,  # For cosine similarity
            batch_size=32,  # Batch processing for faster encoding
            show_progress_bar=False
        )
        
        # Create FAISS index (cosine similarity with normalized embeddings)
        dimension = embeddings.shape[1]
        index = faiss.IndexFlatIP(dimension)  # Inner product = cosine for normalized vectors
        index.add(embeddings.astype(np.float32))
        
        # Save index and metadata
        index_path = self.store_dir / f"{prompt_key}.index"
        parquet_path = self.store_dir / f"{prompt_key}.parquet"
        meta_path = self.store_dir / f"{prompt_key}.json"
        
        faiss.write_index(index, str(index_path))
        df.to_parquet(parquet_path, index=False)
        
        meta = {
            "task": prompt_key,
            "dim": int(dimension),
            "size": int(len(df))
        }
        with open(meta_path, 'w', encoding='utf-8') as f:
            json.dump(meta, f, indent=2)
        
        # Store in memory
        self.indexes[prompt_key] = index
        self.metadata[prompt_key] = df
        
        print(f"[INFO] Built FAISS index for '{prompt_key}': {len(df)} examples")
        return True
    
    def load_index(self, prompt_key: str) -> bool:
        """
        Load existing FAISS index from disk.
        
        Args:
            prompt_key: The prompt key to load
        
        Returns:
            True if loaded successfully, False otherwise
        """
        index_path = self.store_dir / f"{prompt_key}.index"
        parquet_path = self.store_dir / f"{prompt_key}.parquet"
        
        if not index_path.exists() or not parquet_path.exists():
            return False
        
        try:
            self.indexes[prompt_key] = faiss.read_index(str(index_path))
            self.metadata[prompt_key] = pd.read_parquet(parquet_path)
            print(f"[INFO] Loaded FAISS index for '{prompt_key}'")
            return True
        except Exception as e:
            print(f"[ERROR] Failed to load index for '{prompt_key}': {e}")
            return False
    
    def get_fewshot_examples(
        self,
        prompt_key: str,
        note_text: str,
        k: int = 10
    ) -> List[Tuple[str, str]]:
        """
        Retrieve top-k similar fewshot examples for a given note.
        
        Args:
            prompt_key: The prompt type key
            note_text: The input note text
            k: Number of examples to retrieve
        
        Returns:
            List of (note_text, annotation) tuples
        """
        # Load index if not in memory
        if prompt_key not in self.indexes:
            if not self.load_index(prompt_key):
                print(f"[WARN] No index found for '{prompt_key}', returning empty list")
                return []
        
        # Get embeddings for the input note (use GPU if available)
        query_embedding = self.embedder.encode(
            [note_text],
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False
        ).astype(np.float32)
        
        # Search FAISS index
        index = self.indexes[prompt_key]
        metadata = self.metadata[prompt_key]
        
        # Get top-k similar examples
        distances, indices = index.search(query_embedding, min(k, len(metadata)))
        
        # Return as list of (note_text, annotation) tuples
        results = []
        for idx in indices[0]:
            if idx >= 0 and idx < len(metadata):
                row = metadata.iloc[idx]
                results.append((row['note_original_text'], row['annotation']))
        
        return results
    
    def preload_all_indexes(self, prompt_keys: List[str]):
        """
        Preload all FAISS indexes into memory for faster retrieval.
        
        Args:
            prompt_keys: List of prompt keys to preload
        """
        print(f"[INFO] Preloading {len(prompt_keys)} FAISS indexes...")
        loaded = 0
        for prompt_key in prompt_keys:
            if self.load_index(prompt_key):
                loaded += 1
        print(f"[INFO] Preloaded {loaded}/{len(prompt_keys)} indexes")
    
    def build_all_int_prompts(
        self,
        json_file_path: str | Path,
        prompts_json_path: str | Path,
        patient_indices: List[int] = [1, 2],
        force_rebuild: bool = False
    ):
        """
        Build FAISS indexes for all INT prompt types.
        
        Args:
            json_file_path: Path to annotated_patient_notes.json
            prompts_json_path: Path to FBK_scripts/prompts.json
            patient_indices: Patient indices to use for fewshot examples
            force_rebuild: If True, rebuild even if index exists
        """
        # Load INT prompt keys
        with open(prompts_json_path, 'r', encoding='utf-8') as f:
            prompts_data = json.load(f)
        
        int_prompts = prompts_data.get('INT', {})
        prompt_keys = list(int_prompts.keys())
        
        # Extract patients
        patients = self.extract_patients_for_fewshot(json_file_path, patient_indices)
        print(f"[INFO] Extracted {len(patients)} patients for fewshot building")
        
        # Build indexes for each prompt type
        built_count = 0
        skipped_count = 0
        
        for prompt_key in prompt_keys:
            # Check if index already exists
            index_path = self.store_dir / f"{prompt_key}.index"
            if index_path.exists() and not force_rebuild:
                print(f"[INFO] Index for '{prompt_key}' already exists, skipping")
                skipped_count += 1
                continue
            
            if self.build_index_for_prompt_type(prompt_key, patients):
                built_count += 1
            else:
                skipped_count += 1
        
        print(f"\n[INFO] Completed: {built_count} built, {skipped_count} skipped/total")


if __name__ == "__main__":
    # Test the builder
    script_dir = Path(__file__).resolve().parent
    json_file = script_dir / "annotated_patient_notes.json"
    prompts_file = script_dir / "FBK_scripts" / "prompts.json"
    
    builder = FewshotBuilder()
    builder.build_all_int_prompts(json_file, prompts_file, force_rebuild=False)

