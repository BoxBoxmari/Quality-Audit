import pandas as pd

from quality_audit.utils.table_normalizer import TableNormalizer


class TestCodeColumnDetection:
    def test_multi_code_columns_detects_code_dot_variants(self):
        """Detector returns ALL code-like columns: Description, Code, Code.1, Code.2."""
        df = pd.DataFrame(
            columns=["Description", "Code", "Code.1", "Code.2", "2018", "2017"]
        )
        code_cols = TableNormalizer._detect_code_columns_with_synonyms(df)
        assert code_cols == [
            "Description",
            "Code",
            "Code.1",
            "Code.2",
        ], f"Expected ['Description','Code','Code.1','Code.2'], got {code_cols}"

    def test_detects_common_vietnamese_synonyms(self):
        """Test detection of common Vietnamese code aliases."""
        synonyms = ["Mã số", "MS", "Mã", "Số", "STT", "TT"]
        for syn in synonyms:
            df = pd.DataFrame(columns=[syn, "Nội dung", "Giá trị"])
            code_col = TableNormalizer._detect_code_column_with_synonyms(df)
            assert code_col == syn, f"Failed to detect synonym: {syn}"

    def test_detects_cp_pattern(self):
        """Test CP Vietnam pattern (often 'Mã số' or similar, possibly with special chars)."""
        # CP Vietnam sometimes has 'Mã số' combined with line break or extra spaces
        df = pd.DataFrame(columns=[" Mã  số ", "Nội dung", "Năm nay"])
        code_col = TableNormalizer._detect_code_column_with_synonyms(df)
        # Should parse clean 'Mã  số' from columns
        # Synonyms check lowers it. " mã  số " in synonyms?
        # Synonyms list has "mã số".
        # Strategy 2: Partial match. "mã số" in " mã  số ". lower() -> " mã  số "
        # "mã số" is NOT in " mã  số " because of double space!
        # This might be the bug.

        # We expect this to fail if strict substring check fails due to spacing.
        # But normalizer logic strips headers, so we expect stripped version if logic works.
        assert code_col == "Mã  số"

    def test_detects_cjcgv_pattern(self):
        """Test CJCGV pattern (often 'Thuyết minh' as ref, or 'Mã số' with formatting)."""
        # CJCGV might use "Thuyết minh" (Notes) as the reference column if Code is missing
        # Or mixed columns.
        df = pd.DataFrame(columns=["Thuyết minh", "Nội dung", "Số tiền"])
        # "thuyết minh" is likely not in synonyms list.
        # But 'Notes' is a synonym? List has "note".
        # If "Thuyết minh" is not in list, it might fail Strategy 1 & 2.
        # Strategy 3: Check content.
        df.loc[0] = ["V.01", "Cash", 100]
        df.loc[1] = ["V.02", "Deposit", 200]

        code_col = TableNormalizer._detect_code_column_with_synonyms(df)
        assert code_col == "Thuyết minh"

    def test_strategy_3_pattern_matching(self):
        """Test content-based detection when header is ambiguous."""
        df = pd.DataFrame(columns=["Unknown", "Desc", "Val"])
        df["Unknown"] = ["10", "11", "20", "30", "40"]  # Numeric codes

        code_col = TableNormalizer._detect_code_column_with_synonyms(df)
        assert code_col == "Unknown"

    def test_strategy_priority_code_over_notes(self):
        """Test that explicit Code synonyms are preferred over Notes when both exist."""
        # Scenario: Table has both "Mã số" and "Thuyết minh"
        df = pd.DataFrame(columns=["Thuyết minh", "Mã số", "Nội dung", "Số tiền"])
        # Should pick "Mã số" because it's higher in priority list
        code_col = TableNormalizer._detect_code_column_with_synonyms(df)
        assert code_col == "Mã số"
