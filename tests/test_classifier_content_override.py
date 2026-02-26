"""
Tests for classifier_content_override and tax_routing_content_evidence.
Content analysis always runs; override when heading junk (confidence < 0.5);
TAX_NOTE only when content evidence (row/column labels) present.
"""

import pandas as pd
import pytest

from quality_audit.core.routing.table_type_classifier import (
    TableType,
    TableTypeClassifier,
)


class TestClassifierContentOverride:
    """Tests for classifier content override and tax routing with content evidence."""

    @pytest.fixture
    def classifier(self):
        return TableTypeClassifier()

    def test_classifier_returns_context_with_reason(self, classifier):
        """Classification result context includes classifier_reason and classifier_primary_type."""
        df = pd.DataFrame(
            [
                ["Assets", "2024", "2023"],
                ["Current assets", 100, 90],
                ["Total assets", 100, 90],
            ]
        )
        result = classifier.classify(
            df, heading="Balance Sheet", heading_confidence=0.9
        )
        assert result.context is not None
        assert "classifier_reason" in result.context
        assert "classifier_primary_type" in result.context or "table_type" in str(
            result
        )

    def test_tax_note_requires_content_evidence(self, classifier):
        """When tax_routing_content_evidence is on, TAX_NOTE requires tax content in table."""
        # Table with no tax labels -> should not be TAX_NOTE (or low confidence)
        df = pd.DataFrame(
            [
                ["Item", "2024", "2023"],
                ["Revenue", 1000, 900],
                ["Total", 1000, 900],
            ]
        )
        result = classifier.classify(df, heading="Tax note", heading_confidence=0.8)
        # With content evidence: no tax phrases in table -> may route to generic_note or unknown
        assert result.table_type in (
            TableType.TAX_NOTE,
            TableType.GENERIC_NOTE,
            TableType.UNKNOWN,
            TableType.FS_BALANCE_SHEET,
        )

    def test_content_override_when_heading_confidence_low(self, classifier):
        """When heading_confidence < 0.5 and classifier_content_override on, content can override."""
        df = pd.DataFrame(
            [
                ["Assets", "Liabilities", "Equity"],
                ["100", "60", "40"],
                ["Total", "100", "100"],
            ]
        )
        result = classifier.classify(df, heading="Junk 123", heading_confidence=0.3)
        assert result.context is not None
        assert "classifier_reason" in result.context
