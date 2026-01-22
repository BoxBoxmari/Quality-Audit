"""
Performance benchmark tests for Quality Audit operations.
"""

import time

from quality_audit.core.cache_manager import LRUCacheManager
from quality_audit.core.repositories.financial_data_repository import \
    FinancialDataRepository
from quality_audit.core.validators.balance_sheet_validator import \
    BalanceSheetValidator


class TestPerformanceBenchmarks:
    """Performance benchmark tests to measure improvements."""

    def test_vectorized_validation_performance(self):
        """Benchmark vectorized validation vs loop-based approach."""
        validator = BalanceSheetValidator()

        # Create large dataset
        num_accounts = 1000
        data = {}
        code_rowpos = {}
        for i in range(num_accounts):
            code = str(1000 + i)
            data[code] = (float(i * 100), float(i * 90))
            code_rowpos[code] = i

        header = ["code", "account_name", "2024", "2023"]
        rules = {"1000": [str(1000 + i) for i in range(100)]}

        # Measure vectorized performance
        start = time.time()
        issues, marks = validator._validate_balance_sheet_vectorized(
            data, code_rowpos, "2024", "2023", header, 0, rules
        )
        vectorized_time = time.time() - start

        # Vectorized should complete in reasonable time
        assert vectorized_time < 1.0, f"Vectorized validation took {vectorized_time}s"

    def test_cache_performance(self):
        """Benchmark cache operations."""
        cache = LRUCacheManager(max_size=1000)

        # Test cache set performance
        start = time.time()
        for i in range(1000):
            cache.set(f"key_{i}", (i * 100.0, i * 90.0))
        set_time = time.time() - start

        # Test cache get performance
        start = time.time()
        for i in range(1000):
            cache.get(f"key_{i}")
        get_time = time.time() - start

        # Both operations should be fast
        assert set_time < 0.5, f"Cache set took {set_time}s"
        assert get_time < 0.5, f"Cache get took {get_time}s"

    def test_repository_performance(self):
        """Benchmark repository operations."""
        cache = LRUCacheManager(max_size=1000)
        repo = FinancialDataRepository(cache)

        # Test bulk save performance
        start = time.time()
        for i in range(500):
            repo.save_balance_sheet_data(f"account_{i}", i * 100.0, i * 90.0)
        save_time = time.time() - start

        # Test bulk retrieve performance
        start = time.time()
        for i in range(500):
            repo.get_balance_sheet_data(f"account_{i}")
        retrieve_time = time.time() - start

        # Both should be fast
        assert save_time < 0.3, f"Repository save took {save_time}s"
        assert retrieve_time < 0.3, f"Repository retrieve took {retrieve_time}s"
