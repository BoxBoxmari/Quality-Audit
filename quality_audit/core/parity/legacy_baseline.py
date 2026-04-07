"""
Legacy parity baseline helpers for cross-check cache semantics.

This module centralizes legacy keys and combined-mapping logic so validators
can keep modern structure while preserving legacy outcomes.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional, Tuple

# Legacy cache keys used by reconciliation/cross-check logic.
KEY_AR_SHORT = "accounts receivable from customers"
KEY_AR_LONG = "accounts receivable from customers – long-term"
KEY_AR_LONG_ASCII = "accounts receivable from customers - long-term"
KEY_AR_COMBINED = "accounts receivable from customers-combined"

KEY_AP_SHORT = "accounts payable to suppliers"
KEY_AP_LONG = "long-term accounts payable to suppliers"
KEY_AP_COMBINED = "accounts payable to suppliers-combined"

KEY_NET_DTA_DTL = "Net_DTA_DTL"


def _cache_get(cache: Any, key: str) -> Optional[Tuple[float, float]]:
    value = cache.get(key)
    if value is None:
        return None
    try:
        cur, prior = value
        return (float(cur), float(prior))
    except (TypeError, ValueError):
        return None


def _cache_set(cache: Any, key: str, value: Tuple[float, float]) -> None:
    cache.set(key, value)


def _sum_pair(
    left: Optional[Tuple[float, float]], right: Optional[Tuple[float, float]]
) -> Optional[Tuple[float, float]]:
    if left is None and right is None:
        return None
    lc, lp = left or (0.0, 0.0)
    rc, rp = right or (0.0, 0.0)
    return (lc + rc, lp + rp)


def update_legacy_combined_keys(cache: Any) -> None:
    """
    Recompute legacy combined keys from short/long-term components.

    This mirrors legacy behavior where combined note tables reconcile against
    aggregate FS balances.
    """
    ar_short = _cache_get(cache, KEY_AR_SHORT)
    ar_long = _cache_get(cache, KEY_AR_LONG) or _cache_get(cache, KEY_AR_LONG_ASCII)
    ar_combined = _sum_pair(ar_short, ar_long)
    if ar_combined is not None:
        _cache_set(cache, KEY_AR_COMBINED, ar_combined)

    ap_short = _cache_get(cache, KEY_AP_SHORT)
    ap_long = _cache_get(cache, KEY_AP_LONG)
    ap_combined = _sum_pair(ap_short, ap_long)
    if ap_combined is not None:
        _cache_set(cache, KEY_AP_COMBINED, ap_combined)


def accumulate_net_dta_dtl(
    cache: Any, code: str, current_year: float, prior_year: float
) -> None:
    """
    Legacy netting for deferred tax:
    - code 272 contributes positively
    - code 342 contributes negatively
    """
    if code not in {"272", "342"}:
        return

    old_cur, old_prior = _cache_get(cache, KEY_NET_DTA_DTL) or (0.0, 0.0)
    sign = -1.0 if code == "342" else 1.0
    _cache_set(
        cache,
        KEY_NET_DTA_DTL,
        (old_cur + sign * current_year, old_prior + sign * prior_year),
    )


def choose_receivable_cross_check_key(cache: Any) -> str:
    """
    Legacy key selection for receivable note cross-check.
    Prefer combined key when both short and long-term are available.
    """
    has_short = _cache_get(cache, KEY_AR_SHORT) is not None
    has_long = (
        _cache_get(cache, KEY_AR_LONG) is not None
        or _cache_get(cache, KEY_AR_LONG_ASCII) is not None
    )
    if has_short and has_long and _cache_get(cache, KEY_AR_COMBINED) is not None:
        return KEY_AR_COMBINED
    if has_short:
        return KEY_AR_SHORT
    if has_long:
        return KEY_AR_LONG
    return KEY_AR_SHORT


def choose_payable_cross_check_key(cache: Any) -> str:
    """
    Legacy key selection for payable note cross-check.
    Prefer combined key when both short and long-term are available.
    """
    has_short = _cache_get(cache, KEY_AP_SHORT) is not None
    has_long = _cache_get(cache, KEY_AP_LONG) is not None
    if has_short and has_long and _cache_get(cache, KEY_AP_COMBINED) is not None:
        return KEY_AP_COMBINED
    if has_short:
        return KEY_AP_SHORT
    if has_long:
        return KEY_AP_LONG
    return KEY_AP_SHORT


def resolve_cross_check_key_with_precedence(
    cache: Any,
    explicit_business_key: Optional[str],
    combined_key: Optional[str],
    specific_keys: Iterable[str],
    code_fallback: Optional[str] = None,
) -> str:
    """
    Deterministic key resolution precedence:
    1) explicit business key
    2) combined key
    3) specific short/long keys
    4) code fallback
    """
    if explicit_business_key and _cache_get(cache, explicit_business_key) is not None:
        return explicit_business_key
    if combined_key and _cache_get(cache, combined_key) is not None:
        return combined_key
    for key in specific_keys:
        if key and _cache_get(cache, key) is not None:
            return key
    return code_fallback or explicit_business_key or combined_key or ""
