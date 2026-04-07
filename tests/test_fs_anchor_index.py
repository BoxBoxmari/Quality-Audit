from quality_audit.core.model.fs_anchor_index import (
    _normalize_note_ref,
    infer_note_ref_for_table,
)


def test_normalize_note_ref_canonicalizes_leading_zeroes():
    assert _normalize_note_ref("Note 04") == "4"
    assert _normalize_note_ref("TM 009") == "9"
    assert _normalize_note_ref("4") == "4"


def test_infer_note_ref_prefers_context_note_number_over_heading():
    t_info = {
        "context": {"note_number": "04"},
        "heading": "TM 09 - Tien va tuong duong tien",
    }
    result = infer_note_ref_for_table(t_info)
    assert result == "4"


def test_infer_note_ref_supports_legacy_tm_heading_pattern():
    assert (
        infer_note_ref_for_table({"context": {}, "heading": "TM 09 - Tai san co dinh"})
        == "9"
    )
    assert (
        infer_note_ref_for_table({"context": {}, "heading": "TM.7 - Chi phi tra truoc"})
        == "7"
    )
    assert (
        infer_note_ref_for_table({"context": {}, "heading": "tm so 12 - Doanh thu"})
        == "12"
    )
