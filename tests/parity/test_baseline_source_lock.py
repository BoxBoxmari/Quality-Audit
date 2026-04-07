from quality_audit.core.legacy_audit import BASELINE_SOURCES


def test_baseline_sources_locked():
    assert BASELINE_SOURCES == ("legacy/main.py", "legacy/Quality Audit.py")
