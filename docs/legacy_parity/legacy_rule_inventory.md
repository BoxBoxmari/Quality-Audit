# Legacy Rule Inventory

## Baseline Authority Lock
- Authoritative baseline union is **only**: `legacy/main.py` + `legacy/Quality Audit.py`.
- Repository root `main.py` is **not** baseline authority.
- Runtime must use ported modules under `quality_audit/core/legacy_audit/*`.
- Runtime must not import legacy scripts by file path.

## Baseline Rule Families (Union Scope)
- Heading and statement-family aliases/routing fallbacks.
- Table catalogs for validation scope (including Form 1/1A/1B/2/3 cross-check families).
- Valid code taxonomy and balance-sheet parent/child trees.
- Cash-flow formula trees.
- Equity anchors, subtotal/vertical-sum semantics.
- Note subtype and cross-check precedence semantics.
- Excel coloring/cross-reference semantics.

## Explicitly Restored in This Pass
- Catalog union expansions in Form families, including Form 1A / 1B / 3 variants.
- Valid code restoration: `234`, `235`, `241`, `242`.
- Legacy heading behavior alignment in `core/legacy_audit/headings.py`.
