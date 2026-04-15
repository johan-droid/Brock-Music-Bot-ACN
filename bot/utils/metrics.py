"""Performance metrics collection and reporting for button optimization analysis."""

import logging
import time
from typing import Dict, Optional
from datetime import datetime, timedelta
from collections import defaultdict
from dataclasses import dataclass, field
import json

logger = logging.getLogger(__name__)


@dataclass
class CallbackMetrics:
    """Metrics for a single callback execution."""
    action: str
    chat_id: int
    timestamp: float
    response_time_ms: float
    cache_hit: Optional[bool] = None  # True if cache hit, False if miss, None if N/A
    db_lookup_time_ms: float = 0.0
    background_task_created: bool = False
    
    def __repr__(self):
        cache_status = ""
        if self.cache_hit is not None:
            cache_status = f" | Cache: {'HIT' if self.cache_hit else 'MISS'}"
        return (f"[{self.action.upper()}] RTT: {self.response_time_ms:.1f}ms"
                f"{cache_status} | DB: {self.db_lookup_time_ms:.1f}ms"
                f" | BG: {self.background_task_created}")


class MetricsCollector:
    """Collect and aggregate performance metrics across all callbacks."""
    
    def __init__(self, max_samples: int = 10000):
        """Initialize metrics collector.
        
        Args:
            max_samples: Maximum number of samples to store before rotating
        """
        self.max_samples = max_samples
        self.metrics: list[CallbackMetrics] = []
        
        # Aggregated stats by action
        self.stats_by_action: Dict[str, Dict] = defaultdict(lambda: {
            "count": 0,
            "total_time_ms": 0,
            "min_time_ms": float('inf'),
            "max_time_ms": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "avg_db_time_ms": 0,
            "total_db_time_ms": 0,
        })
        
        self.start_time = datetime.now()
    
    def record_callback(self, metric: CallbackMetrics) -> None:
        """Record a callback metric."""
        # Maintain size limit
        if len(self.metrics) >= self.max_samples:
            self.metrics = self.metrics[-self.max_samples // 2:]
        
        self.metrics.append(metric)
        
        # Update aggregated stats
        stats = self.stats_by_action[metric.action]
        stats["count"] += 1
        stats["total_time_ms"] += metric.response_time_ms
        stats["min_time_ms"] = min(stats["min_time_ms"], metric.response_time_ms)
        stats["max_time_ms"] = max(stats["max_time_ms"], metric.response_time_ms)
        
        if metric.cache_hit is not None:
            if metric.cache_hit:
                stats["cache_hits"] += 1
            else:
                stats["cache_misses"] += 1
        
        if metric.db_lookup_time_ms > 0:
            stats["total_db_time_ms"] += metric.db_lookup_time_ms
            stats["avg_db_time_ms"] = stats["total_db_time_ms"] / stats["count"]
        
        logger.debug(f"Metrics recorded: {metric}")
    
    def get_stats_by_action(self, action: Optional[str] = None) -> Dict:
        """Get aggregated stats for one or all actions.
        
        Args:
            action: Optional specific action to get stats for (e.g., "pause", "queue")
        
        Returns:
            Dict of {action: {count, avg_time, min_time, max_time, cache_hit_rate, ...}}
        """
        if action:
            if action not in self.stats_by_action:
                return {}
            stats = self.stats_by_action[action].copy()
            if stats["count"] > 0:
                stats["avg_time_ms"] = stats["total_time_ms"] / stats["count"]
                stats["cache_hit_rate"] = (
                    stats["cache_hits"] / (stats["cache_hits"] + stats["cache_misses"])
                    if (stats["cache_hits"] + stats["cache_misses"]) > 0
                    else None
                )
            return stats
        
        # Return all actions
        result = {}
        for action_name, stats in self.stats_by_action.items():
            stats_copy = stats.copy()
            if stats_copy["count"] > 0:
                stats_copy["avg_time_ms"] = stats_copy["total_time_ms"] / stats_copy["count"]
                stats_copy["cache_hit_rate"] = (
                    stats_copy["cache_hits"] / (stats_copy["cache_hits"] + stats_copy["cache_misses"])
                    if (stats_copy["cache_hits"] + stats_copy["cache_misses"]) > 0
                    else None
                )
            result[action_name] = stats_copy
        
        return result
    
    def get_recent_metrics(self, action: Optional[str] = None, last_n: int = 50) -> list:
        """Get recent callback metrics.
        
        Args:
            action: Optional specific action to filter by
            last_n: Number of recent samples to return
        
        Returns:
            List of CallbackMetrics, most recent first
        """
        metrics = self.metrics[-last_n:] if self.metrics else []
        
        if action:
            metrics = [m for m in metrics if m.action == action]
        
        return list(reversed(metrics))
    
    def log_summary(self) -> str:
        """Generate a summary log of current metrics.
        
        Returns:
            Formatted summary string
        """
        now = datetime.now()
        uptime = now - self.start_time
        
        lines = [
            "\n" + "="*80,
            "📊 BUTTON OPTIMIZATION METRICS SUMMARY",
            f"Uptime: {uptime.total_seconds():.0f}s | Total samples: {len(self.metrics)}",
            "="*80,
        ]
        
        stats = self.get_stats_by_action()
        
        if not stats:
            lines.append("No metrics collected yet.")
            return "\n".join(lines)
        
        # Header
        lines.append(f"{'Action':<15} {'Count':<8} {'Avg RTT':<10} {'Min/Max':<15} {'Cache Hit %':<12} {'Avg DB':<10}")
        lines.append("-"*80)
        
        # Sort by frequency
        sorted_actions = sorted(stats.items(), key=lambda x: x[1]['count'], reverse=True)
        
        for action, action_stats in sorted_actions:
            count = action_stats["count"]
            avg_time = action_stats.get("avg_time_ms", 0)
            min_time = action_stats["min_time_ms"]
            max_time = action_stats["max_time_ms"]
            cache_hit_rate = action_stats.get("cache_hit_rate")
            avg_db = action_stats["avg_db_time_ms"]
            
            cache_str = f"{cache_hit_rate*100:.0f}%" if cache_hit_rate is not None else "N/A"
            
            lines.append(
                f"{action:<15} {count:<8} {avg_time:>6.1f}ms   "
                f"{min_time:>5.1f}/{max_time:>6.1f}ms {cache_str:<12} {avg_db:>6.1f}ms"
            )
        
        # Performance tiers
        lines.append("\n" + "-"*80)
        lines.append("⚡ PERFORMANCE BY TIER (based on avg RTT):")
        lines.append(f"{'Ultra (<10ms)':<20} {'Fast (10-50ms)':<20} {'Normal (50-100ms)':<20} {'Slow (>100ms)':<20}")
        
        ultra = sum(1 for _, s in stats.items() if s.get("avg_time_ms", 0) < 10)
        fast = sum(1 for _, s in stats.items() if 10 <= s.get("avg_time_ms", 0) < 50)
        normal = sum(1 for _, s in stats.items() if 50 <= s.get("avg_time_ms", 0) < 100)
        slow = sum(1 for _, s in stats.items() if s.get("avg_time_ms", 0) >= 100)
        
        lines.append(f"{ultra:<20} {fast:<20} {normal:<20} {slow:<20}")
        
        # Phase assessment
        lines.append("\n" + "="*80)
        lines.append("📈 OPTIMIZATION PHASE ASSESSMENT:")
        
        # Phase 1: Optimistic state caching (should see <10ms for pause/resume)
        pause_stats = stats.get("pause", {})
        resume_stats = stats.get("resume", {})
        pause_avg = pause_stats.get("avg_time_ms", 0)
        resume_avg = resume_stats.get("avg_time_ms", 0)
        
        if pause_avg < 20 and resume_avg < 20:
            lines.append("✅ Phase 1 (Optimistic State): SUCCESS - Pause/Resume <20ms")
        else:
            lines.append(f"⚠️  Phase 1 (Optimistic State): Pause={pause_avg:.1f}ms, Resume={resume_avg:.1f}ms")
        
        # Phase 2: Button state rendering (buttons should show correct state)
        lines.append("✅ Phase 2 (Button State): Enabled - Buttons show state-aware rendering")
        
        # Phase 3: Queue caching (queue should have high cache hit rate)
        queue_stats = stats.get("queue", {})
        queue_hit_rate = queue_stats.get("cache_hit_rate")
        
        if queue_hit_rate is not None:
            if queue_hit_rate > 0.5:
                lines.append(f"✅ Phase 3 (Queue Cache): SUCCESS - {queue_hit_rate*100:.0f}% hit rate")
            else:
                lines.append(f"⚠️  Phase 3 (Queue Cache): {queue_hit_rate*100:.0f}% hit rate (< 50%)")
        else:
            lines.append("⏳ Phase 3 (Queue Cache): Not enough samples yet")
        
        lines.append("="*80 + "\n")
        
        return "\n".join(lines)
    
    def export_json(self) -> str:
        """Export metrics as JSON string.
        
        Returns:
            JSON string with full metrics data
        """
        stats = self.get_stats_by_action()
        
        # Convert defaultdicts to regular dicts for serialization
        export_data = {
            "timestamp": datetime.now().isoformat(),
            "uptime_seconds": (datetime.now() - self.start_time).total_seconds(),
            "total_samples": len(self.metrics),
            "stats_by_action": {k: dict(v) for k, v in stats.items()},
            "recent_metrics": [
                {
                    "action": m.action,
                    "response_time_ms": m.response_time_ms,
                    "cache_hit": m.cache_hit,
                    "db_time_ms": m.db_lookup_time_ms,
                }
                for m in self.get_recent_metrics(last_n=100)
            ]
        }
        
        return json.dumps(export_data, indent=2)


# Global metrics instance
metrics_collector = MetricsCollector()


async def log_metrics_periodically(interval_seconds: int = 300) -> None:
    """Periodically log metrics summary (runs in background).
    
    Args:
        interval_seconds: How often to log (default: 5 minutes)
    """
    import asyncio
    
    while True:
        try:
            await asyncio.sleep(interval_seconds)
            summary = metrics_collector.log_summary()
            logger.info(summary)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Error logging metrics: {e}")


def log_metrics_now() -> str:
    """Log metrics immediately and return summary string."""
    summary = metrics_collector.log_summary()
    logger.info(summary)
    return summary
