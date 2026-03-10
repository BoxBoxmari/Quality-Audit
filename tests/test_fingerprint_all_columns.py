"""
Regression test: fingerprinter must find codes in shifted columns (not just first 3).
Covers P2 fix: scan all columns.
"""

import pandas as pd
import pytest

from quality_audit.core.classification.structural_fingerprint import (
    StructuralFingerprinter,
)


class TestFingerprintAllColumns:
    @pytest.fixture
    def fingerprinter(self):
        return StructuralFingerprinter()

    def test_code_column_at_index_4_detected(self, fingerprinter):
        """Code column at index 4 (beyond old limit of 3) must be picked up."""
        rows = [
            ["Item A", 10000, 20000, 30000, "10"],
            ["Item B", 15000, 25000, 35000, "20"],
            ["Item C", 17500, 27500, 37500, "30"],
        ]
        df = pd.DataFrame(rows, columns=["Desc", "Y1", "Y2", "Y3", "Code"])
        fp = fingerprinter.extract(df)
        assert fp.found_codes, "Expected codes to be found at index 4"
        assert "10" in fp.found_codes
        assert "20" in fp.found_codes

    def test_code_column_at_index_0_still_works(self, fingerprinter):
        """Code column at index 0 still works after the change."""
        rows = [
            ["10", "Revenue", 1000],
            ["20", "COGS", 800],
            ["30", "Gross profit", 200],
        ]
        df = pd.DataFrame(rows, columns=["Code", "Description", "Amount"])
        fp = fingerprinter.extract(df)
        assert "10" in fp.found_codes
        assert "20" in fp.found_codes
        assert "30" in fp.found_codes

    def test_pure_numeric_amounts_not_treated_as_codes(self, fingerprinter):
        """Large numeric values (amounts) should not be picked up as codes."""
        rows = [
            ["Revenue", 1000000, 900000],
            ["COGS", 800000, 750000],
        ]
        df = pd.DataFrame(rows, columns=["Description", "2024", "2023"])
        fp = fingerprinter.extract(df)
        # 1000000 doesn't match _CODE_RE (^\\d{2,3}[a-zA-Z]?$)
        assert len(fp.found_codes) == 0, (
            f"Expected no codes from amounts, got {fp.found_codes}"
        )
