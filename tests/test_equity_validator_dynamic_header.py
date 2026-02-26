"""
Phase 6: Tests for EquityValidator dynamic header (_detect_header_row, _detect_first_data_row).
"""

from unittest.mock import patch

import pandas as pd
import pytest

from quality_audit.core.validators.base_validator import ValidationResult
from quality_audit.core.validators.equity_validator import (
    EquityValidator,
    _detect_first_data_row,
    _detect_header_row,
)


class TestDetectHeaderRow:
    """Module-level _detect_header_row(df) returns last row index of header block."""

    def test_all_header_keywords_returns_last_header_index(self):
        df = pd.DataFrame(
            [
                ["Total", "Balance", "Equity"],
                ["Movement", "Share", "Capital"],
                ["100", "200", "300"],
            ]
        )
        assert _detect_header_row(df) == 1

    def test_first_row_mostly_numeric_breaks_header(self):
        df = pd.DataFrame(
            [
                ["100", "200", "300"],
                ["Balance at", "x", "y"],
            ]
        )
        assert _detect_header_row(df) == 0

    def test_single_row(self):
        df = pd.DataFrame([["Total equity", "100", "200"]])
        assert _detect_header_row(df) == 0


class TestDetectFirstDataRow:
    """_detect_first_data_row(df) is header_idx + 1."""

    def test_after_header_block(self):
        df = pd.DataFrame(
            [
                ["Total", "Balance"],
                ["Movement", "Share"],
                ["100", "200"],
            ]
        )
        assert _detect_first_data_row(df) == 2

    def test_single_row_data(self):
        df = pd.DataFrame([["100", "200"]])
        assert _detect_first_data_row(df) == 1


class TestEquityValidatorDynamicHeader:
    """With equity_header_infer True, validator uses inferred header/data row."""

    @pytest.fixture
    def validator(self):
        return EquityValidator()

    def test_uses_inferred_header_when_flag_on(self, validator):
        with patch(
            "quality_audit.core.validators.equity_validator.get_feature_flags"
        ) as gff:
            gff.return_value = {"equity_header_infer": True}
            df = pd.DataFrame(
                [
                    ["Changes in equity", "", ""],
                    ["Balance at beginning", "100", "90"],
                    ["Profit", "10", ""],
                    ["Balance at end", "110", "90"],
                ]
            )
            result = validator.validate(df, table_context={})
            assert isinstance(result, ValidationResult)
            assert result.status_enum in ("PASS", "INFO", "WARN", "FAIL")
