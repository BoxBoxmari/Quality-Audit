"""
Regression tests for EquityValidator (tbl_030 / changes in owners' equity).

Covers: balance-at row detection, Total owners' equity column detection,
per-row sum vs toe comparison, PASS when correct, FAIL mark when mismatch
with expected/actual/delta in comment.
"""

import pandas as pd
import pytest

from quality_audit.core.validators.equity_validator import EquityValidator


class TestEquityValidator:
    """Tests for EquityValidator (tbl_030)."""

    @pytest.fixture
    def validator(self):
        return EquityValidator()

    def test_equity_happy_path_toe_column_matches(self, validator):
        """When sum(left_part) equals toe column for each row, status is PASS."""
        # Header row 0 must contain "Total owners' equity"; need >= 2 "Balance at" rows
        df = pd.DataFrame(
            [
                ["Label", "Amount", "Total owners' equity"],
                ["Balance at beginning", 100, 100],
                ["Balance at end", 100, 100],
            ]
        )
        result = validator.validate(df, table_context={})
        assert result.status.startswith("PASS")
        toe_marks = [m for m in result.marks if m.get("col") == 2]
        assert all(m.get("ok") for m in toe_marks)

    def test_equity_toe_mismatch_produces_fail_mark_with_expected_actual_delta(
        self, validator
    ):
        """When toe column differs from sum(left_part) beyond EQUITY_TOLERANCE_REL, one fail mark with expected/actual/delta."""
        # Use 100 vs 98 so rel_delta (2%) exceeds EQUITY_TOLERANCE_REL (1.2%)
        df = pd.DataFrame(
            [
                ["Label", "Amount", "Total owners' equity"],
                ["Balance at beginning", 100, 100],
                ["Balance at end", 100, 98],
            ]
        )
        result = validator.validate(df, table_context={})
        assert "FAIL" in result.status or not result.status.startswith("PASS")
        fail_marks = [m for m in result.marks if m.get("ok") is False]
        assert len(fail_marks) >= 1
        comment = next((m.get("comment") or "" for m in fail_marks), "")
        assert "100" in comment and "98" in comment
        assert "Sai lệch" in comment or "Δ" in comment or "-2" in comment

    def test_equity_insufficient_balance_at_returns_info(self, validator):
        """When fewer than 2 'Balance at' rows, return INFO and no marks."""
        df = pd.DataFrame(
            [
                ["Label", "Amount", "Total owners' equity"],
                ["Balance at beginning", 100, 100],
            ]
        )
        result = validator.validate(df, table_context={})
        assert "INFO" in result.status
        assert "không đủ dữ liệu" in result.status or "Balance at" in result.status

    def test_equity_with_two_balance_rows_does_not_early_info_when_order_is_odd(
        self, validator
    ):
        """With >=2 balance rows, validator should continue checks instead of early INFO."""
        df = pd.DataFrame(
            [
                ["Label", "Amount", "Total owners' equity"],
                ["Balance at end", 100, 100],
                ["Movement", 0, 0],
                ["Balance at beginning", 100, 100],
            ]
        )
        result = validator.validate(df, table_context={})
        assert result.rule_id != "EQUITY_INSUFFICIENT_BALANCE_ROWS"

    def test_equity_no_evidence_not_fail_flag_treats_zero_expected_as_ok(
        self, validator, monkeypatch
    ):
        """Phase 5 B1: When expected=0 (no numeric in slice) and actual!=0, flag ON → no FAIL."""
        # Slice first_data:idx2 has no numbers → expected=0; row idx2 has 100 → actual=100
        df = pd.DataFrame(
            [
                ["Label", "Amount", "Total owners' equity"],
                ["Balance at beginning", "", ""],  # no numeric → expected_series_2 = 0
                ["Balance at end", 50, 100],  # actual 50, 100
            ]
        )
        from quality_audit.config.feature_flags import get_feature_flags

        orig = get_feature_flags()

        # Default: flag off → can FAIL (expected 0 vs actual 50/100)
        result_off = validator.validate(df, table_context={})
        fail_marks_off = [m for m in result_off.marks if m.get("ok") is False]
        assert len(fail_marks_off) >= 1

        # Flag on: those cells become NO_EVIDENCE (ok=True), so no FAIL from them.
        # Fix first_data_idx=1 by disabling header infer so slice [1:2] = row 1 (all empty → expected=0).
        def flags_on():
            f = dict(orig)
            f["legacy_parity_mode"] = False
            f["equity_no_evidence_not_fail"] = True
            f["equity_header_infer"] = False
            return f

        monkeypatch.setattr(
            "quality_audit.core.validators.equity_validator.get_feature_flags",
            flags_on,
        )
        result_on = validator.validate(df, table_context={})
        no_evidence_marks = [
            m
            for m in result_on.marks
            if m.get("comment") and "NO_EVIDENCE" in (m.get("comment") or "")
        ]
        assert len(no_evidence_marks) >= 1
        assert all(m.get("ok") for m in no_evidence_marks)
        # With flag on, no FAIL from expected=0 vs actual!=0
        fail_marks_on = [m for m in result_on.marks if m.get("ok") is False]
        assert len(fail_marks_on) <= len(fail_marks_off)

    def test_equity_no_evidence_flag_is_ignored_in_parity_mode(
        self, validator, monkeypatch
    ):
        """In parity mode, equity_no_evidence_not_fail must not convert mismatch to NO_EVIDENCE."""
        df = pd.DataFrame(
            [
                ["Label", "Amount", "Total owners' equity"],
                ["Balance at beginning", "", ""],
                ["Balance at end", 50, 100],
            ]
        )
        from quality_audit.config.feature_flags import get_feature_flags

        orig = get_feature_flags()

        def flags_parity_on():
            f = dict(orig)
            f["legacy_parity_mode"] = True
            f["equity_no_evidence_not_fail"] = True
            f["equity_header_infer"] = False
            return f

        monkeypatch.setattr(
            "quality_audit.core.validators.equity_validator.get_feature_flags",
            flags_parity_on,
        )
        result = validator.validate(df, table_context={})
        no_evidence_marks = [
            m for m in result.marks if "NO_EVIDENCE" in (m.get("comment") or "")
        ]
        assert len(no_evidence_marks) == 0

    def test_equity_parity_mode_uses_strict_equality_not_rel_tolerance(
        self, validator, monkeypatch
    ):
        """Parity mode: small relative mismatch must still FAIL (legacy strict semantics)."""
        df = pd.DataFrame(
            [
                ["Label", "Amount", "Total owners' equity"],
                ["Balance at beginning", 1000, 1000],
                # Left-part sum = 1000, table value = 1008 (~0.79%): would pass with rel tolerance.
                ["Balance at end", 1000, 1008],
            ]
        )

        from quality_audit.config.feature_flags import get_feature_flags

        orig = get_feature_flags()

        def flags_parity_on():
            f = dict(orig)
            f["legacy_parity_mode"] = True
            return f

        monkeypatch.setattr(
            "quality_audit.core.validators.equity_validator.get_feature_flags",
            flags_parity_on,
        )
        result = validator.validate(df, table_context={})
        fail_marks = [m for m in result.marks if m.get("ok") is False]
        assert len(fail_marks) >= 1
        assert "FAIL" in result.status

    def test_equity_parity_third_balance_uses_second_balance_index_not_closing_index(
        self, validator, monkeypatch
    ):
        """Legacy parity: 'Balance at (thứ 3)' must use slice [balance_rows[1]:balance_rows[2])."""
        df = pd.DataFrame(
            [
                ["Label", "Amount"],
                ["Balance at beginning", 10],
                ["Movement", 20],
                ["Balance at period movement", 30],  # balance_rows[1]
                [
                    "Balance at period end",
                    31,
                ],  # balance_rows[2] -> expected should be 30
                ["Closing balance", 999],  # can bias closing_idx in modern classifier
            ]
        )
        from quality_audit.config.feature_flags import get_feature_flags

        orig = get_feature_flags()

        def flags_parity_on():
            f = dict(orig)
            f["legacy_parity_mode"] = True
            f["equity_header_infer"] = False
            return f

        monkeypatch.setattr(
            "quality_audit.core.validators.equity_validator.get_feature_flags",
            flags_parity_on,
        )
        result = validator.validate(df, table_context={})
        third_row_comments = [
            m.get("comment") or ""
            for m in result.marks
            if "HÀNG: Balance at (thứ 3)" in (m.get("comment") or "")
        ]
        assert any("Tính=30" in c for c in third_row_comments), third_row_comments

    def test_equity_parity_ignores_header_balance_at_text_for_balance_row_detection(
        self, validator, monkeypatch
    ):
        """Legacy parity: detect balance rows by first non-empty cell, not any cell in row."""
        df = pd.DataFrame(
            [
                ["Section", "Balance at beginning", "Balance at end", "Amount"],
                ["Balance at beginning", "", "", 100],
                ["Movement", "", "", 200],
                ["Balance at period movement", "", "", 300],  # idx2 expected row
                ["Balance at period end", "", "", 301],  # idx3 expected row
            ]
        )
        from quality_audit.config.feature_flags import get_feature_flags

        orig = get_feature_flags()

        def flags_parity_on():
            f = dict(orig)
            f["legacy_parity_mode"] = True
            f["equity_header_infer"] = False
            return f

        monkeypatch.setattr(
            "quality_audit.core.validators.equity_validator.get_feature_flags",
            flags_parity_on,
        )
        result = validator.validate(df, table_context={})
        third_row_comments = [
            m.get("comment") or ""
            for m in result.marks
            if "HÀNG: Balance at (thứ 3)" in (m.get("comment") or "")
        ]
        assert any(
            "Cột 4: Tính=300" in c for c in third_row_comments
        ), third_row_comments

    def test_equity_parity_does_not_extract_numbers_from_label_column(
        self, validator, monkeypatch
    ):
        """Legacy parity: label text like years/notes must not leak into numeric formula checks."""
        df = pd.DataFrame(
            [
                ["", "Share capital VND", "Retained profits VND", "Total VND"],
                ["", "", "", ""],
                ["Balance at 1 January 2017", 100, 300, 400],
                ["Net loss for the year", "-", -50, -50],
                ["", "", "", ""],
                ["Balance at 1 January 2018", 100, 250, 350],
                ["Net profit for the year", "-", 40, 40],
                ["Dividends (Note 23)", "-", -10, -10],
                ["", "", "", ""],
                ["Balance at 31 December 2018", 100, 280, 380],
            ]
        )
        from quality_audit.config.feature_flags import get_feature_flags

        orig = get_feature_flags()

        def flags_parity_on():
            f = dict(orig)
            f["legacy_parity_mode"] = True
            f["equity_header_infer"] = False
            return f

        monkeypatch.setattr(
            "quality_audit.core.validators.equity_validator.get_feature_flags",
            flags_parity_on,
        )
        result = validator.validate(df, table_context={})
        formula_fails = [
            m
            for m in result.marks
            if m.get("ok") is False
            and "HÀNG: Balance at (thứ 3) - Cột 1" in (m.get("comment") or "")
        ]
        assert formula_fails == [], formula_fails

    def test_equity_default_runtime_uses_anchor_roll_forward_not_legacy_bug(
        self, validator
    ):
        """Default runtime should pass anchor-based second interval roll-forward."""
        df = pd.DataFrame(
            [
                ["Label", "Amount"],
                ["Balance at beginning", 100],
                ["Movement phase 1", 20],
                ["Balance at period movement", 120],
                ["Movement phase 2", 30],
                ["Balance at end", 150],
            ]
        )
        result = validator.validate(df, table_context={})
        assert result.status.startswith("PASS"), result.status
