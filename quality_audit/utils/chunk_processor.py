"""
Chunk processing utilities for handling large DataFrames efficiently.

Provides memory-efficient processing of large tables by splitting them
into smaller chunks and managing garbage collection between chunks.
"""

import gc
from typing import Any, Callable, Iterator, List, Optional

import pandas as pd


class ChunkProcessor:
    """Process large DataFrames in chunks to manage memory efficiently."""

    DEFAULT_CHUNK_SIZE = 1000

    @staticmethod
    def chunk_dataframe(
        df: pd.DataFrame, chunk_size: int = DEFAULT_CHUNK_SIZE
    ) -> Iterator[pd.DataFrame]:
        """
        Split DataFrame into chunks of specified size.

        Args:
            df: DataFrame to chunk
            chunk_size: Number of rows per chunk (default: 1000)

        Yields:
            pd.DataFrame: Chunk of the original DataFrame
        """
        if df.empty:
            return

        total_rows = len(df)
        for start_idx in range(0, total_rows, chunk_size):
            end_idx = min(start_idx + chunk_size, total_rows)
            # Use .copy() to avoid view warnings and ensure memory safety
            chunk = df.iloc[start_idx:end_idx].copy()
            yield chunk

    @staticmethod
    def process_with_memory_limits(
        df: pd.DataFrame,
        processor_func: Callable[[pd.DataFrame], Any],
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        enable_gc: bool = True,
    ) -> List[Any]:
        """
        Process DataFrame in chunks with garbage collection between chunks.

        This method helps prevent memory exhaustion when processing very large tables
        by processing data in smaller chunks and explicitly freeing memory between chunks.

        Args:
            df: DataFrame to process
            processor_func: Function to apply to each chunk
            chunk_size: Number of rows per chunk (default: 1000)
            enable_gc: Whether to run garbage collection between chunks (default: True)

        Returns:
            List[Any]: List of results from processing each chunk
        """
        results = []
        chunk_count = 0

        for chunk in ChunkProcessor.chunk_dataframe(df, chunk_size):
            try:
                result = processor_func(chunk)
                results.append(result)
                chunk_count += 1

                # Force garbage collection between chunks to free memory
                if enable_gc:
                    gc.collect()

            except Exception as e:
                # Log error but continue processing other chunks
                error_msg = f"Error processing chunk {chunk_count}: {str(e)}"
                results.append({"error": error_msg, "chunk_index": chunk_count})
                if enable_gc:
                    gc.collect()

        return results

    @staticmethod
    def get_chunk_count(df: pd.DataFrame, chunk_size: int = DEFAULT_CHUNK_SIZE) -> int:
        """
        Calculate number of chunks needed for a DataFrame.

        Args:
            df: DataFrame to calculate chunks for
            chunk_size: Number of rows per chunk

        Returns:
            int: Number of chunks needed
        """
        if df.empty:
            return 0
        return (len(df) + chunk_size - 1) // chunk_size

    @staticmethod
    def should_use_chunking(
        df: pd.DataFrame, threshold: int = DEFAULT_CHUNK_SIZE
    ) -> bool:
        """
        Determine if chunking should be used for a DataFrame.

        Args:
            df: DataFrame to check
            threshold: Row count threshold for chunking (default: 1000)

        Returns:
            bool: True if DataFrame should be chunked
        """
        return len(df) > threshold

    @staticmethod
    def aggregate_chunk_results(
        results: List[Any],
        aggregation_func: Optional[Callable[[List[Any]], Any]] = None,
    ) -> Any:
        """
        Aggregate results from chunk processing.

        Args:
            results: List of results from processing chunks
            aggregation_func: Optional function to aggregate results.
                            If None, returns list as-is.

        Returns:
            Aggregated results or list of results
        """
        if aggregation_func:
            return aggregation_func(results)
        return results
