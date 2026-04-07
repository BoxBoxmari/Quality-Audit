"""
Legacy cross-check key resolution wrappers.
"""

from quality_audit.core.parity.legacy_baseline import (
    KEY_AP_COMBINED,
    KEY_AP_LONG,
    KEY_AP_SHORT,
    KEY_AR_COMBINED,
    KEY_AR_LONG,
    KEY_AR_SHORT,
    choose_payable_cross_check_key,
    choose_receivable_cross_check_key,
    resolve_cross_check_key_with_precedence,
    update_legacy_combined_keys,
)

__all__ = [
    "KEY_AR_SHORT",
    "KEY_AR_LONG",
    "KEY_AR_COMBINED",
    "KEY_AP_SHORT",
    "KEY_AP_LONG",
    "KEY_AP_COMBINED",
    "update_legacy_combined_keys",
    "choose_receivable_cross_check_key",
    "choose_payable_cross_check_key",
    "resolve_cross_check_key_with_precedence",
]
