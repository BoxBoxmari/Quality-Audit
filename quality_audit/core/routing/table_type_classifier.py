"""
Table Type Classifier for intelligent routing of financial tables.
Distinguishes between main Financial Statements (BS, IS, CF, EQ) and Notes/Disclosures.

NON-RUNTIME OWNER (canonical mode): kept for experimental/shadow flows only.
Production correctness is owned by legacy/main.py single-path runtime.
"""

import logging
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

import pandas as pd

from quality_audit.config.feature_flags import get_feature_flags

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
        has_cf_sections = False

        scan_rows = min(60, total_rows)

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

                # Cash flow section signals.
                #
                # IMPORTANT: do NOT treat generic words like "operating" as a cash-flow indicator
                # because income statements often contain "operating profit/expense".
                # We only flag cash-flow when we see explicit "activities/ cash flows" section labels.
                if any(
                    p in row_text
                    for p in (
                        "cash flows from operating",
                        "cash flows from investing",
                        "cash flows from financing",
                        "operating activities",
                        "investing activities",
                        "financing activities",
                        "hoạt động kinh doanh",
                        "hoạt động đầu tư",
                        "hoạt động tài chính",
                    )
                ):
                    has_cf_sections = True

                if (
                    any(p in row_text for p in keyword_map["assets"])
                    and i < early_window
                ):
                    has_assets_in_early = True

                # Check for code patterns in first few columns
                # Heuristic: row has numeric code in col 0, 1 or 2
                for j in range(min(5, len(table.columns))):
                    raw = str(table.iloc[i, j]).strip()
                    # Normalize common extraction artifacts (e.g. "01.", "21)", "30 -")
                    val = re.sub(r"[^0-9A-Za-z]", "", raw)
                    if re.match(r"^\d{2,3}[a-zA-Z]?$", val):
                        m_code = re.match(r"^(\d{2,3})", val)
                        if m_code is not None:
                            found_codes.add(m_code.group(1))
                        code_rows += 1
                        break
                    elif re.match(r"^[IVX]+$", raw):
                        code_rows += 1
                        break
            except Exception:
                continue

        code_density = code_rows / scan_rows if scan_rows > 0 else 0

        _ctx = {"scan_rows": scan_rows, "classifier_reason": ""}
        logger.debug(
            "Classifier scan: scan_rows=%s, has_assets=%s, has_liabilities=%s, has_assets_early=%s, code_density=%.2f",
            scan_rows,
            has_keywords["assets"],
            has_keywords["liabilities"],
            has_assets_in_early,
            code_density,
        )

        effective_heading = heading_lower
        if bool(flags.get("heading_fallback_from_table_first_row", False)) and (
            not effective_heading or effective_heading.strip() in {"", "unknown", "n/a"}
        ):
            # Heading fallback: infer a usable heading signal from the first few rows.
            # This is intentionally conservative: it only activates when heading is missing/garbage.
            try:
                for i in range(min(15, len(table))):
                    row_text = " ".join(
                        [
                            str(x).strip().lower()
                            for x in table.iloc[i].tolist()
                            if pd.notna(x) and str(x).strip()
                        ]
                    ).strip()
                    if row_text:
                        effective_heading = row_text
                        _ctx["heading_fallback_used"] = True
                        break
            except Exception:
                # Keep original heading_lower if fallback inference fails.
                pass

        # 3. Routing Logic - P0-3: Match legacy routing với guardrails
        # Priority 1: Exact heading match (match legacy check_table_total logic)
        # Priority 2: Content-based fallback nếu heading unknown/null/garbage
        # Guardrails: Nếu heading match nhưng content không match → route GENERIC_NOTE
        # Balance Sheet - Exact heading match với guardrails (use effective_heading)
        if (
            effective_heading == "balance sheet"
            or "statement of financial position" in effective_heading
            or "cân đối kế toán" in effective_heading
        ):
            _ctx["classifier_reason"] = (
                "Exact heading match"
                if effective_heading == "balance sheet"
                else "Legacy heading map match"
            )
            _ctx["classifier_primary_type"] = TableType.FS_BALANCE_SHEET.value
            _ctx["classifier_confidence"] = 0.95
            return ClassificationResult(
                TableType.FS_BALANCE_SHEET,
                0.95,
                [str(_ctx["classifier_reason"])],
                context=_ctx,
            )

        # Income Statement - Exact heading match với guardrails
        if (
            "statement of income" in effective_heading
            or "income statement" in effective_heading
            or "kết quả kinh doanh" in effective_heading
        ):
            _ctx["classifier_reason"] = "Exact heading match"
            _ctx["classifier_primary_type"] = TableType.FS_INCOME_STATEMENT.value
            _ctx["classifier_confidence"] = 0.95
            return ClassificationResult(
                TableType.FS_INCOME_STATEMENT,
                0.95,
                ["Exact heading match"],
                context=_ctx,
            )

        # Cash Flow - Exact heading match với guardrails
        if (
            "statement of cash flows" in effective_heading
            or "lưu chuyển tiền" in effective_heading
        ):
            _ctx["classifier_reason"] = "Exact heading match"
            _ctx["classifier_primary_type"] = TableType.FS_CASH_FLOW.value
            _ctx["classifier_confidence"] = 0.95
            return ClassificationResult(
                TableType.FS_CASH_FLOW,
                0.95,
                ["Exact heading match"],
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

        # Content-based routing (heading unknown or non-exact).
        # Balance sheet evidence: code density + assets early + liabilities anywhere in scan.
        bs_code_density_threshold = float(
            flags.get("routing_balance_sheet_code_density_threshold", 0.2)
        )
        if (
            not has_cf_sections
            and has_assets_in_early
            and has_keywords["liabilities"]
            and code_density >= bs_code_density_threshold
        ):
            _ctx["classifier_reason"] = "Structure-based override (assets+liabilities+code density)"
            _ctx["classifier_primary_type"] = TableType.FS_BALANCE_SHEET.value
            _ctx["classifier_confidence"] = 0.8
            return ClassificationResult(
                TableType.FS_BALANCE_SHEET,
                0.8,
                ["Structure-based override (assets+liabilities+code density)"],
                context=_ctx,
            )

        # Balance sheet structure override: classic BS code families even if labels are abbreviated.
        bs_codes = {"100", "110", "270", "300", "440"}
        if (
            not has_cf_sections
            and code_density >= bs_code_density_threshold
            and len(found_codes.intersection(bs_codes)) >= 2
        ):
            _ctx["classifier_reason"] = "Structure-based override (BS codes)"
            _ctx["classifier_primary_type"] = TableType.FS_BALANCE_SHEET.value
            _ctx["classifier_confidence"] = 0.75
            return ClassificationResult(
                TableType.FS_BALANCE_SHEET,
                0.75,
                ["Structure-based override (BS codes)"],
                context=_ctx,
            )

        # Income statement evidence: P&L code families and revenue/profit signals.
        is_code_density_threshold = float(
            flags.get("routing_income_statement_code_density_threshold", 0.15)
        )
        pl_codes = {"01", "11", "20", "21", "22", "30", "50", "60"}
        if (
            not has_cf_sections
            and code_density >= is_code_density_threshold
            and (
                has_keywords["revenue"]
                or has_keywords["profit"]
                or len(found_codes.intersection(pl_codes)) >= 4
            )
            and len(found_codes.intersection(pl_codes)) >= 2
        ):
            _ctx["classifier_reason"] = "Structure-based override (P&L codes)"
            _ctx["classifier_primary_type"] = TableType.FS_INCOME_STATEMENT.value
            _ctx["classifier_confidence"] = 0.8
            return ClassificationResult(
                TableType.FS_INCOME_STATEMENT,
                0.8,
                ["Structure-based override (P&L codes)"],
                context=_ctx,
            )

        # Income statement fallback (no-code/low-code tables):
        # Some DOCX extractions drop the code column for IS fragments; allow keyword-only routing
        # when balance-sheet signals are absent.
        if (
            not has_cf_sections
            and (has_keywords["revenue"] or has_keywords["profit"])
            and not has_keywords["assets"]
            and not has_keywords["liabilities"]
        ):
            _ctx["classifier_reason"] = "Content evidence (revenue/profit)"
            _ctx["classifier_primary_type"] = TableType.FS_INCOME_STATEMENT.value
            _ctx["classifier_confidence"] = 0.7
            return ClassificationResult(
                TableType.FS_INCOME_STATEMENT,
                0.7,
                ["Content evidence (revenue/profit)"],
                context=_ctx,
            )

        # Cash flow evidence: cash/flows keywords + typical CF code families.
        cf_code_density_threshold = float(
            flags.get("routing_cash_flow_code_density_threshold", 0.12)
        )
        cf_codes = {"20", "30", "40", "50", "60", "70"}
        if (
            code_density >= cf_code_density_threshold
            and (has_keywords["cash"] or has_keywords["flows"])
            and len(found_codes.intersection(cf_codes)) >= 2
        ):
            _ctx["classifier_reason"] = "Content evidence (cash flow codes)"
            _ctx["classifier_primary_type"] = TableType.FS_CASH_FLOW.value
            _ctx["classifier_confidence"] = 0.75
            return ClassificationResult(
                TableType.FS_CASH_FLOW,
                0.75,
                ["Content evidence (cash flow codes)"],
                context=_ctx,
            )

        # Cash flow structure override (language-agnostic):
        # If table contains explicit CF section labels (operating/investing/financing),
        # allow routing even when code families differ from the legacy set.
        if (
            has_cf_sections
            and code_density >= float(flags.get("routing_cash_flow_code_density_threshold", 0.12))
            and len(found_codes) >= 5
        ):
            _ctx["classifier_reason"] = "Structure-based override (cash flow sections)"
            _ctx["classifier_primary_type"] = TableType.FS_CASH_FLOW.value
            _ctx["classifier_confidence"] = 0.7
            return ClassificationResult(
                TableType.FS_CASH_FLOW,
                0.7,
                ["Structure-based override (cash flow sections)"],
                context=_ctx,
            )

        # Default to Generic Note if no specific match
        # P0-3: Low confidence fallback → route về Generic (match legacy)
        _ctx["classifier_reason"] = "Fallback"
        _ctx["classifier_primary_type"] = TableType.GENERIC_NOTE.value
        _ctx["classifier_confidence"] = 0.5
        return ClassificationResult(
            TableType.GENERIC_NOTE, 0.5, ["Fallback"], context=_ctx
        )
