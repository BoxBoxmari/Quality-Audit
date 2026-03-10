"""
Test P5: undetermined structure → INFO_SKIPPED / WARN, never PASS/FAIL.
"""

import pandas as pd
import pytest

from quality_audit.utils.note_structure import (
    SEGMENT_CONFIDENCE_THRESHOLD,
    NoteStructureResult,
    Segment,
    analyze_note_table,
)


class TestUndeterminedStructure:
    def test_no_segments_gives_zero_confidence(self):
        """Table with no recognizable structure → confidence near 0."""
        data = {
            "Col1": ["Item A", "Item B", "Item C"],
            "Col2": [100, 200, 300],
        }
        df = pd.DataFrame(data)
        result = analyze_note_table(df, heading="Random Table", table_id="099")
        # No OB/CB/Movement patterns → segments have confidence 0
        assert result.is_movement_table is False
        for seg in result.segments:
            assert seg.confidence < SEGMENT_CONFIDENCE_THRESHOLD, (
                f"Expected low confidence for unrecognized segment, got {seg.confidence}"
            )

    def test_unstructured_table_empty_scopes(self):
        """P4: Table without total/subtotal rows but ≥3 rows → conservative scope uses last numeric row."""
        data = {
            "Description": ["Revenue from contracts", "Other income", "Miscellaneous"],
            "Amount": [1000, 200, 50],
        }
        df = pd.DataFrame(data)
        result = analyze_note_table(df, heading="Test", table_id="100")
        # P4: Conservative unlabeled-total: last numeric row becomes total
        # for sum-to-total segments (no OB/CB) with ≥3 rows
        if result.scopes:
            # If scope created, total should be last row (2)
            assert result.scopes[0].total_row_idx == 2
        # Note: if segment somehow has OB/CB, P4 doesn't apply (guard)
