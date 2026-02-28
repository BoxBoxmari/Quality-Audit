"""
LRU Cache Manager for cross-checking data with memory bounds and performance monitoring.
"""

import threading
import time
from collections import OrderedDict
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Set, Tuple

from quality_audit.config.tax_rate import TaxRateConfig


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

    def __contains__(self, key: object) -> bool:
        """
        Support `key in cache` checks for tests and ergonomics.
        Respects TTL eviction semantics (expired entries are treated as missing).
        """
        if not isinstance(key, str):
            return False
        # Use get() to apply TTL behavior without updating LRU stats too heavily.
        # This is acceptable for membership checks in this project.
        return self.get(key) is not None

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

    def __len__(self) -> int:
        """Get current cache size."""
        with self.lock:
            return len(self.cache)


class AuditContext:
    """
    Context object for audit operations, replacing global state.

    This class encapsulates cache and marks in a single context object,
    enabling proper dependency injection and eliminating global state.

    Concurrent-safe: Uses contextvars for run-specific state (filename, marks).
    """

    _current_filename_var: ContextVar[Optional[str]] = ContextVar(
        "current_filename", default=None
    )
    _marks_var: ContextVar[Optional[Set[str]]] = ContextVar("marks", default=None)
    _last_classification_context_var: ContextVar[Optional[Dict[str, Any]]] = ContextVar(
        "last_classification_context", default=None
    )
    _last_normalization_metadata_var: ContextVar[Optional[Dict[str, Any]]] = ContextVar(
        "last_normalization_metadata", default=None
    )
    _last_total_row_metadata_var: ContextVar[Optional[Dict[str, Any]]] = ContextVar(
        "last_total_row_metadata", default=None
    )
    _cash_flow_registry_var: ContextVar[Optional[Dict[str, Tuple[float, float]]]] = (
        ContextVar("cash_flow_registry", default=None)
    )

    def __init__(
        self,
        cache: Optional[LRUCacheManager] = None,
        tax_rate_config: Optional[TaxRateConfig] = None,
        base_path: Optional[Path] = None,
    ):
        """
        Initialize audit context.

        Args:
            cache: Cache manager instance (creates new one if not provided)
            tax_rate_config: Configuration for tax rates
            base_path: Base path for resolving relative paths
        """
        self.cache = cache or LRUCacheManager(max_size=1000)
        self.tax_rate_config = tax_rate_config
        self.base_path = base_path

    @property
    def current_filename(self) -> Optional[str]:
        """Get the current filename for this task."""
        return self._current_filename_var.get()

    @current_filename.setter
    def current_filename(self, value: Optional[str]):
        """Set the current filename for this task."""
        self._current_filename_var.set(value)

    @property
    def marks(self) -> Set[str]:
        """Get the cross-check marks for this task."""
        m = self._marks_var.get()
        if m is None:
            m = set()
            self._marks_var.set(m)
        return m

    def get_last_classification_context(self) -> Optional[Dict[str, Any]]:
        """Get last classification result context (set by ValidatorFactory)."""
        return self._last_classification_context_var.get()

    def set_last_classification_context(self, ctx: Optional[Dict[str, Any]]) -> None:
        """Set last classification result context for observability."""
        self._last_classification_context_var.set(ctx)

    def get_last_normalization_metadata(self) -> Optional[Dict[str, Any]]:
        """
        Get last table normalization metadata.

        This is populated by validators via BaseValidator._normalize_table_with_metadata
        to support per-table observability/logging without changing validator behaviour.
        """
        return self._last_normalization_metadata_var.get()

    def set_last_normalization_metadata(
        self, metadata: Optional[Dict[str, Any]]
    ) -> None:
        """Set last table normalization metadata for observability."""
        self._last_normalization_metadata_var.set(metadata)

    def get_last_total_row_metadata(self) -> Optional[Dict[str, Any]]:
        """
        Get last total-row selection metadata.

        This is populated by BaseValidator._find_total_row to record which strategy
        was used to choose the total row (RowClassifier, safe_total_row_selection, legacy).
        """
        return self._last_total_row_metadata_var.get()

    def set_last_total_row_metadata(self, metadata: Optional[Dict[str, Any]]) -> None:
        """Set last total-row selection metadata for observability."""
        self._last_total_row_metadata_var.set(metadata)

    @property
    def cash_flow_registry(self) -> Dict[str, Tuple[float, float]]:
        """
        Document-level registry for cash flow codes: code -> (current_year, prior_year).

        Used when cashflow_cross_table_context feature flag is enabled to aggregate
        values across all Cash Flow tables in a document.
        """
        reg = self._cash_flow_registry_var.get()
        if reg is None:
            reg = {}
            self._cash_flow_registry_var.set(reg)
        return reg

    @cash_flow_registry.setter
    def cash_flow_registry(self, value: Dict[str, Tuple[float, float]]) -> None:
        """Set the document-level cash flow registry."""
        self._cash_flow_registry_var.set(value)

    def clear(self) -> None:
        """
        Clear run-specific state for this task.

        Note: shared cache is NOT cleared here to prevent interference
        in concurrent batch processing.
        """
        self._marks_var.set(set())
        self._current_filename_var.set(None)
        self._last_classification_context_var.set(None)
        self._cash_flow_registry_var.set(None)
        self._last_normalization_metadata_var.set(None)
        self._last_total_row_metadata_var.set(None)


import warnings


class DeprecatedLRUCacheManager(LRUCacheManager):
    """Proxy for cross_check_cache that logs a deprecation warning on first use."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._warned = False

    def _warn(self):
        if not self._warned:
            warnings.warn(
                "cross_check_cache global is deprecated and will be removed in v3.0.0. "
                "Use AuditContext with dependency injection instead.",
                DeprecationWarning,
                stacklevel=3,
            )
            self._warned = True

    def get(self, *args, **kwargs):
        self._warn()
        return super().get(*args, **kwargs)

    def set(self, *args, **kwargs):
        self._warn()
        return super().set(*args, **kwargs)


# Global instances for backward compatibility
cross_check_cache = DeprecatedLRUCacheManager(max_size=1000)
# Deprecated: Use AuditContext.marks instead. This global set is maintained for backward compatibility only.
cross_check_marks: Set[str] = set()
