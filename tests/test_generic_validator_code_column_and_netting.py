import pandas as pd

from quality_audit.core.validators.generic_validator import GenericTableValidator


class TestGenericValidatorCodeColumnExclusion:
    def test_convert_to_numeric_df_excluding_code_leaves_code_untouched(self):
        df = pd.DataFrame(
            {
                "Code": ["10", "20", "30"],
                "Amount CY": ["100", "200", "300"],
                "Amount PY": ["90", "180", "270"],
            }
        )

        validator = GenericTableValidator()
        df_numeric = validator._convert_to_numeric_df_excluding_code(
            df, code_col="Code"
        )

        # Code column should remain as original strings
        assert list(df_numeric["Code"]) == ["10", "20", "30"]
        assert not pd.api.types.is_numeric_dtype(df_numeric["Code"])
        # Other columns should be numeric
        assert df_numeric["Amount CY"].tolist() == [100.0, 200.0, 300.0]
        assert df_numeric["Amount PY"].tolist() == [90.0, 180.0, 270.0]
        assert pd.api.types.is_numeric_dtype(df_numeric["Amount CY"])
        assert pd.api.types.is_numeric_dtype(df_numeric["Amount PY"])

    def test_convert_to_numeric_df_excluding_multiple_code_columns(self):
        """Exclude Code, Code.1, Code.2 from numeric conversion; only amount columns become numeric."""
        df = pd.DataFrame(
            {
                "Description": ["A", "B", "Total"],
                "Code": ["7", "8", ""],
                "Code.1": ["10", "11", ""],
                "Code.2": ["9", "9", ""],
                "2018": ["100", "200", "300"],
                "2017": ["90", "180", "270"],
            }
        )
        validator = GenericTableValidator()
        df_numeric = validator._convert_to_numeric_df_excluding_code(
            df, code_cols=["Code", "Code.1", "Code.2"]
        )
        # Code columns stay as strings
        assert list(df_numeric["Code"]) == ["7", "8", ""]
        assert list(df_numeric["Code.1"]) == ["10", "11", ""]
        assert list(df_numeric["Code.2"]) == ["9", "9", ""]
        assert not pd.api.types.is_numeric_dtype(df_numeric["Code"])
        assert not pd.api.types.is_numeric_dtype(df_numeric["Code.1"])
        assert not pd.api.types.is_numeric_dtype(df_numeric["Code.2"])
        # Amount columns numeric
        assert df_numeric["2018"].tolist() == [100.0, 200.0, 300.0]
        assert df_numeric["2017"].tolist() == [90.0, 180.0, 270.0]
        assert pd.api.types.is_numeric_dtype(df_numeric["2018"])
        assert pd.api.types.is_numeric_dtype(df_numeric["2017"])

    def test_column_totals_row_sum_excludes_all_code_columns(self):
        """Row sum for 'CỘT TỔNG' must not include Code/Code.1/Code.2; only amount columns."""
        # One data row + one total row; total row has 8 in amount, code columns 7+28 would inflate
        df = pd.DataFrame(
            {
                "Desc": ["Line 1", "Tổng cộng"],
                "Code": ["7", ""],
                "Code.1": ["28", ""],
                "2018": ["8", "8"],
                "2017": ["8", "8"],
            }
        )
        validator = GenericTableValidator()
        result = validator.validate(df, heading="Bảng cân đối kế toán")
        # Should not produce a mark like "Tính lại = 43" (7+28+8); expected "Tính lại = 8"
        # So either PASS or marks must not reference sum including code columns
        for m in result.marks:
            comment = str(m.get("comment", ""))
            if "Tính lại" in comment:
                # If there is a recalculation message, value must be 8 not 43
                assert "43" not in str(m), (
                    "Row sum must exclude code columns (7+28+8=43)"
                )

    def test_code_column_not_used_in_row_total_marks(self):
        df = pd.DataFrame(
            {
                "Code": ["10", "20", "Total"],
                "Amount": [100.0, 200.0, 300.0],
            }
        )

        validator = GenericTableValidator()
        result = validator.validate(df, heading="Test table")

        # Any marks produced should not target the Code column (index 0)
        assert all(m["col"] != 0 for m in result.marks)


class TestGenericValidatorNettingStructure:
    def test_netting_structure_detects_adjacent_total_less_net(self):
        df = pd.DataFrame(
            {
                "Desc": [
                    "Total income",
                    "Less: expenses",
                    "Net income",
                    "Other row",
                ],
                "CY": [1000.0, 200.0, 800.0, 10.0],
                "PY": [900.0, 100.0, 800.0, 5.0],
            }
        )

        validator = GenericTableValidator()
        structure = validator._detect_netting_structure(df)

        assert structure is not None
        assert set(structure.keys()) == {"total", "less", "net"}

    def test_netting_structure_detects_total_less_net_separated_by_12_rows(self):
        """R4: Total/Less/Net within 15 rows (relaxed adjacency) still detected."""
        desc = (
            ["Total revenue"]
            + [f"Line {i}" for i in range(1, 12)]
            + ["Less: deductions", "Net revenue"]
        )
        cy = [10000.0] + [0.0] * 11 + [1000.0, 9000.0]
        py = [9000.0] + [0.0] * 11 + [800.0, 8200.0]
        df = pd.DataFrame({"Desc": desc, "CY": cy, "PY": py})

        validator = GenericTableValidator()
        structure = validator._detect_netting_structure(df)

        assert structure is not None
        assert set(structure.keys()) == {"total", "less", "net"}
        assert structure["total"] == 0
        assert structure["less"] == 12
        assert structure["net"] == 13

    def test_netting_table_skips_grand_total_sum_validation(self):
        """R4: When netting is detected, block-sum/total-sum path is skipped (no double-validate)."""
        df = pd.DataFrame(
            {
                "Desc": ["Total income", "Less: expenses", "Net income"],
                "CY": [1000.0, -200.0, 800.0],
                "PY": [900.0, -100.0, 800.0],
            }
        )
        df_numeric = df.copy()
        marks = []
        issues = []

        validator = GenericTableValidator()
        validator._validate_row_totals(
            df=df,
            df_numeric=df_numeric,
            total_row_idx=0,
            code_col="Desc",
            heading_lower="desc",
            marks=marks,
            issues=issues,
            cross_ref_marks=[],
            code_cols=["Desc"],
            amount_cols=None,
        )

        netting_marks = [m for m in marks if m.get("rule_id") == "NETTING_VALIDATION"]
        assert len(netting_marks) >= 1
        grand_total_marks = [
            m
            for m in marks
            if m.get("comment")
            and ("Tổng chi tiết" in m["comment"] or "Tính lại" in m["comment"])
        ]
        assert len(grand_total_marks) == 0
