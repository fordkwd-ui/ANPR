"""Thread-safe latency tracker for p50 and p95 metrics over a 1-hour rolling window."""
from collections import deque
from datetime import datetime, timezone
import math
import threading
from typing import Any, Dict, List, Optional, Tuple


class LatencyTracker:
    """Stores ingestion & WebSocket latency samples over a rolling 1-hour window."""

    def __init__(self, max_seconds: int = 3600):
        self.max_seconds = max_seconds
        self._samples: deque[Tuple[float, float, Optional[float]]] = deque()
        self._lock = threading.Lock()

    def record_event(
        self,
        captured_at: datetime,
        received_at: datetime,
        ws_sent_at: Optional[datetime] = None,
    ) -> None:
        """
        Records latency in milliseconds:
        recv_latency_ms = (received_at - captured_at).total_seconds() * 1000
        ws_latency_ms = (ws_sent_at - captured_at).total_seconds() * 1000 (if provided)
        """
        now = datetime.now(timezone.utc).timestamp()

        # Handle naive datetimes by assuming UTC
        if captured_at.tzinfo is None:
            captured_at = captured_at.replace(tzinfo=timezone.utc)
        if received_at.tzinfo is None:
            received_at = received_at.replace(tzinfo=timezone.utc)

        recv_ms = max(0.0, (received_at - captured_at).total_seconds() * 1000.0)
        ws_ms = None
        if ws_sent_at is not None:
            if ws_sent_at.tzinfo is None:
                ws_sent_at = ws_sent_at.replace(tzinfo=timezone.utc)
            ws_ms = max(0.0, (ws_sent_at - captured_at).total_seconds() * 1000.0)

        with self._lock:
            self._samples.append((now, recv_ms, ws_ms))
            self._prune_locked(now)

    def _prune_locked(self, now: float) -> None:
        cutoff = now - self.max_seconds
        while self._samples and self._samples[0][0] < cutoff:
            self._samples.popleft()

    @staticmethod
    def _percentile(values: List[float], p: float) -> float:
        if not values:
            return 0.0
        sorted_vals = sorted(values)
        k = (len(sorted_vals) - 1) * (p / 100.0)
        f = math.floor(k)
        c = math.ceil(k)
        if f == c:
            return float(sorted_vals[int(k)])
        d0 = sorted_vals[int(f)] * (c - k)
        d1 = sorted_vals[int(c)] * (k - f)
        return float(d0 + d1)

    def get_metrics(self) -> Dict[str, Any]:
        """Calculates p50 and p95 for received_at and ws_sent_at latencies."""
        now = datetime.now(timezone.utc).timestamp()
        with self._lock:
            self._prune_locked(now)
            recv_latencies = [s[1] for s in self._samples]
            ws_latencies = [s[2] for s in self._samples if s[2] is not None]

        return {
            "samples_count": len(recv_latencies),
            "window_seconds": self.max_seconds,
            "received_to_captured_p50_ms": round(self._percentile(recv_latencies, 50), 2),
            "received_to_captured_p95_ms": round(self._percentile(recv_latencies, 95), 2),
            "ws_to_captured_p50_ms": round(self._percentile(ws_latencies, 50), 2),
            "ws_to_captured_p95_ms": round(self._percentile(ws_latencies, 95), 2),
        }


latency_tracker = LatencyTracker()
