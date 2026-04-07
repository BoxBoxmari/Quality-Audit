from quality_audit.core.cache_manager import LRUCacheManager
from quality_audit.core.parity.legacy_baseline import (
    KEY_AP_COMBINED,
    KEY_AP_LONG,
    KEY_AP_SHORT,
    KEY_AR_COMBINED,
    KEY_AR_LONG,
    KEY_AR_SHORT,
    KEY_NET_DTA_DTL,
    accumulate_net_dta_dtl,
    choose_payable_cross_check_key,
    choose_receivable_cross_check_key,
    resolve_cross_check_key_with_precedence,
    update_legacy_combined_keys,
)


def _cache() -> LRUCacheManager:
    return LRUCacheManager()


def test_update_legacy_combined_keys_builds_ar_ap_combined() -> None:
    cache = _cache()
    cache.set(KEY_AR_SHORT, (100.0, 80.0))
    cache.set(KEY_AR_LONG, (40.0, 20.0))
    cache.set(KEY_AP_SHORT, (55.0, 25.0))
    cache.set(KEY_AP_LONG, (45.0, 35.0))

    update_legacy_combined_keys(cache)

    assert cache.get(KEY_AR_COMBINED) == (140.0, 100.0)
    assert cache.get(KEY_AP_COMBINED) == (100.0, 60.0)


def test_accumulate_net_dta_dtl_preserves_legacy_sign_convention() -> None:
    cache = _cache()

    accumulate_net_dta_dtl(cache, "272", 200.0, 150.0)
    accumulate_net_dta_dtl(cache, "342", 50.0, 20.0)

    assert cache.get(KEY_NET_DTA_DTL) == (150.0, 130.0)


def test_choose_receivable_key_prefers_combined_when_short_and_long_present() -> None:
    cache = _cache()
    cache.set(KEY_AR_SHORT, (10.0, 5.0))
    cache.set(KEY_AR_LONG, (3.0, 1.0))
    update_legacy_combined_keys(cache)

    assert choose_receivable_cross_check_key(cache) == KEY_AR_COMBINED


def test_choose_payable_key_prefers_long_when_only_long_present() -> None:
    cache = _cache()
    cache.set(KEY_AP_LONG, (3.0, 2.0))

    assert choose_payable_cross_check_key(cache) == KEY_AP_LONG


def test_resolve_cross_check_key_precedence() -> None:
    cache = _cache()
    cache.set(KEY_AR_SHORT, (10.0, 5.0))
    cache.set(KEY_AR_LONG, (3.0, 1.0))
    update_legacy_combined_keys(cache)

    selected = resolve_cross_check_key_with_precedence(
        cache=cache,
        explicit_business_key=KEY_AR_SHORT,
        combined_key=KEY_AR_COMBINED,
        specific_keys=[KEY_AR_LONG],
        code_fallback="131",
    )
    assert selected == KEY_AR_SHORT
