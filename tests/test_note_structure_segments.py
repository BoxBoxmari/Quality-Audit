"""
Tests for P4: NOTE structure engine — segments, scopes, row classification.
"""

import pandas as pd
import pytest

from quality_audit.utils.note_structure import (
    NoteMode,
    NoteStructureResult,
    NoteValidationMode,
    RowType,
    StructureStatus,
    _classify_row_type,
    analyze_note_table,
)


class TestRowClassification:
    def test_opening_balance(self):
        assert _classify_row_type("opening balance") == RowType.OPENING

    def test_closing_balance(self):
        assert _classify_row_type("closing balance") == RowType.CLOSING

    def test_movement_with_numeric(self):
        assert _classify_row_type("depreciation", has_numeric=True) == RowType.MOVEMENT

    def test_movement_without_numeric_becomes_section_header(self):
        """P4: Movement keyword + no numeric → SECTION_HEADER."""
        assert (
            _classify_row_type("depreciation", has_numeric=False)
            == RowType.SECTION_HEADER
        )

    def test_accumulated_depreciation_section_header(self):
        """P4: 'Accumulated depreciation' is accounting section header."""
        assert _classify_row_type("accumulated depreciation") == RowType.SECTION_HEADER

    def test_cost_section_header(self):
        """P4: 'Cost' is accounting section header."""
        assert _classify_row_type("cost") == RowType.SECTION_HEADER

    def test_net_book_value_section_header(self):
        """P4: 'Net book value' is accounting section header."""
        assert _classify_row_type("net book value") == RowType.SECTION_HEADER

    def test_total(self):
        assert _classify_row_type("Total") == RowType.TOTAL_LIKE

    def test_blank(self):
        assert _classify_row_type("", has_numeric=False) == RowType.BLANK
        assert _classify_row_type("", has_numeric=True) == RowType.OTHER


