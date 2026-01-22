"""
Unit tests for ChunkProcessor utility.
"""

import pandas as pd

from quality_audit.utils.chunk_processor import ChunkProcessor


class TestChunkProcessor:
    """Test cases for ChunkProcessor."""

    def test_chunk_dataframe_empty(self):
        """Test chunking empty DataFrame."""
        df = pd.DataFrame()
        chunks = list(ChunkProcessor.chunk_dataframe(df, chunk_size=1000))
        assert len(chunks) == 0

    def test_chunk_dataframe_small(self):
        """Test chunking small DataFrame (smaller than chunk size)."""
        df = pd.DataFrame({"col1": range(100), "col2": range(100, 200)})
        chunks = list(ChunkProcessor.chunk_dataframe(df, chunk_size=1000))
        assert len(chunks) == 1
        assert len(chunks[0]) == 100
        pd.testing.assert_frame_equal(chunks[0], df)

    def test_chunk_dataframe_large(self):
        """Test chunking large DataFrame (multiple chunks)."""
        df = pd.DataFrame({"col1": range(2500), "col2": range(2500, 5000)})
        chunks = list(ChunkProcessor.chunk_dataframe(df, chunk_size=1000))
        assert len(chunks) == 3
        assert len(chunks[0]) == 1000
        assert len(chunks[1]) == 1000
        assert len(chunks[2]) == 500

    def test_chunk_dataframe_custom_size(self):
        """Test chunking with custom chunk size."""
        df = pd.DataFrame({"col1": range(1000), "col2": range(1000, 2000)})
        chunks = list(ChunkProcessor.chunk_dataframe(df, chunk_size=250))
        assert len(chunks) == 4
        for chunk in chunks:
            assert len(chunk) == 250

    def test_process_with_memory_limits(self):
        """Test processing with memory limits and GC."""
        df = pd.DataFrame({"col1": range(2500), "col2": range(2500, 5000)})

        def processor_func(chunk):
            return {"rows": len(chunk), "sum": chunk["col1"].sum()}

        results = ChunkProcessor.process_with_memory_limits(
            df, processor_func, chunk_size=1000, enable_gc=True
        )

        assert len(results) == 3
        assert results[0]["rows"] == 1000
        assert results[1]["rows"] == 1000
        assert results[2]["rows"] == 500

    def test_process_with_memory_limits_no_gc(self):
        """Test processing without GC."""
        df = pd.DataFrame({"col1": range(500), "col2": range(500, 1000)})

        def processor_func(chunk):
            return len(chunk)

        results = ChunkProcessor.process_with_memory_limits(
            df, processor_func, chunk_size=200, enable_gc=False
        )

        assert len(results) == 3
        assert sum(results) == 500

    def test_process_with_memory_limits_error_handling(self):
        """Test error handling in chunk processing."""
        df = pd.DataFrame({"col1": range(1000), "col2": range(1000, 2000)})

        def processor_func(chunk):
            if len(chunk) > 500:
                raise ValueError("Chunk too large")
            return len(chunk)

        results = ChunkProcessor.process_with_memory_limits(
            df, processor_func, chunk_size=600, enable_gc=True
        )

        # Should have results for all chunks, with error in first chunk
        assert len(results) == 2
        assert "error" in results[0]

    def test_get_chunk_count(self):
        """Test chunk count calculation."""
        df = pd.DataFrame({"col1": range(2500)})
        count = ChunkProcessor.get_chunk_count(df, chunk_size=1000)
        assert count == 3

    def test_get_chunk_count_empty(self):
        """Test chunk count for empty DataFrame."""
        df = pd.DataFrame()
        count = ChunkProcessor.get_chunk_count(df, chunk_size=1000)
        assert count == 0

    def test_should_use_chunking(self):
        """Test chunking threshold detection."""
        df_small = pd.DataFrame({"col1": range(500)})
        df_large = pd.DataFrame({"col1": range(1500)})

        assert not ChunkProcessor.should_use_chunking(df_small, threshold=1000)
        assert ChunkProcessor.should_use_chunking(df_large, threshold=1000)

    def test_aggregate_chunk_results(self):
        """Test result aggregation."""
        results = [{"count": 10}, {"count": 20}, {"count": 30}]

        # Without aggregation function
        aggregated = ChunkProcessor.aggregate_chunk_results(results)
        assert aggregated == results

        # With aggregation function
        def sum_counts(results):
            return sum(r["count"] for r in results)

        aggregated = ChunkProcessor.aggregate_chunk_results(results, sum_counts)
        assert aggregated == 60
