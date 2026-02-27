"""
Table Type Classifier for intelligent routing of financial tables.
Distinguishes between main Financial Statements (BS, IS, CF, EQ) and Notes/Disclosures.
"""

import logging
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

import pandas as pd

from quality_audit.config.feature_flags import FEATURE_FLAGS, get_feature_flags

logger = logging.getLogger(__name__)

# Tax content evidence phrases (row/column labels suggesting tax note)
_TAX_CONTENT_PHRASES = [
    "tax",
    "thuế",
    "income tax",
    "deferred tax",
    "current tax",
    "vat",
    "value added",
    "corporate tax",
    "tax expense",
]
# Negative signal: do not route to TAX_NOTE when present
_EXCLUSIVE_OF_VAT_PATTERN = re.compile(r"exclusive\s+of\s+vat", re.I)


class TableType(Enum):
    FS_BALANCE_SHEET = "fs_balance_sheet"
    FS_INCOME_STATEMENT = "fs_income_statement"
    FS_CASH_FLOW = "fs_cash_flow"
    FS_EQUITY = "fs_equity"
    TAX_NOTE = "tax_note"
    GENERIC_NOTE = "generic_note"  # Default for notes
    UNKNOWN = "unknown"


@dataclass
class ClassificationResult:
    table_type: TableType
    confidence: float
    reasons: List[str]
    context: Optional[Dict[str, Any]] = None


