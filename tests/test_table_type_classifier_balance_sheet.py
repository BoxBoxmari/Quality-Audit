import pandas as pd

from quality_audit.core.cache_manager import AuditContext, LRUCacheManager
from quality_audit.core.routing.table_type_classifier import (
    TableType,
    TableTypeClassifier,
)
from quality_audit.core.validators.factory import ValidatorFactory
from quality_audit.core.validators.generic_validator import GenericTableValidator


class TestTableTypeClassifierBalanceSheet:
    def test_balance_sheet_detected_with_liabilities_after_early_rows(self):
        """
        Assets in early rows and Liabilities appearing after row 20 should still be
        classified as FS_BALANCE_SHEET when scan expansion feature flag is enabled.
        """
        rows = []
        # Row 0: assets keyword with code
        rows.append(["100", "Total Assets"])
        # Rows 1-29: filler numeric/code rows without liabilities
        for i in range(1, 30):
            rows.append([str(100 + i), f"Row {i}"])
        # Row 30: liabilities keyword
        rows.append(["300", "Total Liabilities"])
        # A few more rows
        for i in range(31, 40):
            rows.append([str(100 + i), f"Row {i}"])

        df = pd.DataFrame(rows, columns=["Code", "Description"])

        classifier = TableTypeClassifier()
        result = classifier.classify(df, heading=None)

        assert result.table_type == TableType.FS_BALANCE_SHEET
        assert result.context is not None
        assert result.context.get("scan_rows") >= len(df)

    def test_non_balance_sheet_notes_not_misclassified(self):
        """
        Table that merely mentions 'assets' in narrative text without strong code density
        should not be forced into FS_BALANCE_SHEET when heading is unknown.
        """
        df = pd.DataFrame(
            {
                "Col1": ["Discussion of assets and other matters", "More narrative"],
                "Col2": ["This is a note", "without structured codes"],
            }
        )

        classifier = TableTypeClassifier()
        result = classifier.classify(df, heading=None)

        assert result.table_type in {TableType.GENERIC_NOTE, TableType.UNKNOWN}

    def test_balance_sheet_routing_downgraded_when_no_numeric_evidence(self):
        """
        Tables with ASSETS/LIABILITIES keywords but text-only columns are routed
        to GenericTableValidator when gating is enabled (numeric_evidence_score < threshold).
        """
        df = pd.DataFrame(
            {
                "Description": ["Total Assets", "Total Liabilities", "Equity"],
                "Notes": ["Narrative text only", "No figures", "Text column"],
            }
        )
        ctx = AuditContext(cache=LRUCacheManager(max_size=100))
        validator, skip_reason = ValidatorFactory.get_validator(
            df, heading="Statement of Financial Position", context=ctx
        )
        assert validator is not None
        assert isinstance(validator, GenericTableValidator)
        assert skip_reason is None
        last_ctx = ctx.get_last_classification_context()
        assert last_ctx is not None
        # With no numeric evidence, routing may downgrade from BalanceSheet or go straight to generic
        assert last_ctx.get("downgraded_from") == "BalanceSheetValidator" or (
            last_ctx.get("classifier_primary_type") in ("generic_note", "generic_table")
        )
