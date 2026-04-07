"""Tests for _decide_merge logic in WordReader (G1)."""

import pandas as pd
import pytest

from quality_audit.io.word_reader import WordReader


@pytest.fixture
def reader():
    return WordReader()


def _default_flags():
    return {"ENABLE_SPLIT_TABLE_MERGE": True}


def _df(rows=3, cols=3):
    return pd.DataFrame({f"c{i}": range(rows) for i in range(cols)})


class TestDecideMerge:
    """Tests for WordReader._decide_merge."""

    def test_merge_blocked_when_heading_and_note_missing(self, reader):
        """No heading, no note, no page_break -> MERGE_WEAK_HEURISTIC_BLOCKED."""
        prev = _df()
        curr = _df()
        ok, reason, _ = reader._decide_merge(
            prev_df=prev,
            curr_df=curr,
            prev_heading="Note 1",
            curr_heading=None,
            curr_note_number=None,
            page_break=False,
            paragraphs_since=1,
            long_paragraph=False,
            is_footer=False,
            prev_is_footer=False,
            flags=_default_flags(),
        )
        assert not ok
        assert reason == "MERGE_WEAK_HEURISTIC_BLOCKED"

    def test_merge_allowed_with_page_break(self, reader):
        """Page break allows merge even without heading/note."""
        prev = _df()
        curr = _df()
        ok, reason, _ = reader._decide_merge(
            prev_df=prev,
            curr_df=curr,
            prev_heading="Note 1",
            curr_heading=None,
            curr_note_number=None,
            page_break=True,
            paragraphs_since=5,
            long_paragraph=True,
            is_footer=False,
            prev_is_footer=False,
            flags=_default_flags(),
        )
        assert ok
        assert reason == "MERGED_BY_STRONG_ANCHOR"

    def test_merge_allowed_strong_anchor_note_match(self, reader):
        """Heading match + proximity -> allowed."""
        prev = _df()
        curr = _df()
        ok, reason, _ = reader._decide_merge(
            prev_df=prev,
            curr_df=curr,
            prev_heading="Note 1",
            curr_heading="Note 1",
            curr_note_number="1",
            page_break=False,
            paragraphs_since=1,
            long_paragraph=False,
            is_footer=False,
            prev_is_footer=False,
            flags=_default_flags(),
        )
        assert ok
        assert reason == "MERGED_BY_STRONG_ANCHOR"

    def test_merge_blocked_financial_statement(self, reader):
        """Financial-statement heading blocks merge."""
        prev = _df()
        curr = _df()
        ok, reason, _ = reader._decide_merge(
            prev_df=prev,
            curr_df=curr,
            prev_heading="Note 1",
            curr_heading="Cash Flow Statement",
            curr_note_number=None,
            page_break=True,
            paragraphs_since=1,
            long_paragraph=False,
            is_footer=False,
            prev_is_footer=False,
            flags=_default_flags(),
        )
        assert not ok
        assert reason == "MERGE_BLOCKED_FINANCIAL_STATEMENT"

    def test_merge_blocked_code_reset(self, reader):
        """Code column resets to '01' -> MERGE_BLOCKED_CONTINUITY."""
        prev = pd.DataFrame(
            {"c0": ["01", "02", "20"], "c1": [1, 2, 3], "c2": [4, 5, 6]}
        )
        curr = pd.DataFrame(
            {"c0": ["01", "02", "10"], "c1": [7, 8, 9], "c2": [10, 11, 12]}
        )
        ok, reason, _ = reader._decide_merge(
            prev_df=prev,
            curr_df=curr,
            prev_heading="Note 1",
            curr_heading=None,
            curr_note_number="1",
            page_break=True,
            paragraphs_since=1,
            long_paragraph=False,
            is_footer=False,
            prev_is_footer=False,
            flags=_default_flags(),
        )
        assert not ok
        assert reason == "MERGE_BLOCKED_CONTINUITY"

    def test_merge_blocked_column_count_mismatch(self, reader):
        """Column drift with weak continuity should remain blocked."""
        prev = pd.DataFrame(
            {
                "code": ["10", "11", "12"],
                "label": ["A", "B", "C"],
                "cy": [10, 20, 30],
            }
        )
        curr = pd.DataFrame(
            {
                "text": ["Narrative", "Narrative 2", "Narrative 3"],
                "x": ["-", "-", "-"],
                "y": ["-", "-", "-"],
                "z": ["-", "-", "-"],
            }
        )
        ok, reason, _ = reader._decide_merge(
            prev_df=prev,
            curr_df=curr,
            prev_heading="Note 1",
            curr_heading="Different heading",
            curr_note_number=None,
            page_break=False,
            paragraphs_since=3,
            long_paragraph=True,
            is_footer=False,
            prev_is_footer=False,
            flags=_default_flags(),
        )
        assert not ok
        assert reason in {
            "COLUMN_COUNT_MISMATCH",
            "MERGE_WEAK_HEURISTIC_BLOCKED",
            "PROXIMITY_FAIL",
        }

    def test_merge_blocked_no_prev_table(self, reader):
        """No previous table -> NO_PREV_TABLE."""
        curr = _df()
        ok, reason, _ = reader._decide_merge(
            prev_df=None,
            curr_df=curr,
            prev_heading=None,
            curr_heading="Note 1",
            curr_note_number="1",
            page_break=False,
            paragraphs_since=1,
            long_paragraph=False,
            is_footer=False,
            prev_is_footer=False,
            flags=_default_flags(),
        )
        assert not ok
        assert reason == "NO_PREV_TABLE"

    def test_merge_evidence_dict_populated(self, reader):
        """Evidence dict contains expected keys."""
        prev = _df()
        curr = _df()
        _, _, evidence = reader._decide_merge(
            prev_df=prev,
            curr_df=curr,
            prev_heading="H1",
            curr_heading="H2",
            curr_note_number="5",
            page_break=True,
            paragraphs_since=0,
            long_paragraph=False,
            is_footer=False,
            prev_is_footer=False,
            flags=_default_flags(),
        )
        assert "prev_heading" in evidence
        assert "curr_heading" in evidence
        assert "note_number" in evidence
        assert "page_break" in evidence

    def test_merge_allows_col_diff_one_when_continuity_is_high(self, reader):
        prev = pd.DataFrame(
            {
                "code": ["10", "11", "20", "21"],
                "label": ["A", "B", "C", "D"],
                "cy": [10, 20, 30, 40],
            }
        )
        curr = pd.DataFrame(
            {
                "code": ["22", "23", "24", "30"],
                "label": ["E", "F", "G", "H"],
                "cy": [50, 60, 70, 80],
                "py": [45, 55, 65, 75],
            }
        )
        ok, reason, evidence = reader._decide_merge(
            prev_df=prev,
            curr_df=curr,
            prev_heading="Note 5",
            curr_heading="Note 5",
            curr_note_number="5",
            page_break=False,
            paragraphs_since=1,
            long_paragraph=False,
            is_footer=False,
            prev_is_footer=False,
            flags=_default_flags(),
        )
        assert ok
        assert reason in {
            "MERGED_CONTINUITY",
            "MERGED_BY_STRONG_ANCHOR",
            "MERGED_BY_CONTINUITY_SCORE",
        }
        assert int(evidence.get("column_count_diff", 0)) == 1
