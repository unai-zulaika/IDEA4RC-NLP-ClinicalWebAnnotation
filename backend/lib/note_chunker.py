"""
Note chunker for handling clinical notes that exceed the LLM context window.

Strategy: sliding window with sentence-boundary-aware splitting and
sentence overlap. Returns overlapping chunks that each fit within the
token budget. Tokenizer is loaded from the local model path in
vllm_config.json; falls back to character-based approximation if unavailable.
"""
import json
import logging
import re
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

# Null-like values for "confident answer" detection (English + Italian)
_NULL_PATTERNS: frozenset = frozenset({
    "", "unknown", "n/a", "not mentioned", "not found", "not available",
    "not stated", "not provided", "not specified", "not documented",
    "nessuno", "non specificato", "non disponibile", "non menzionato",
    "non presente", "non riportato", "non indicato",
})

# Sentence boundary: period/!/? followed by whitespace, or two+ newlines
_SENTENCE_BOUNDARY = re.compile(r'(?<=[.!?])\s+|\n{2,}')


class NoteChunker:
    """
    Splits long clinical notes into overlapping chunks that fit the context window.

    Usage (singleton):
        chunker = NoteChunker.get_instance()
        chunks = chunker.chunk_note(note_text, available_tokens=5000)
    """

    _instance: Optional["NoteChunker"] = None

    def __init__(self, context_window: int = 8192):
        self.context_window = context_window
        self._tokenizer = None
        self._using_approximation = False
        self._try_load_tokenizer()

    # ── Singleton ────────────────────────────────────────────────────────

    @classmethod
    def get_instance(cls) -> "NoteChunker":
        """Return (and lazily create) the module-level singleton."""
        if cls._instance is None:
            context_window = cls._read_context_window_from_config()
            cls._instance = cls(context_window)
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset singleton (useful in tests)."""
        cls._instance = None

    # ── Config helpers ───────────────────────────────────────────────────

    @staticmethod
    def _read_context_window_from_config() -> int:
        config_path = Path(__file__).parent.parent / "config" / "vllm_config.json"
        try:
            with open(config_path, encoding="utf-8") as f:
                config = json.load(f)
            return int(config.get("context_window", 8192))
        except Exception:
            return 8192

    def _resolve_model_path(self) -> Optional[str]:
        """Resolve local model path from vllm_config.json (for tokenizer loading)."""
        config_path = Path(__file__).parent.parent / "config" / "vllm_config.json"
        try:
            with open(config_path, encoding="utf-8") as f:
                config = json.load(f)
            model_name = config.get("model_name", "")
            if not model_name:
                return None
            if model_name.startswith("/"):
                resolved = Path(model_name).resolve()
            else:
                # Relative path: resolve from project root (parent of backend/)
                project_root = Path(__file__).parent.parent.parent
                resolved = (project_root / model_name).resolve()
            return str(resolved) if resolved.exists() else None
        except Exception:
            return None

    # ── Tokenizer ────────────────────────────────────────────────────────

    def _try_load_tokenizer(self) -> None:
        """Attempt to load the model's tokenizer; fall back to char approximation."""
        model_path = self._resolve_model_path()
        if model_path is None:
            logger.warning(
                "[NoteChunker] Model path not found; using char-based token approximation (len//4)"
            )
            self._using_approximation = True
            return
        try:
            from transformers import AutoTokenizer
            self._tokenizer = AutoTokenizer.from_pretrained(model_path)
            logger.info(f"[NoteChunker] Tokenizer loaded from {model_path}")
        except Exception as exc:
            logger.warning(
                f"[NoteChunker] Tokenizer load failed ({exc}); using char-based approximation"
            )
            self._using_approximation = True

    def count_tokens(self, text: str) -> int:
        """Count tokens; falls back to len(text)//4 if tokenizer unavailable."""
        if self._using_approximation or self._tokenizer is None:
            return max(1, len(text) // 4)
        try:
            return len(self._tokenizer.encode(text, add_special_tokens=False))
        except Exception:
            return max(1, len(text) // 4)

    # ── Token budget ─────────────────────────────────────────────────────

    def calculate_available_tokens(self, prompt_without_note: str, output_buffer: int) -> int:
        """
        Calculate token budget available for the note text.

        Args:
            prompt_without_note: Fully formatted prompt with note replaced by "".
            output_buffer: Tokens reserved for the model's generated output.

        Returns:
            Token count available for note content (minimum 100).
        """
        overhead = self.count_tokens(prompt_without_note)
        available = self.context_window - overhead - output_buffer
        return max(100, available)

    # ── Chunking ─────────────────────────────────────────────────────────

    def chunk_note(
        self,
        note_text: str,
        available_tokens: int,
        overlap_sentences: int = 2,
    ) -> List[str]:
        """
        Split note_text into overlapping chunks that each fit within available_tokens.

        Args:
            note_text: Full clinical note.
            available_tokens: Max tokens allowed per chunk.
            overlap_sentences: Sentences to repeat between consecutive chunks
                               (maintains cross-boundary context).

        Returns:
            List of text chunks. Single-element list if note already fits.
        """
        if self.count_tokens(note_text) <= available_tokens:
            return [note_text]

        sentences = _SENTENCE_BOUNDARY.split(note_text)
        sentences = [s.strip() for s in sentences if s.strip()]

        chunks: List[str] = []
        current: List[str] = []
        current_tokens = 0

        for sentence in sentences:
            stokens = self.count_tokens(sentence)

            if stokens > available_tokens:
                # Single oversized sentence — flush then word-split
                if current:
                    chunks.append(" ".join(current))
                word_chunks = self._split_by_words(sentence, available_tokens)
                chunks.extend(word_chunks)
                # Use last word-chunk's tail as overlap seed
                if word_chunks:
                    tail = word_chunks[-1].split()
                    current = [" ".join(tail[-20:])] if len(tail) > 20 else [word_chunks[-1]]
                    current_tokens = self.count_tokens(current[0])
                else:
                    current, current_tokens = [], 0
                continue

            if current_tokens + stokens > available_tokens:
                # Flush chunk with overlap
                chunks.append(" ".join(current))
                overlap = current[-overlap_sentences:] if len(current) >= overlap_sentences else current[:]
                current = overlap[:]
                current_tokens = sum(self.count_tokens(s) for s in current)

            current.append(sentence)
            current_tokens += stokens

        if current:
            chunks.append(" ".join(current))

        return chunks if chunks else [note_text]

    def _split_by_words(self, text: str, available_tokens: int) -> List[str]:
        """Word-level fallback for sentences that individually exceed the budget."""
        words = text.split()
        chunks: List[str] = []
        current: List[str] = []
        current_tokens = 0
        for word in words:
            wtokens = self.count_tokens(word + " ")
            if current_tokens + wtokens > available_tokens and current:
                chunks.append(" ".join(current))
                current, current_tokens = [], 0
            current.append(word)
            current_tokens += wtokens
        if current:
            chunks.append(" ".join(current))
        return chunks

    # ── Confident-result detection ────────────────────────────────────────

    @staticmethod
    def is_confident_result(annotation_text: str) -> bool:
        """
        Return True if annotation_text contains a real clinical finding.
        Returns False for null/unknown/error answers.
        """
        if not annotation_text or not annotation_text.strip():
            return False
        normalized = annotation_text.strip().lower()
        if normalized.startswith("error:"):
            return False
        return normalized not in _NULL_PATTERNS
