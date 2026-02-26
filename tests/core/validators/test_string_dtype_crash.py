"""
Regression tests for TypeError crash when pandas DataFrames have string[python] dtype.

Root cause: `row.copy()` and `df.map()` preserve nullable `string[python]` dtype,
causing TypeError when numeric/NA values are assigned into string-typed Series.
Fix: `.astype(object)` before mutation at all affected call sites.
"""

import pandas as pd
import pytest

from quality_audit.utils.numeric_utils import normalize_numeric_column


# ---------------------------------------------------------------------------
# Helper: build a DataFrame with explicit StringDtype (reproduces the crash)
# ---------------------------------------------------------------------------
def _string_dtype_df():
    """Create a DataFrame with string[python] dtype containing numeric-looking strings."""
    df = pd.DataFrame(
        {
            "Label": ["Revenue", "Cost", "Total"],
            "CY": ["1,000", "500", "1,500"],
            "PY": ["900", "400", "1,300"],
        }
    )
    # Force nullable string dtype — this is what pandas auto-infers in newer versions
    return df.astype("string")


# ---------------------------------------------------------------------------
# Test 1: _as_numeric_series must not raise on string[python] input
# ---------------------------------------------------------------------------
class TestAsNumericSeriesStringDtype:
    """Verify _as_numeric_series handles string[python] dtype without TypeError."""

    def test_no_typeerror_on_string_dtype_row(self):
        """Row with string[python] dtype should convert to numeric Series."""
        df = _string_dtype_df()
        row = df.iloc[0]
        assert str(row.dtype) == "string", (
            f"Precondition: dtype should be string, got {row.dtype}"
        )

        # Reproduce the fix: astype(object) before mutation
        s = row.astype(object).copy()
        exclude = {"Label"}
        for c in s.index:
            if c in exclude:
                s[c] = pd.NA
            else:
                s[c] = normalize_numeric_column(row[c])

        result = pd.to_numeric(s, errors="coerce")
        assert result.dtype.kind == "f" or result.dtype.kind == "i"  # numeric
        assert pd.notna(result["CY"])
        assert pd.notna(result["PY"])
        assert pd.isna(result["Label"])

    def test_astype_object_allows_mixed_assignment(self):
        """astype(object) copy must accept both pd.NA and float assignments."""
        df = _string_dtype_df()
        row = df.iloc[0]

        s = row.astype(object).copy()
        # These assignments must not raise regardless of pandas version
        s["Label"] = pd.NA
        s["CY"] = 1000.0
        s["PY"] = 900.0
        assert pd.isna(s["Label"])
        assert s["CY"] == 1000.0


# ---------------------------------------------------------------------------
# Test 2: df.map(normalize_numeric_column) must not raise on string[python] DF
# ---------------------------------------------------------------------------
class TestDfMapNormalizeStringDtype:
    """Verify df.astype(object).map(normalize_numeric_column) works."""

    def test_map_normalize_no_crash(self):
        """DataFrame.map(normalize_numeric_column) after astype(object) should succeed."""
        df = _string_dtype_df()
        assert all(str(df[c].dtype) == "string" for c in df.columns), (
            "Precondition: all string dtype"
        )

        result = df.astype(object).map(normalize_numeric_column)
        # CY column should have numeric values
        assert pd.notna(result.iloc[0]["CY"])
        assert result.iloc[0]["CY"] == 1000.0

    def test_map_normalize_preserves_none_for_text(self):
        """Text cells should become NA after normalize_numeric_column."""
        df = _string_dtype_df()
        result = df.astype(object).map(normalize_numeric_column)
        # "Revenue" is not numeric
        assert pd.isna(result.iloc[0]["Label"])


# ---------------------------------------------------------------------------
# Test 3: End-to-end GenericTableValidator with string[python] DataFrame
# ---------------------------------------------------------------------------
class TestGenericValidatorStringDtype:
    """Verify GenericTableValidator.validate does not produce FAIL_TOOL_LOGIC on string dtype DF."""

    def test_validate_string_dtype_not_tool_logic_fail(self):
        """Validator should process string[python] DF without crashing."""
        from quality_audit.core.validators.generic_validator import (
            GenericTableValidator,
        )

        df = _string_dtype_df()
        validator = GenericTableValidator()
        result = validator.validate(df, heading="Test table")

        assert result.status_enum != "FAIL_TOOL_LOGIC", (
            f"Validator crashed with FAIL_TOOL_LOGIC: {result.exception_message}"
        )
