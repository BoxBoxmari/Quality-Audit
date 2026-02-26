"""
Tests for extractor_usable_v2: _is_period_like_header, period-only duplicate logic,
_detect_caption_rows, header row detection, is_usable (2+ critical flags).
"""

from quality_audit.io.extractors.ooxml_table_grid_extractor import (
    ExtractionResult,
    OOXMLTableGridExtractor,
)


class TestIsPeriodLikeHeader:
    """Tests for _is_period_like_header."""

    def test_period_year_matches(self):
        extractor = OOXMLTableGridExtractor()
        assert extractor._is_period_like_header("2020") is True
        assert extractor._is_period_like_header("2024") is True
        assert extractor._is_period_like_header("FY2021") is True
        assert extractor._is_period_like_header("31/12/2020") is True

    def test_code_note_empty_false(self):
        extractor = OOXMLTableGridExtractor()
        assert extractor._is_period_like_header("") is False
        assert extractor._is_period_like_header("Code") is False
        assert extractor._is_period_like_header("Note") is False
        assert extractor._is_period_like_header("Description") is False
        assert extractor._is_period_like_header("Item") is False


class TestDetectCaptionRows:
    """Tests for _detect_caption_rows."""

    def test_single_non_empty_is_caption(self):
        extractor = OOXMLTableGridExtractor()
        grid = [
            ["Table 1", "", ""],
            ["A", "B", "C"],
            ["1", "2", "3"],
        ]
        captions = extractor._detect_caption_rows(grid)
        assert 0 in captions

    def test_full_header_row_not_caption(self):
        extractor = OOXMLTableGridExtractor()
        grid = [
            ["Account", "2024", "2023"],
            ["Revenue", "100", "90"],
        ]
        captions = extractor._detect_caption_rows(grid)
        assert 0 not in captions


class TestExtractorUsableV2:
    """Tests for is_usable when extractor_usable_v2: 2+ critical flags -> unusable."""

    def test_usable_when_score_high_no_critical(self):
        result = ExtractionResult(
            grid=[["A", "B"], ["1", "2"]],
            quality_score=0.8,
            quality_flags=[],
            rows=2,
            cols=2,
            invariant_violations=[],
        )
        assert result.is_usable is True

    def test_unusable_when_score_low(self):
        result = ExtractionResult(
            grid=[["A", "B"]],
            quality_score=0.5,
            quality_flags=[],
            rows=1,
            cols=2,
            invariant_violations=[],
        )
        assert result.is_usable is False
