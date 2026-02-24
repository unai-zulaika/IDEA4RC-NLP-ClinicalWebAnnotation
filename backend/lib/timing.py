"""
Timing utility for measuring pipeline step durations.
"""

import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class TimingBreakdown:
    """Tracks durations for named pipeline steps."""

    _steps: Dict[str, float] = field(default_factory=dict)
    _running: Dict[str, float] = field(default_factory=dict)
    _start_time: Optional[float] = None

    def start(self, step: str) -> None:
        """Start timing a named step."""
        self._running[step] = time.perf_counter()

    def stop(self, step: str) -> float:
        """Stop timing a named step and return its duration."""
        if step not in self._running:
            return 0.0
        elapsed = time.perf_counter() - self._running.pop(step)
        self._steps[step] = self._steps.get(step, 0.0) + elapsed
        return elapsed

    @contextmanager
    def measure(self, step: str):
        """Context manager to time a named step."""
        self.start(step)
        try:
            yield
        finally:
            self.stop(step)

    def start_total(self) -> None:
        """Start the total timer."""
        self._start_time = time.perf_counter()

    def get_total(self) -> float:
        """Get total elapsed time since start_total()."""
        if self._start_time is None:
            return sum(self._steps.values())
        return time.perf_counter() - self._start_time

    def to_dict(self) -> Dict[str, float]:
        """Return all step durations plus total."""
        result = dict(self._steps)
        result["total"] = self.get_total()
        return result
