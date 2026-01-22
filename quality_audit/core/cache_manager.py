"""
LRU Cache Manager for cross-checking data with memory bounds and performance monitoring.
"""

import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Dict, Optional, Set


@dataclass
class CacheEntry:
    """Cache entry with metadata."""

    value: Any
    timestamp: float
    access_count: int = 0


class LRUCacheManager:
    """
    LRU Cache Manager with configurable size limits and statistics.

    Features:
    - LRU eviction policy
    - Configurable maximum size
    - Thread-safe operations
    - Access statistics
    - TTL support
    """

    def __init__(self, max_size: int = 1000, ttl_seconds: Optional[float] = None):
        """
        Initialize cache manager.

        Args:
            max_size: Maximum number of entries
            ttl_seconds: Time-to-live in seconds (None for no TTL)
        """
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        self.cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self.lock = threading.RLock()
        self.stats = {"hits": 0, "misses": 0, "evictions": 0, "sets": 0}

    def get(self, key: str) -> Optional[Any]:
        """
        Get value from cache with LRU update.

        Args:
            key: Cache key

        Returns:
            Optional[Any]: Cached value or None if not found/expired
        """
        with self.lock:
            if key not in self.cache:
                self.stats["misses"] += 1
                return None

            entry = self.cache[key]

            # Check TTL
            if self.ttl_seconds and (time.time() - entry.timestamp) > self.ttl_seconds:
                del self.cache[key]
                self.stats["misses"] += 1
                return None

            # Update LRU and access count
            self.cache.move_to_end(key)
            entry.access_count += 1
            self.stats["hits"] += 1

            return entry.value

    def set(self, key: str, value: Any) -> None:
        """
        Set value in cache with LRU eviction.

        Args:
            key: Cache key
            value: Value to cache
        """
        with self.lock:
            # Remove existing entry if present
            if key in self.cache:
                del self.cache[key]

            # Evict if at capacity
            if len(self.cache) >= self.max_size:
                evicted_key, _ = self.cache.popitem(last=False)
                self.stats["evictions"] += 1

            # Add new entry
            entry = CacheEntry(value=value, timestamp=time.time(), access_count=0)
            self.cache[key] = entry
            self.cache.move_to_end(key)
            self.stats["sets"] += 1

    def delete(self, key: str) -> bool:
        """
        Delete entry from cache.

        Args:
            key: Cache key to delete

        Returns:
            bool: True if key was found and deleted
        """
        with self.lock:
            if key in self.cache:
                del self.cache[key]
                return True
            return False

    def clear(self) -> None:
        """Clear all cache entries."""
        with self.lock:
            self.cache.clear()

    def get_stats(self) -> Dict[str, Any]:
        """
        Get cache statistics.

        Returns:
            Dict with cache statistics
        """
        with self.lock:
            total_requests = self.stats["hits"] + self.stats["misses"]
            hit_rate = self.stats["hits"] / total_requests if total_requests > 0 else 0

            return {
                "size": len(self.cache),
                "max_size": self.max_size,
                "hits": self.stats["hits"],
                "misses": self.stats["misses"],
                "evictions": self.stats["evictions"],
                "sets": self.stats["sets"],
                "hit_rate": hit_rate,
                "ttl_seconds": self.ttl_seconds,
                "entries": list(self.cache.keys()),  # For debugging
            }

    def __contains__(self, key: str) -> bool:
        """Check if key exists in cache."""
        with self.lock:
            return key in self.cache

    def __len__(self) -> int:
        """Get current cache size."""
        with self.lock:
            return len(self.cache)


class AuditContext:
    """
    Context object for audit operations, replacing global state.

    This class encapsulates cache and marks in a single context object,
    enabling proper dependency injection and eliminating global state.
    """

    def __init__(self, cache: Optional[LRUCacheManager] = None):
        """
        Initialize audit context.

        Args:
            cache: Cache manager instance (creates new one if not provided)
        """
        self.cache = cache or LRUCacheManager(max_size=1000)
        self.marks: Set[str] = set()

    def clear(self) -> None:
        """Clear both cache and marks."""
        self.cache.clear()
        self.marks.clear()


# Global instances for backward compatibility
# DEPRECATED: These will be removed in a future version.
# Use AuditContext with dependency injection instead.
# Accessing these will trigger a deprecation warning in future versions.
cross_check_cache = LRUCacheManager(max_size=1000)
cross_check_marks = set()  # Use set for O(1) membership tests