class TestNoteStructureSegments:
    def test_tangible_fixed_assets_three_segments(self):
        """Tangible fixed assets: Cost / Accumulated depreciation / NBV → 3 segments."""
        data = {
            "Description": [
                "Cost",  # 0: SECTION_HEADER
                "Opening balance",  # 1: OPENING
                "Additions",  # 2: MOVEMENT (has numeric)
                "Disposals",  # 3: MOVEMENT (has numeric)
                "Closing balance",  # 4: CLOSING
                "",  # 5: BLANK
                "Accumulated depreciation",  # 6: SECTION_HEADER
                "Opening balance",  # 7: OPENING
                "Depreciation charge",  # 8: MOVEMENT (has numeric)
                "Closing balance",  # 9: CLOSING
                "",  # 10: BLANK
                "Net book value",  # 11: SECTION_HEADER
                "Opening balance",  # 12: OPENING
                "Closing balance",  # 13: CLOSING
            ],
            "Amount": [
                None,
                1000,
                200,
                -50,
                1150,
                None,
                None,
                -300,
                -100,
                -400,
                None,
                None,
                700,
                750,
            ],
        }
        df = pd.DataFrame(data)
        result = analyze_note_table(df, heading="PPE", table_id="001")

        assert isinstance(result, NoteStructureResult)
        assert result.is_movement_table is True
        # P5: movement tables should surface MOVEMENT_ROLLFORWARD semantics
        assert result.mode == NoteMode.MOVEMENT_ROLLFORWARD
        assert result.structure_status == StructureStatus.STRUCTURE_OK
        # Phase 2 planner: movement tables must be classified as MOVEMENT_BY_ROWS
        assert result.validation_mode == NoteValidationMode.MOVEMENT_BY_ROWS
        # Structural confidence must come from segments; alignment from scopes
        assert result.confidence_struct == result.confidence
        assert result.confidence_alignment == 0.0
        # Should have at least 2 segments with OB+CB
        segments_with_ob_cb = [
            s
            for s in result.segments
            if s.ob_row_idx is not None and s.cb_row_idx is not None
        ]
        assert (
            len(segments_with_ob_cb) >= 2
        ), f"Expected >= 2 segments with OB+CB, got {len(segments_with_ob_cb)}"

    def test_no_total_like_row_gives_empty_scopes(self):
        """P4: Table without TOTAL_LIKE row → scopes=[]."""
        data = {
            "Description": [
                "Opening balance",
                "Additions",
                "Closing balance",
            ],
            "Amount": [1000, 200, 1200],
        }
        df = pd.DataFrame(data)
        result = analyze_note_table(df, heading="Test", table_id="002")
        # No TOTAL_LIKE row → scopes must be empty (not defaulting last row)
        assert (
            result.scopes == []
        ), f"Expected empty scopes without TOTAL_LIKE, got {result.scopes}"
        # P5: movement patterns are still detected even when we cannot find a
        # TOTAL_LIKE row, so this is treated as a movement rollforward without
        # scopes rather than a generic undetermined note.
        assert result.mode == NoteMode.MOVEMENT_ROLLFORWARD

    def test_table_with_total_row_creates_scope(self):
        """Table with explicit 'Total' row creates a scope."""
        data = {
            "Description": [
                "Item A",
                "Item B",
                "Total",
            ],
            "Amount": [100, 200, 300],
        }
        df = pd.DataFrame(data)
        result = analyze_note_table(df, heading="Test", table_id="003")
        assert len(result.scopes) >= 1, "Expected at least 1 scope with Total row"
        assert result.scopes[0].total_row_idx == 2

    def test_heading_normalized_cached(self):
        """P5: heading_normalized should store normalized heading text."""
        df = pd.DataFrame({"Description": ["Item A"], "Amount": [100]})
        heading = "  Business Costs By Element  "
        result = analyze_note_table(df, heading=heading, table_id="004")
        assert result.heading_normalized == "business costs by element"

    def test_tables_without_total_heading_skip_fallback_scopes(self):
        """P5: Headings in TABLES_WITHOUT_TOTAL must not create fallback scopes."""
        data = {
            "Description": ["Item A", "Item B", "Item C"],
            "Amount": [10, 20, 30],
        }
        df = pd.DataFrame(data)
        # Heading corresponds to constants.TABLES_WITHOUT_TOTAL entry
        heading = "Non-cash investing activities"
        result = analyze_note_table(df, heading=heading, table_id="005")
        assert (
            result.scopes == []
        ), f"Expected no scopes for NO_TOTAL heading, got {result.scopes}"
        # Phase 1/2 semantics: explicit NO_TOTAL heading → STRUCTURE_NO_TOTAL + LISTING_NO_TOTAL
        assert (
            result.structure_status == StructureStatus.STRUCTURE_NO_TOTAL
        ), f"Expected STRUCTURE_NO_TOTAL for heading {heading!r}, got {result.structure_status}"
        # Phase 2 planner: NO_TOTAL/listing headings must be classified as LISTING_NO_TOTAL
        assert (
            result.validation_mode == NoteValidationMode.LISTING_NO_TOTAL
        ), f"Expected LISTING_NO_TOTAL for heading {heading!r}, got {result.validation_mode}"

    def test_listing_heading_with_implicit_total_creates_scoped_totals(self):
        """
        Planner: listing-style heading with an implicit total row should be
        classified as LISTING_TOTALS with a planner-provided scope.

        This exercises the conservative _detect_listing_scopes_with_implicit_total
        helper, which only activates for listing headings that are NOT in
        TABLES_WITHOUT_TOTAL and have a corroborated implicit total.
        """
        data = {
            "Description": [
                "Counterparty A",
                "Counterparty B",
                "",  # implicit total row (blank label)
            ],
            "Amount": [10, 20, 30],
        }
        df = pd.DataFrame(data)
        # Heading chosen to match _LISTING_HEADING_RE but not appear in
        # TABLES_WITHOUT_TOTAL.
        heading = "Related parties"
        result = analyze_note_table(df, heading=heading, table_id="LISTING_001")

        assert (
            result.validation_mode == NoteValidationMode.LISTING_TOTALS
        ), f"Expected LISTING_TOTALS for heading {heading!r}, got {result.validation_mode}"
        assert (
            result.scopes
        ), "Expected at least one scope for implicit total listing table"
        scope = result.scopes[0]
        assert scope.total_row_idx == 2
        assert scope.detail_rows == [0, 1]

    def test_movement_by_columns_detection_and_plan(self):
        """Planner: detect simple movement-by-columns layout from column headers."""
        data = {
            "Opening balance": [100, 200],
            "Increase": [50, 0],
            "Decrease": [0, 20],
            "Closing balance": [150, 180],
        }
        df = pd.DataFrame(data)
        result = analyze_note_table(
            df, heading="Movement by columns", table_id="MBC_001"
        )

        assert isinstance(result, NoteStructureResult)
        assert (
            result.validation_mode == NoteValidationMode.MOVEMENT_BY_COLUMNS
        ), f"Expected MOVEMENT_BY_COLUMNS, got {result.validation_mode}"
        plan = result.note_validation_plan
        assert (
            plan is not None
        ), "Expected a note_validation_plan payload for MOVEMENT_BY_COLUMNS"
        assert plan.get("ob_col") == "Opening balance"
        assert plan.get("cb_col") == "Closing balance"
        assert plan.get("movement_cols") == ["Increase", "Decrease"]
