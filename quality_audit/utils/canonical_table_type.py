"""
Canonical table type normalisation utility.

Single source of truth for mapping raw table_type values
(from TableType enum or legacy strings) to the UPPER_CASE
registry keys used by RuleRegistry.
"""

from __future__ import annotations

# Exhaustive map from known raw values to registry keys.
_RAW_TO_CANONICAL: dict[str, str] = {
    "fs_balance_sheet": "FS_BALANCE_SHEET",
    "fs_income_statement": "FS_INCOME_STATEMENT",
    "fs_cash_flow": "FS_CASH_FLOW",
    "fs_equity": "FS_EQUITY",
    "generic_note": "GENERIC_NOTE",
    "tax_note": "TAX_NOTE",
    "unknown": "UNKNOWN",
}


def canonical_table_type(raw: str | None) -> str:
    """Return the canonical (UPPER_CASE) table type for a raw value.

    Handles:
    - ``None`` → ``"UNKNOWN"``
    - TableType enum ``.value`` (snake_case) via lookup table
    - Already-UPPER_CASE strings pass through unchanged
    - Unrecognised strings are upper-cased as best-effort

    >>> canonical_table_type("fs_balance_sheet")
    'FS_BALANCE_SHEET'
    >>> canonical_table_type("GENERIC_NOTE")
    'GENERIC_NOTE'
    >>> canonical_table_type(None)
    'UNKNOWN'
    """
    if raw is None:
        return "UNKNOWN"

    raw_stripped = raw.strip()
    if not raw_stripped:
        return "UNKNOWN"

    # Fast path: already canonical / uppercase
    if raw_stripped in _RAW_TO_CANONICAL.values():
        return raw_stripped

    # Lookup from snake_case enum value
    canonical = _RAW_TO_CANONICAL.get(raw_stripped.lower())
    if canonical is not None:
        return canonical

    # Best-effort fallback
    return raw_stripped.upper()
