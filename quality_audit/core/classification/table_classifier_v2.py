"""
Table Classifier V2 — multi-signal weighted voting classifier.

Combines structural fingerprint evidence (weight 0.7) with heading
evidence (weight 0.3) for robust table type classification.
Feature-flag gated via ``classification_v2_enabled``.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import pandas as pd

from ...config.feature_flags import get_feature_flags
from ..routing.table_type_classifier import ClassificationResult, TableType
from .structural_fingerprint import StructuralFingerprint, StructuralFingerprinter

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Heading keyword sets
# ---------------------------------------------------------------------------

_HEADING_PATTERNS: Dict[TableType, List[str]] = {
    TableType.FS_BALANCE_SHEET: [
        "balance sheet",
        "cân đối kế toán",
        "statement of financial position",
        "báo cáo tình hình tài chính",
        "financial position",
    ],
    TableType.FS_INCOME_STATEMENT: [
        "statement of income",
        "income statement",
        "kết quả kinh doanh",
        "profit and loss",
        "p&l",
        "statement of comprehensive income",
        "báo cáo kết quả hoạt động kinh doanh",
    ],
    TableType.FS_CASH_FLOW: [
        "cash flow",
        "cash flows",
        "lưu chuyển tiền tệ",
        "lưu chuyển tiền",
        "statement of cash flows",
    ],
    TableType.FS_EQUITY: [
        "changes in equity",
        "biến động vốn chủ sở hữu",
        "statement of changes in equity",
        "báo cáo biến động vốn chủ sở hữu",
    ],
    TableType.TAX_NOTE: [
        "tax",
        "thuế",
    ],
}

# Negative keywords: if present in heading, table is likely a Note
_NEGATIVE_STATEMENT_KEYWORDS = [
    "recognised in",
    "ghi nhận tại",
    "off balance sheet",
    "ngoài bảng",
    "approved but not provided",
    "policy",
    "accounting policy",
    "chính sách",
    "is recognised",
    "được ghi nhận",
    "details of",
    "chi tiết",
    "schedule of",
]

_EXCLUSIVE_OF_VAT_RE = re.compile(r"exclusive\s+of\s+vat", re.I)


@dataclass
class _Signal:
    """Internal voting signal for a table type."""

    table_type: TableType
    score: float
    source: str  # "heading", "structure", "movement"


class TableClassifierV2:
    """Multi-signal table classifier with weighted voting.

    Combines heading evidence (weight=0.3) and structural fingerprint
    evidence (weight=0.7) to produce a classification with confidence.

    Usage::

        classifier = TableClassifierV2()
        result = classifier.classify(table, heading)
    """

    HEADING_WEIGHT: float = 0.3
    STRUCTURE_WEIGHT: float = 0.7

    # Minimum fingerprint thresholds for structure signal
    MIN_CODE_MATCHES_BS: int = 3
    MIN_CODE_MATCHES_IS: int = 3
    MIN_CODE_MATCHES_CF: int = 3
    MIN_CODE_DENSITY: float = 0.15

    def __init__(
        self,
        *,
        fingerprinter: Optional[StructuralFingerprinter] = None,
    ) -> None:
        self._fp = fingerprinter or StructuralFingerprinter()

    def classify(
        self,
        table: pd.DataFrame,
        heading: Optional[str],
        heading_confidence: Optional[float] = None,
    ) -> ClassificationResult:
        """Classify a table using multi-signal voting.

        Args:
            table: The table DataFrame.
            heading: Table heading text (may be None).
            heading_confidence: Optional confidence in heading (0–1).

        Returns:
            ClassificationResult compatible with existing factory.
        """
        if table.empty:
            return ClassificationResult(
                TableType.UNKNOWN,
                0.0,
                ["Empty table"],
                context={"scan_rows": 0, "classifier_version": "v2"},
            )

        heading_lower = heading.lower().strip() if heading else ""

        # Fast exit: skipped tables
        if "skipped_" in heading_lower:
            return ClassificationResult(
                TableType.UNKNOWN,
                1.0,
                ["Skipped header"],
                context={"scan_rows": 0, "classifier_version": "v2"},
            )

        # Negative keyword gate: definite note
        is_note_by_keyword = any(
            k in heading_lower for k in _NEGATIVE_STATEMENT_KEYWORDS
        )

        # Extract structural fingerprint
        fingerprint = self._fp.extract(table)

        # Collect signals
        signals: List[_Signal] = []

        # --- Heading signals ---
        heading_weight = self.HEADING_WEIGHT
        if heading_confidence is not None and heading_confidence < 0.5:
            heading_weight *= 0.5  # Reduce heading influence when low confidence

        if not is_note_by_keyword and heading_lower:
            heading_signal = self._score_heading(heading_lower)
            if heading_signal is not None:
                heading_signal_weighted = _Signal(
                    heading_signal.table_type,
                    heading_signal.score * heading_weight,
                    "heading",
                )
                signals.append(heading_signal_weighted)

        # --- Structure signals ---
        structure_signals = self._score_structure(fingerprint)
        for sig in structure_signals:
            sig.score *= self.STRUCTURE_WEIGHT
            signals.append(sig)

        # --- Movement signal (overrides if strong) ---
        if fingerprint.has_movement_structure:
            signals.append(
                _Signal(
                    TableType.GENERIC_NOTE,  # Movement tables use generic validator with rollforward
                    0.8 * self.STRUCTURE_WEIGHT,
                    "movement",
                )
            )

        # --- Aggregate votes ---
        if not signals:
            table_type = TableType.GENERIC_NOTE
            confidence = 0.5
            reasons = ["No signals matched — fallback"]
        else:
            vote_totals: Dict[TableType, float] = {}
            for sig in signals:
                vote_totals[sig.table_type] = (
                    vote_totals.get(sig.table_type, 0.0) + sig.score
                )

            winner = max(vote_totals, key=vote_totals.get)  # type: ignore[arg-type]
            raw_score = vote_totals[winner]

            # Normalize confidence to 0–1 range
            confidence = min(1.0, raw_score)
            table_type = winner

            # Tax note requires content evidence
            if table_type == TableType.TAX_NOTE:
                if _EXCLUSIVE_OF_VAT_RE.search(heading_lower):
                    table_type = TableType.GENERIC_NOTE
                    confidence = 0.8
                    signals.append(
                        _Signal(TableType.GENERIC_NOTE, 0.8, "vat_exclusion")
                    )

            reasons = [
                f"{s.source}: {s.table_type.value} (score={s.score:.2f})"
                for s in signals
            ]

        # Note override: if heading has negative keywords → force note
        if is_note_by_keyword and table_type not in (
            TableType.GENERIC_NOTE,
            TableType.TAX_NOTE,
            TableType.UNKNOWN,
        ):
            # Only override if structure signal is not very strong
            structure_score = sum(s.score for s in signals if s.source == "structure")
            if structure_score < 0.6:
                table_type = TableType.GENERIC_NOTE
                confidence = 0.75
                reasons.append("Negative keyword override → GENERIC_NOTE")

        ctx: Dict[str, Any] = {
            "scan_rows": fingerprint.scan_rows,
            "classifier_version": "v2",
            "classifier_primary_type": table_type.value,
            "classifier_confidence": round(confidence, 3),
            "code_density": round(fingerprint.code_density, 3),
            "bs_code_matches": fingerprint.bs_code_matches,
            "is_code_matches": fingerprint.is_code_matches,
            "cf_code_matches": fingerprint.cf_code_matches,
            "has_movement_structure": fingerprint.has_movement_structure,
            "keywords_found": sorted(fingerprint.keywords_found),
        }

        return ClassificationResult(
            table_type=table_type,
            confidence=round(confidence, 3),
            reasons=reasons,
            context=ctx,
        )

    # -----------------------------------------------------------------
    # Internal scoring methods
    # -----------------------------------------------------------------

    def _score_heading(self, heading_lower: str) -> Optional[_Signal]:
        """Score heading match against known patterns."""
        best: Optional[_Signal] = None

        for table_type, patterns in _HEADING_PATTERNS.items():
            for pattern in patterns:
                if pattern in heading_lower:
                    # Exact full match (heading IS the pattern) → high score
                    score = 0.95 if heading_lower == pattern else 0.8
                    if best is None or score > best.score:
                        best = _Signal(table_type, score, "heading")

        return best

    def _score_structure(self, fp: StructuralFingerprint) -> List[_Signal]:
        """Score structural fingerprint evidence per table type."""
        signals: List[_Signal] = []

        # Balance Sheet
        if fp.bs_code_matches >= self.MIN_CODE_MATCHES_BS:
            score = min(1.0, 0.3 + fp.bs_code_matches * 0.1)
            signals.append(_Signal(TableType.FS_BALANCE_SHEET, score, "structure"))
        elif (
            "assets" in fp.keywords_found
            and "liabilities" in fp.keywords_found
            and fp.code_density > self.MIN_CODE_DENSITY
        ):
            signals.append(_Signal(TableType.FS_BALANCE_SHEET, 0.6, "structure"))
        elif fp.has_assets_in_early and fp.code_density > 0.2:
            signals.append(_Signal(TableType.FS_BALANCE_SHEET, 0.5, "structure"))

        # Income Statement: need IS codes + exclusives or keywords
        if fp.is_code_matches >= self.MIN_CODE_MATCHES_IS and (
            fp.is_exclusive_matches >= 1
            or "revenue" in fp.keywords_found
            or "profit" in fp.keywords_found
        ):
            score = min(1.0, 0.3 + fp.is_code_matches * 0.08)
            signals.append(_Signal(TableType.FS_INCOME_STATEMENT, score, "structure"))

        # Cash Flow: need CF codes + cash/flows keywords or CF exclusives
        if fp.cf_code_matches >= self.MIN_CODE_MATCHES_CF and (
            "cash" in fp.keywords_found
            or fp.cf_exclusive_matches >= 1
            or ("operating" in fp.keywords_found and "investing" in fp.keywords_found)
        ):
            score = min(1.0, 0.3 + fp.cf_code_matches * 0.06)
            signals.append(_Signal(TableType.FS_CASH_FLOW, score, "structure"))

        # Equity: heading-only (rare structural signals)
        if "equity" in fp.keywords_found and fp.has_movement_structure:
            signals.append(_Signal(TableType.FS_EQUITY, 0.5, "structure"))

        return signals