class TableTypeClassifier:
    """Classifies financial tables based on heading and content evidence."""

    # Strong negative keywords for Statement tables (if present, likely a Note)
    NEGATIVE_STATEMENT_KEYWORDS = [
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

    def _has_tax_content_evidence(
        self, table: pd.DataFrame, max_rows: int = 20
    ) -> bool:
        """Scan table content for tax-related labels (row/column text)."""
        for i in range(min(max_rows, len(table))):
            try:
                row_text = " ".join(
                    [str(x).lower() for x in table.iloc[i] if pd.notna(x)]
                )
                if any(phrase in row_text for phrase in _TAX_CONTENT_PHRASES):
                    return True
            except Exception:
                continue
        return False

    def _has_exclusive_of_vat(
        self, heading_lower: str, table: pd.DataFrame, max_rows: int = 10
    ) -> bool:
        """True if heading or table content contains 'exclusive of vat' (negative signal for TAX_NOTE)."""
        if _EXCLUSIVE_OF_VAT_PATTERN.search(heading_lower):
            return True
        for i in range(min(max_rows, len(table))):
            try:
                row_text = " ".join(
                    [str(x).lower() for x in table.iloc[i] if pd.notna(x)]
                )
                if _EXCLUSIVE_OF_VAT_PATTERN.search(row_text):
                    return True
            except Exception:
                continue
        return False

    def classify(
        self,
        table: pd.DataFrame,
        heading: Optional[str],
        heading_confidence: Optional[float] = None,
    ) -> ClassificationResult:
        """
        Classify a table into a specific type.

        Args:
            table: The table DataFrame
            heading: The table heading text
            heading_confidence: Optional heading confidence (0–1). When < 0.5 and
                classifier_content_override is True, content-based routing is preferred.

        Returns:
            ClassificationResult
        """
        if table.empty:
            ctx = {"scan_rows": 0, "classifier_reason": "Empty table"}
            ctx["classifier_primary_type"] = TableType.UNKNOWN.value
            ctx["classifier_confidence"] = 0.0
            return ClassificationResult(
                TableType.UNKNOWN,
                0.0,
                ["Empty table"],
                context=ctx,
            )

        heading_lower = heading.lower().strip() if heading else ""
        reasons = []
        flags = get_feature_flags()
        use_heading_for_routing = True
        if (
            flags.get("classifier_content_override", False)
            and heading_confidence is not None
            and heading_confidence < 0.5
        ):
            use_heading_for_routing = False
            reasons.append("Heading confidence < 0.5, prefer content")
        tax_requires_content = flags.get("tax_routing_content_evidence", False)
        has_exclusive_of_vat = self._has_exclusive_of_vat(heading_lower, table)

        # 0. Check for SKIPPED (signature/footer) - should be handled upstream but safe to check
        if "skipped_" in heading_lower:
            return ClassificationResult(
                TableType.UNKNOWN,
                1.0,
                ["Skipped header"],
                context={"scan_rows": 0, "classifier_reason": "Skipped header"},
            )

        # 1. Negative Check: Is this definitely a Note?
        is_note_by_keyword = any(
            k in heading_lower for k in self.NEGATIVE_STATEMENT_KEYWORDS
        )
        if is_note_by_keyword:
            reasons.append("Matched negative statement keywords (likely note)")
            # Route to appropriate note type
            if "tax" in heading_lower or "thuế" in heading_lower:
                if has_exclusive_of_vat:
                    _ctx_tax = {
                        "scan_rows": 0,
                        "classifier_reason": "exclusive of VAT (negative signal)",
                    }
                    _ctx_tax["classifier_primary_type"] = TableType.GENERIC_NOTE.value
                    _ctx_tax["classifier_confidence"] = 0.8
                    return ClassificationResult(
                        TableType.GENERIC_NOTE,
                        0.8,
                        reasons + ["exclusive of VAT (negative signal)"],
                        context=_ctx_tax,
                    )
                if tax_requires_content and not self._has_tax_content_evidence(table):
                    _ctx_tax = {
                        "scan_rows": 0,
                        "classifier_reason": "No tax content evidence",
                    }
                    _ctx_tax["classifier_primary_type"] = TableType.GENERIC_NOTE.value
                    _ctx_tax["classifier_confidence"] = 0.7
                    return ClassificationResult(
                        TableType.GENERIC_NOTE,
                        0.7,
                        reasons + ["No tax content evidence"],
                        context=_ctx_tax,
                    )
                _ctx_tax = {"scan_rows": 0, "classifier_reason": reasons[0]}
                _ctx_tax["classifier_primary_type"] = TableType.TAX_NOTE.value
                _ctx_tax["classifier_confidence"] = 0.9
                return ClassificationResult(
                    TableType.TAX_NOTE,
                    0.9,
                    reasons,
                    context=_ctx_tax,
                )
            _ctx_note = {"scan_rows": 0, "classifier_reason": reasons[0]}
            _ctx_note["classifier_primary_type"] = TableType.GENERIC_NOTE.value
            _ctx_note["classifier_confidence"] = 0.8
            return ClassificationResult(
                TableType.GENERIC_NOTE,
                0.8,
                reasons,
                context=_ctx_note,
            )

        # 2. Content Analysis
        # Count code-like rows
        code_rows = 0
        total_rows = len(table)
        has_keywords = {
            "assets": False,  # assets, tài sản
            "liabilities": False,  # liabilities, nợ phải trả
            "equity": False,  # equity, vốn chủ sở hữu
            "cash": False,  # cash, tiền
            "flows": False,  # flows, lưu chuyển
            "revenue": False,  # revenue, doanh thu, sales
            "profit": False,  # profit, lợi nhuận, lãi
        }
        # Keyword mapping for multi-language support
        keyword_map = {
            "assets": ["assets", "tài sản"],
            "liabilities": ["liabilities", "nợ phải trả"],
            "equity": ["equity", "vốn chủ sở hữu"],
            "cash": ["cash", "tiền"],
            "flows": ["flows", "lưu chuyển"],
            "revenue": ["revenue", "doanh thu", "sales", "thu nhập"],
            "profit": ["profit", "lợi nhuận", "lãi"],
        }
        # For relaxed BS: "assets in early part" = within first 20 rows of scan
        early_window = 20
        has_assets_in_early = False

        # Feature flag: classifier_scan_expansion (default True) - expand scan window
        if FEATURE_FLAGS.get("classifier_scan_expansion", True):
            scan_rows = min(60, total_rows)
        else:
            scan_rows = min(20, total_rows)

        found_codes = set()
        for i in range(scan_rows):
            try:
                row_text = " ".join(
                    [str(x).lower() for x in table.iloc[i] if pd.notna(x)]
                )

                # Check keywords via mapping
                for k, patterns in keyword_map.items():
                    if any(p in row_text for p in patterns):
                        has_keywords[k] = True

                if (
                    any(p in row_text for p in keyword_map["assets"])
                    and i < early_window
                ):
                    has_assets_in_early = True

                # Check for code patterns in first few columns
                # Heuristic: row has numeric code in col 0, 1 or 2
                for j in range(min(3, len(table.columns))):
                    val = str(table.iloc[i, j]).strip()
                    if re.match(r"^\d{2,3}[a-zA-Z]?$", val):
                        found_codes.add(re.match(r"^(\d{2,3})", val).group(1))
                        code_rows += 1
                        break
                    elif re.match(r"^[IVX]+$", val):
                        code_rows += 1
                        break
            except Exception:
                continue

        code_density = code_rows / scan_rows if scan_rows > 0 else 0

        # Comment 3: content score for override — allow content to override heading when score > 0.6
        keyword_score = sum(1 for v in has_keywords.values() if v) / max(
            len(has_keywords), 1
        )
        content_score = 0.5 * code_density + 0.5 * keyword_score
        if flags.get("classifier_content_override", False) and content_score > 0.6:
            use_heading_for_routing = False
            reasons.append("Content score > 0.6, prefer content over heading")
        _ctx = {"scan_rows": scan_rows, "classifier_reason": ""}
        if flags.get("classifier_content_override", False) and content_score > 0.6:
            _ctx["content_override_reason"] = "content_score_above_threshold"
            _ctx["content_score"] = round(content_score, 3)
        logger.debug(
            "Classifier scan: scan_rows=%s, has_assets=%s, has_liabilities=%s, has_assets_early=%s, code_density=%.2f",
            scan_rows,
            has_keywords["assets"],
            has_keywords["liabilities"],
            has_assets_in_early,
            code_density,
        )

        recognized_statement_keywords = [
            "balance sheet",
            "cân đối kế toán",
            "statement of income",
            "income statement",
            "kết quả kinh doanh",
            "profit and loss",
            "p&l",
            "cash flow",
            "cash flows",
            "lưu chuyển tiền tệ",
            "lưu chuyển tiền",
            "equity",
            "vốn chủ sở hữu",
        ]
        is_heading_recognized = any(
            k in heading_lower for k in recognized_statement_keywords
        )

        effective_heading = "" if not use_heading_for_routing else heading_lower

        # Structure-based override (Escape Hatch for GenericNote misclassification)
        # ONLY apply if the heading is not explicitly recognized as a major statement
        structure_override = None
        if (
            not is_heading_recognized
            or not use_heading_for_routing
            or "unknown" in heading_lower
        ):
            bs_code_matches = len(
                found_codes.intersection({"100", "110", "270", "300", "440"})
            )
            is_code_matches = len(
                found_codes.intersection(
                    {"01", "11", "20", "21", "22", "30", "50", "60"}
                )
            )
            cf_code_matches = len(
                found_codes.intersection({"20", "30", "40", "50", "60", "70"})
            )

            is_exclusive = len(
                found_codes.intersection({"23", "25", "26", "51", "52", "61", "62"})
            )
            cfs_exclusive = len(
                found_codes.intersection({"08", "09", "13", "14", "15", "16", "17"})
            )

            if bs_code_matches >= 3:
                structure_override = TableType.FS_BALANCE_SHEET
            elif cf_code_matches >= 3 and (has_keywords["cash"] or cfs_exclusive >= 1):
                structure_override = TableType.FS_CASH_FLOW
            elif is_code_matches >= 3 and (
                is_exclusive >= 1 or has_keywords["revenue"] or has_keywords["profit"]
            ):
                structure_override = TableType.FS_INCOME_STATEMENT

            if structure_override is not None:
                _ctx["classifier_reason"] = "Structure-based override from column codes"
                _ctx["classifier_primary_type"] = structure_override.value
                _ctx["classifier_confidence"] = 0.90
                return ClassificationResult(
                    structure_override,
                    0.90,
                    ["Structure-based override from column codes"],
                    context=_ctx,
                )

        # 3. Routing Logic - P0-3: Match legacy routing với guardrails
        # Priority 1: Exact heading match (match legacy check_table_total logic)
        # Priority 2: Content-based fallback nếu heading unknown/null/garbage
        # Guardrails: Nếu heading match nhưng content không match → route GENERIC_NOTE
        if (
            not heading
            or heading_lower == ""
            or "unknown" in heading_lower
            or not is_heading_recognized
            or not use_heading_for_routing
        ):
            # Content-based statement detection
            bs_by_early_and_density = has_assets_in_early and code_density > 0.2
            bs_by_assets_and_liabilities = (
                has_keywords["assets"] and has_keywords["liabilities"]
            )
            if bs_by_early_and_density or bs_by_assets_and_liabilities:
                _ctx["classifier_reason"] = "Content-based: ASSETS/LIABILITIES detected"
                _ctx["classifier_primary_type"] = TableType.FS_BALANCE_SHEET.value
                _ctx["classifier_confidence"] = 0.85
                return ClassificationResult(
                    TableType.FS_BALANCE_SHEET,
                    0.85,
                    ["Content-based: ASSETS/LIABILITIES detected"],
                    context=_ctx,
                )

            if (
                has_keywords["revenue"] and has_keywords["profit"]
            ) and code_density > 0.3:
                _ctx["classifier_reason"] = "Content-based: REVENUE/PROFIT detected"
                _ctx["classifier_primary_type"] = TableType.FS_INCOME_STATEMENT.value
                _ctx["classifier_confidence"] = 0.85
                return ClassificationResult(
                    TableType.FS_INCOME_STATEMENT,
                    0.85,
                    ["Content-based: REVENUE/PROFIT detected"],
                    context=_ctx,
                )

            if has_keywords["cash"] and has_keywords["flows"] and code_density > 0.3:
                _ctx["classifier_reason"] = "Content-based: CASH FLOWS detected"
                _ctx["classifier_primary_type"] = TableType.FS_CASH_FLOW.value
                _ctx["classifier_confidence"] = 0.85
                return ClassificationResult(
                    TableType.FS_CASH_FLOW,
                    0.85,
                    ["Content-based: CASH FLOWS detected"],
                    context=_ctx,
                )

        # Balance Sheet - Exact heading match với guardrails (use effective_heading)
        if (
            effective_heading == "balance sheet"
            or "cân đối kế toán" in effective_heading
        ):
            # Verify with content (guardrails)
            if (
                has_keywords["assets"]
                or has_keywords["liabilities"]
                or code_density > 0.2
            ):
                _ctx["classifier_reason"] = "Exact heading + content match"
                _ctx["classifier_primary_type"] = TableType.FS_BALANCE_SHEET.value
                _ctx["classifier_confidence"] = 0.95
                return ClassificationResult(
                    TableType.FS_BALANCE_SHEET,
                    0.95,
                    ["Exact heading + content match"],
                    context=_ctx,
                )
            else:
                # Heading match nhưng content không match → route GENERIC_NOTE (guardrails)
                _ctx["classifier_reason"] = "Heading match but content suggests note"
                _ctx["classifier_primary_type"] = TableType.GENERIC_NOTE.value
                _ctx["classifier_confidence"] = 0.7
                return ClassificationResult(
                    TableType.GENERIC_NOTE,
                    0.7,
                    ["Heading match but content suggests note"],
                    context=_ctx,
                )

        # Income Statement - Exact heading match với guardrails
        if (
            effective_heading == "statement of income"
            or "kết quả kinh doanh" in effective_heading
        ):
            if has_keywords["revenue"] or has_keywords["profit"] or code_density > 0.2:
                _ctx["classifier_reason"] = "Exact heading + content match"
                _ctx["classifier_primary_type"] = TableType.FS_INCOME_STATEMENT.value
                _ctx["classifier_confidence"] = 0.95
                return ClassificationResult(
                    TableType.FS_INCOME_STATEMENT,
                    0.95,
                    ["Exact heading + content match"],
                    context=_ctx,
                )
            else:
                _ctx["classifier_reason"] = "Heading match but content suggests note"
                _ctx["classifier_primary_type"] = TableType.GENERIC_NOTE.value
                _ctx["classifier_confidence"] = 0.7
                return ClassificationResult(
                    TableType.GENERIC_NOTE,
                    0.7,
                    ["Heading match but content suggests note"],
                    context=_ctx,
                )

        # Cash Flow - Exact heading match với guardrails
        if (
            effective_heading == "statement of cash flows"
            or "lưu chuyển tiền" in effective_heading
        ):
            if has_keywords["cash"] or has_keywords["flows"] or code_density > 0.2:
                _ctx["classifier_reason"] = "Exact heading + content match"
                _ctx["classifier_primary_type"] = TableType.FS_CASH_FLOW.value
                _ctx["classifier_confidence"] = 0.95
                return ClassificationResult(
                    TableType.FS_CASH_FLOW,
                    0.95,
                    ["Exact heading + content match"],
                    context=_ctx,
                )
            else:
                _ctx["classifier_reason"] = "Heading match but content suggests note"
                _ctx["classifier_primary_type"] = TableType.GENERIC_NOTE.value
                _ctx["classifier_confidence"] = 0.7
                return ClassificationResult(
                    TableType.GENERIC_NOTE,
                    0.7,
                    ["Heading match but content suggests note"],
                    context=_ctx,
                )

        # Equity
        if (
            "equity" in effective_heading or "vốn chủ sở hữu" in effective_heading
        ) and ("change" in effective_heading or "biến động" in effective_heading):
            _ctx["classifier_reason"] = "Heading match"
            _ctx["classifier_primary_type"] = TableType.FS_EQUITY.value
            _ctx["classifier_confidence"] = 0.9
            return ClassificationResult(
                TableType.FS_EQUITY, 0.9, ["Heading match"], context=_ctx
            )

        # Tax Note (heading-based): apply content evidence and exclusive-of-VAT
        if "tax" in effective_heading or "thuế" in effective_heading:
            if has_exclusive_of_vat:
                _ctx["classifier_reason"] = "exclusive of VAT (negative signal)"
                _ctx["classifier_primary_type"] = TableType.GENERIC_NOTE.value
                _ctx["classifier_confidence"] = 0.8
                return ClassificationResult(
                    TableType.GENERIC_NOTE,
                    0.8,
                    ["exclusive of VAT (negative signal)"],
                    context=_ctx,
                )
            if tax_requires_content and not self._has_tax_content_evidence(table):
                _ctx["classifier_reason"] = "No tax content evidence"
                _ctx["classifier_primary_type"] = TableType.GENERIC_NOTE.value
                _ctx["classifier_confidence"] = 0.7
                return ClassificationResult(
                    TableType.GENERIC_NOTE,
                    0.7,
                    ["No tax content evidence"],
                    context=_ctx,
                )
            _ctx["classifier_reason"] = "Tax keyword match"
            _ctx["classifier_primary_type"] = TableType.TAX_NOTE.value
            _ctx["classifier_confidence"] = 0.8
            return ClassificationResult(
                TableType.TAX_NOTE, 0.8, ["Tax keyword match"], context=_ctx
            )

        # Default to Generic Note if no specific match
        # P0-3: Low confidence fallback → route về Generic (match legacy)
        _ctx["classifier_reason"] = "Fallback"
        _ctx["classifier_primary_type"] = TableType.GENERIC_NOTE.value
        _ctx["classifier_confidence"] = 0.5
        return ClassificationResult(
            TableType.GENERIC_NOTE, 0.5, ["Fallback"], context=_ctx
        )
