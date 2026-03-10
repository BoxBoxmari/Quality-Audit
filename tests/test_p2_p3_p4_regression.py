"""Tests for P2: no-blank segment split, P3: NBV derived skip, P4: tax scope."""

import pandas as pd
import pytest

from quality_audit.utils.note_structure import (
    RowType,
    _classify_row_type,
    _split_segments,
    _detect_scopes,
    analyze_note_table,
    Segment,
)


class TestNoBlankSegmentSplit:
    """P2 — BLANK rows inside a segment do NOT split it."""

    def test_blank_between_ob_and_cb_does_not_split(self):
        """A blank spacer row between OB and CB should be absorbed, not cause a split."""
        row_types = [
            RowType.OPENING,  # row 0: "Opening balance"
            RowType.MOVEMENT,  # row 1: "Additions"
            RowType.BLANK,  # row 2: spacer
            RowType.MOVEMENT,  # row 3: "Disposals"
            RowType.CLOSING,  # row 4: "Closing balance"
        ]
        df = pd.DataFrame(
            {
                "Label": ["OB", "Add", "", "Disp", "CB"],
                "Amount": [100, 50, None, -30, 120],
            }
        )
        segments = _split_segments(df, row_types, "Label")
        # P2: All rows should be in ONE segment (no blank-split)
        assert len(segments) == 1, f"Expected 1 segment but got {len(segments)}"
        seg = segments[0]
        assert seg.ob_row_idx == 0
        assert seg.cb_row_idx == 4
        assert seg.movement_rows == [1, 3]
        assert seg.confidence == 1.0

    def test_section_header_still_splits(self):
        """SECTION_HEADER rows should still split segments."""
        row_types = [
            RowType.SECTION_HEADER,  # row 0: "Cost"
            RowType.OPENING,  # row 1
            RowType.MOVEMENT,  # row 2
            RowType.CLOSING,  # row 3
            RowType.SECTION_HEADER,  # row 4: "Accumulated depreciation"
            RowType.OPENING,  # row 5
            RowType.MOVEMENT,  # row 6
            RowType.CLOSING,  # row 7
        ]
        df = pd.DataFrame(
            {
                "Label": ["Cost", "OB", "Add", "CB", "Accum dep", "OB", "Dep", "CB"],
                "Amount": [None, 100, 50, 150, None, -20, -10, -30],
            }
        )
        segments = _split_segments(df, row_types, "Label")
        assert len(segments) >= 2


class TestNBVDerivedSkip:
    """P3 — NBV / carrying amount segments skip roll-forward."""

    def test_nbv_segment_emits_info_not_fail(self):
        from quality_audit.core.rules.movement_equation import MovementEquationRule
        from quality_audit.core.materiality import MaterialityEngine
        from quality_audit.utils.note_structure import Segment

        rule = MovementEquationRule()
        mat = MaterialityEngine()
        # Fake segment named "net book value"
        seg = Segment(
            start_row=0,
            end_row=3,
            ob_row_idx=0,
            cb_row_idx=2,
            movement_rows=[1],
            confidence=1.0,
            segment_name="net book value",
        )
        df = pd.DataFrame(
            {
                "Amount": [100, -30, 70],
            }
        )
        evidence = rule.evaluate(
            df,
            materiality=mat,
            table_type="GENERIC_NOTE",
            table_id="017",
            amount_cols=["Amount"],
            segments=[seg],
        )
        # P3: NBV segment should NOT produce FAIL — it should skip roll-forward
        for ev in evidence:
            assert (
                ev.severity.name != "MAJOR" or ev.metadata.get("nbv_derived") is True
            ), f"NBV segment should not FAIL: {ev.assertion_text}"
        # Should have at least one evidence mentioning "derived"
        nbv_evs = [e for e in evidence if e.metadata.get("nbv_derived")]
        assert len(nbv_evs) >= 1, "Expected NBV derived evidence"


class TestTaxScopeBaselineExclusion:
    """P4 — Baseline rows excluded from sum blocks, conservative unlabeled total."""

    def test_accounting_profit_excluded_from_scope(self):
        """'Accounting profit before tax' should not be included in detail_rows."""
        row_types = [
            RowType.OTHER,  # row 0: "Accounting profit before tax"
            RowType.OTHER,  # row 1: "Tax at statutory rate"
            RowType.OTHER,  # row 2: "Non-deductible expenses"
            RowType.OTHER,  # row 3: "Tax exempt income"
            RowType.OTHER,  # row 4: "Income tax expense" (unlabeled total — last numeric row)
        ]
        df = pd.DataFrame(
            {
                "Description": [
                    "Accounting profit before tax",
                    "Tax at statutory rate",
                    "Non-deductible expenses",
                    "Tax exempt income",
                    "Income tax expense",
                ],
                "Amount": [1000, 200, 50, -30, 220],
            }
        )
        seg = Segment(
            start_row=0,
            end_row=5,
            ob_row_idx=None,
            cb_row_idx=None,
            movement_rows=[],
            confidence=0.0,
        )
        scopes = _detect_scopes(df, row_types, [seg], amount_cols=["Amount"])
        if scopes:
            scope = scopes[0]
            # Row 0 ("Accounting profit before tax") must NOT be in detail_rows
            assert 0 not in scope.detail_rows, (
                f"Baseline row 'Accounting profit' should be excluded but found in {scope.detail_rows}"
            )
