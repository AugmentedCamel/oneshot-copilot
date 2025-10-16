"""Performance metrics tracking for VLM requests."""
import logging
from dataclasses import dataclass
from typing import Dict, List, Optional
from collections import deque
from time import time

logger = logging.getLogger(__name__)


@dataclass
class TimingMetrics:
    """
    Detailed timing metrics for a single VLM request.
    
    Tracks timing at each stage of the processing pipeline:
    - queue_wait_ms: Time spent waiting in queue (enqueue → dequeue)
    - http_post_ms: HTTP request time (socket connect → 200 OK)
    - server_proc_ms: VLM server processing time (from response)
    - total_ms: Total end-to-end time
    - timestamp: When metrics were recorded
    """
    queue_wait_ms: Optional[float] = None
    http_post_ms: Optional[float] = None
    server_proc_ms: Optional[float] = None
    total_ms: Optional[float] = None
    timestamp: float = None
    
    def __post_init__(self):
        """Set timestamp if not provided."""
        if self.timestamp is None:
            self.timestamp = time()


class MetricsCollector:
    """
    Collects and manages performance metrics for VLM requests.
    
    Maintains a rolling history of metrics in memory for analysis
    and provides methods to retrieve and calculate statistics.
    """
    
    def __init__(self, history_size: int = 1000):
        """
        Initialize metrics collector.
        
        Args:
            history_size: Maximum number of metrics to keep in memory
        """
        self.history_size = history_size
        self._metrics: deque = deque(maxlen=history_size)
        self._user_metrics: Dict[str, deque] = {}
        logger.info(f"[METRICS] MetricsCollector initialized with history_size={history_size}")
    
    def record_timing(self, user_id: str, metrics: TimingMetrics) -> None:
        """
        Store metrics for a VLM request.
        
        Args:
            user_id: User identifier
            metrics: TimingMetrics instance with collected timings
        """
        # Add to global metrics
        self._metrics.append(metrics)
        
        # Add to per-user metrics
        if user_id not in self._user_metrics:
            self._user_metrics[user_id] = deque(maxlen=self.history_size)
        self._user_metrics[user_id].append(metrics)
        
        queue_wait_str = f"{metrics.queue_wait_ms:.2f}" if metrics.queue_wait_ms is not None else "N/A"
        http_post_str = f"{metrics.http_post_ms:.2f}" if metrics.http_post_ms is not None else "N/A"
        server_proc_str = f"{metrics.server_proc_ms:.2f}" if metrics.server_proc_ms is not None else "N/A"
        total_str = f"{metrics.total_ms:.2f}" if metrics.total_ms is not None else "N/A"
        
        logger.debug(
            f"[METRICS] Recorded timing - user_id={user_id}, "
            f"queue_wait={queue_wait_str}ms, "
            f"http_post={http_post_str}ms, "
            f"server_proc={server_proc_str}ms, "
            f"total={total_str}ms"
        )
    
    def get_recent_metrics(self, limit: int = 100) -> List[TimingMetrics]:
        """
        Retrieve recent metrics.
        
        Args:
            limit: Maximum number of metrics to return
            
        Returns:
            List of TimingMetrics, most recent first
        """
        # Convert deque to list and return last N items in reverse order
        metrics_list = list(self._metrics)
        return metrics_list[-limit:][::-1]
    
    def get_average_metrics(self, user_id: Optional[str] = None) -> Dict[str, float]:
        """
        Calculate average metrics across all recorded requests.
        
        Args:
            user_id: If provided, calculate averages for specific user only
            
        Returns:
            Dictionary with average values for each timing metric
        """
        # Select metrics source
        if user_id and user_id in self._user_metrics:
            metrics_source = self._user_metrics[user_id]
        else:
            metrics_source = self._metrics
        
        if not metrics_source:
            return {
                'queue_wait_ms': 0.0,
                'http_post_ms': 0.0,
                'server_proc_ms': 0.0,
                'total_ms': 0.0,
                'count': 0
            }
        
        # Calculate sums
        queue_wait_sum = 0.0
        queue_wait_count = 0
        http_post_sum = 0.0
        http_post_count = 0
        server_proc_sum = 0.0
        server_proc_count = 0
        total_sum = 0.0
        total_count = 0
        
        for metric in metrics_source:
            if metric.queue_wait_ms is not None:
                queue_wait_sum += metric.queue_wait_ms
                queue_wait_count += 1
            if metric.http_post_ms is not None:
                http_post_sum += metric.http_post_ms
                http_post_count += 1
            if metric.server_proc_ms is not None:
                server_proc_sum += metric.server_proc_ms
                server_proc_count += 1
            if metric.total_ms is not None:
                total_sum += metric.total_ms
                total_count += 1
        
        return {
            'queue_wait_ms': queue_wait_sum / queue_wait_count if queue_wait_count > 0 else 0.0,
            'http_post_ms': http_post_sum / http_post_count if http_post_count > 0 else 0.0,
            'server_proc_ms': server_proc_sum / server_proc_count if server_proc_count > 0 else 0.0,
            'total_ms': total_sum / total_count if total_count > 0 else 0.0,
            'count': len(metrics_source)
        }
    
    def log_metrics(self, metrics: TimingMetrics, user_id: str) -> None:
        """
        Log metrics in structured format.
        
        Args:
            metrics: TimingMetrics instance to log
            user_id: User identifier
        """
        # Format: VLM_METRICS user=user123 queue_wait_ms=45.2 http_post_ms=892.1 server_proc_ms=734.5 total_ms=1671.8
        queue_wait_str = f"{metrics.queue_wait_ms:.1f}" if metrics.queue_wait_ms is not None else "N/A"
        http_post_str = f"{metrics.http_post_ms:.1f}" if metrics.http_post_ms is not None else "N/A"
        server_proc_str = f"{metrics.server_proc_ms:.1f}" if metrics.server_proc_ms is not None else "N/A"
        total_str = f"{metrics.total_ms:.1f}" if metrics.total_ms is not None else "N/A"
        
        logger.info(
            f"VLM_METRICS user={user_id} "
            f"queue_wait_ms={queue_wait_str} "
            f"http_post_ms={http_post_str} "
            f"server_proc_ms={server_proc_str} "
            f"total_ms={total_str}"
        )


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================
_metrics_collector: Optional[MetricsCollector] = None


def get_metrics_collector() -> MetricsCollector:
    """
    Get the singleton MetricsCollector instance.
    
    Returns:
        The initialized MetricsCollector singleton
        
    Raises:
        RuntimeError: If collector has not been initialized via init_metrics_collector()
    """
    if _metrics_collector is None:
        raise RuntimeError(
            "MetricsCollector not initialized. Call init_metrics_collector() during startup."
        )
    return _metrics_collector


def init_metrics_collector(history_size: Optional[int] = None) -> None:
    """
    Initialize the singleton MetricsCollector.
    
    Args:
        history_size: Maximum number of metrics to keep in memory (default from config)
        
    Should be called once during application startup.
    """
    global _metrics_collector
    
    if _metrics_collector is not None:
        logger.warning("[METRICS] MetricsCollector already initialized, skipping re-initialization")
        return
    
    # Import config here to avoid circular imports
    from app.config import METRICS_HISTORY_SIZE
    
    size = history_size if history_size is not None else METRICS_HISTORY_SIZE
    _metrics_collector = MetricsCollector(history_size=size)
    
    logger.info(f"[METRICS] MetricsCollector singleton initialized with history_size={size}")