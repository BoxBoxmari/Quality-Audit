"""
AuditGradeValidator for orchestrating rules per table and model.
"""

from __future__ import annotations

import logging
from typing import Any

from quality_audit.config.constants import (
    SKIP_REASON_ERROR_IN_RULE,
    SKIP_REASON_INVALID_TABLE_INFO,
    SKIP_REASON_NO_RULES_FOR_TYPE,
    SKIP_REASON_REGISTRY_MISS,
    SKIP_REASON_RULES_RAN_NO_EVIDENCE,
    WARN_REASON_STRUCTURE_UNDETERMINED,
)
from quality_audit.core.evidence import ValidationEvidence
from quality_audit.core.materiality import MaterialityEngine
from quality_audit.core.model.financial_model import FinancialModel
from quality_audit.core.reconciliation.reconciliation_engine import ReconciliationEngine
from quality_audit.core.rules.base_rule import AuditRule
from quality_audit.core.rules.rule_registry import RuleRegistry
from quality_audit.utils.canonical_table_type import canonical_table_type

logger = logging.getLogger(__name__)


class AuditGradeValidator:
    """Orchestrates rule evaluation for single tables and full models."""

    def __init__(
        self,
        registry: RuleRegistry,
        materiality: MaterialityEngine,
    ) -> None:
        self.registry = registry
        self.materiality = materiality
        self.reconciler = ReconciliationEngine(self.materiality)

    def validate_table(self, table_info: dict[str, Any]) -> list[ValidationEvidence]:
        """
        Apply all registered rules to a single table.

        Args:
            table_info: Dict containing 'df', 'table_type', 'code_col', 'amount_cols'.

        Returns:
            List of ValidationEvidence records.
        """
        raw_table_type = table_info.get("table_type")
        table_type = canonical_table_type(raw_table_type)
        df = table_info.get("df")
        table_id = table_info.get("table_id")
        amount_cols = table_info.get("amount_cols", [])
        is_numeric = bool(amount_cols)

        # P0: Early-out for truly invalid input
        if not table_type or df is None:
            logger.warning("Invalid table_info passed to validate_table.")
            if is_numeric:
                return [
                    ValidationEvidence.warn_evidence(
                        rule_id="UNVERIFIED_NUMERIC_TABLE",
                        assertion_text="Numeric table skipped — invalid table_info",
                        reason_code=SKIP_REASON_INVALID_TABLE_INFO,
                        table_type=table_type or "UNKNOWN",
                        table_id=table_id,
                    )
                ]
            return []

        # P1: Structure-undetermined is now a WARN, not a hard gate.
        # low_confidence is reserved for cases where we truly have an
        # undetermined NOTE structure, not for tables explicitly marked as
        # NO_TOTAL / LISTING / SINGLE_ROW.
        low_confidence = False
        evidence_list: list[ValidationEvidence] = []

        note_mode = str(table_info.get("note_mode") or "")
        structure_status = str(table_info.get("structure_status") or "")
        note_validation_mode = str(table_info.get("note_validation_mode") or "")

        if table_info.get("is_structure_undetermined") and structure_status in (
            "",
            "STRUCTURE_UNDETERMINED",
        ):
            # Only treat as low-confidence when structure_status is truly
            # undetermined. Structurally-determined NO_TOTAL/LISTING/SINGLE_ROW
            # tables are valid endpoints and should not push BasicNumericChecks into FAIL-mode.
            evidence_list.append(
                ValidationEvidence.warn_evidence(
                    rule_id="NOTE_STRUCTURE_UNDETERMINED",
                    assertion_text="NOTE structure undetermined",
                    reason_code=WARN_REASON_STRUCTURE_UNDETERMINED,
                    table_type=table_type,
                    table_id=table_id,
                )
            )
            low_confidence = True

        rules = self.registry.resolve(table_type)

        # Separate primary rules from fallback BasicNumericChecksRule so that
        # BasicNumeric only runs when structure is low-confidence or primary
        # rules produced no substantive evidence.
        primary_rules = []
        fallback_rules = []
        for r in rules:
            if getattr(r, "rule_id", None) == "BASIC_NUMERIC_CHECKS":
                fallback_rules.append(r)
            else:
                primary_rules.append(r)

        # Phase 2 NOTE planner gating: for GENERIC_NOTE/TAX_NOTE tables, use the
        # coarse validation_mode to deny-by-default any structure-driven NOTE
        # rules that are not appropriate for the chosen archetype.
        if table_type in ("GENERIC_NOTE", "TAX_NOTE") and note_validation_mode:
            gated_primary: list[AuditRule] = []
            for r in primary_rules:
                rule_id = getattr(r, "rule_id", "")
                if note_validation_mode == "MOVEMENT_BY_ROWS":
                    # Movement-by-rows tables may run all NOTE rules.
                    gated_primary.append(r)
                elif note_validation_mode == "MOVEMENT_BY_COLUMNS":
                    # Movement-by-columns tables: delegate to specialised executor
                    # and skip the movement-by-rows rule.
                    if rule_id != "MOVEMENT_EQUATION":
                        gated_primary.append(r)
                elif note_validation_mode == "HIERARCHICAL_NETTING":
                    # Netting tables: only run the specialised netting executor.
                    if rule_id == "NETTING_BLOCKS":
                        gated_primary.append(r)
                elif note_validation_mode == "GENERIC_NUMERIC_NOTE":
                    # Generic numeric notes: allow vertical-sum / breakdown style
                    # rules but not movement roll-forward.
                    if rule_id not in ("MOVEMENT_ROLLFORWARD",):
                        gated_primary.append(r)
                elif note_validation_mode in ("SCOPED_TOTAL", "LISTING_TOTALS"):
                    # Scoped-total modes: only the scoped vertical-sum executor
                    # should run; all other structure-driven NOTE rules are gated
                    # off to avoid spurious WARN/FAIL.
                    if rule_id == "VERTICAL_SUM_SCOPED":
                        gated_primary.append(r)
                elif note_validation_mode == "LISTING_NO_TOTAL":
                    # Listing/NO_TOTAL: totals are not expected; skip all
                    # structure-driven NOTE rules for safety.
                    continue
                else:  # UNDETERMINED and any future modes
                    # Deny-by-default for structure-driven NOTE rules; they rely
                    # on anchors (scopes/segments) we do not trust here.
                    if rule_id not in (
                        "MOVEMENT_ROLLFORWARD",
                        "VERTICAL_SUM_SCOPED",
                        "NOTE_BREAKDOWN_TOTALS",
                    ):
                        gated_primary.append(r)
            primary_rules = gated_primary

        # P2: Detect registry miss
        skip_reason = None
        if not rules and is_numeric:
            skip_reason = SKIP_REASON_REGISTRY_MISS
            logger.info(
                "REGISTRY_MISS table_id=%s table_type=%s — no rules registered",
                table_id,
                table_type,
            )

        code_col = table_info.get("code_col")
        total_row_idx = table_info.get("total_row_idx")
        detail_rows = table_info.get("detail_rows")
        segments = table_info.get("segments")
        scopes = table_info.get("scopes")
        label_col = table_info.get("label_col")
        is_movement_table = table_info.get("is_movement_table", False)
        note_structure_confidence = table_info.get("note_structure_confidence")

        ob_row_idx = table_info.get("ob_row_idx")
        cb_row_idx = table_info.get("cb_row_idx")
        movement_rows = table_info.get("movement_rows")
        if segments and (
            ob_row_idx is None or cb_row_idx is None or movement_rows is None
        ):
            seg = segments[0]
            ob_row_idx = ob_row_idx if ob_row_idx is not None else seg.ob_row_idx
            cb_row_idx = cb_row_idx if cb_row_idx is not None else seg.cb_row_idx
            movement_rows = (
                movement_rows if movement_rows is not None else seg.movement_rows
            )

        eval_kwargs: dict[str, Any] = {
            "df": df,
            "materiality": self.materiality,
            "table_type": table_type,
            "table_id": table_id,
            "code_col": code_col,
            "amount_cols": amount_cols,
            "total_row_idx": total_row_idx,
            "detail_rows": detail_rows,
            "ob_row_idx": ob_row_idx,
            "cb_row_idx": cb_row_idx,
            "movement_rows": movement_rows,
            "segments": segments,
            "scopes": scopes,
            "label_col": label_col,
            "is_movement_table": is_movement_table,
            "note_structure_confidence": note_structure_confidence,
            "note_validation_mode": note_validation_mode,
            "note_validation_plan": table_info.get("note_validation_plan"),
            "low_confidence": low_confidence,
        }

        rule_errors: list[str] = []
        rules_resolved_ids = [r.rule_id for r in rules]

        # First pass: run primary rules
        for rule in primary_rules:
            try:
                rule_evidence = rule.evaluate(**eval_kwargs)
                evidence_list.extend(rule_evidence)
            except Exception as e:
                logger.exception(
                    "Error executing rule %s on table %s: %s",
                    rule.rule_id,
                    table_type,
                    e,
                )
                rule_errors.append(rule.rule_id)

        # Compute substantive evidence (exclude NOTE_STRUCTURE_UNDETERMINED WARN)
        real_evidence = [
            e
            for e in evidence_list
            if e.rule_id not in ("NOTE_STRUCTURE_UNDETERMINED",)
        ]

        # Determine whether fallback numeric diagnostics are allowed for this table.
        # NOTE semantics:
        # - LISTING / SINGLE_ROW / NO_TOTAL_DECLARED and STRUCTURE_NO_TOTAL /
        #   STRUCTURE_LISTING should never trigger vertical-sum style FAILs.
        disallowed_note_modes = {
            "NoteMode.LISTING_NO_TOTAL",
            "LISTING_NO_TOTAL",
            "NoteMode.SINGLE_ROW_DISCLOSURE",
            "SINGLE_ROW_DISCLOSURE",
            "NoteMode.NO_TOTAL_DECLARED",
            "NO_TOTAL_DECLARED",
        }
        disallowed_structure_status = {
            "StructureStatus.STRUCTURE_NO_TOTAL",
            "STRUCTURE_NO_TOTAL",
            "StructureStatus.STRUCTURE_LISTING",
            "STRUCTURE_LISTING",
        }
        allow_fallback_numeric = not (
            note_mode in disallowed_note_modes
            or structure_status in disallowed_structure_status
        )

        # Fallback pass: run BasicNumericChecksRule only when appropriate.
        #
        # For NOTE tables, "no real evidence" is not a safe trigger for fallback;
        # it often means "not applicable" under deny-by-default routing.
        fallback_trigger = low_confidence or (
            (not real_evidence) and table_type not in ("GENERIC_NOTE", "TAX_NOTE")
        )
        if (
            is_numeric
            and fallback_rules
            and allow_fallback_numeric
            and fallback_trigger
        ):
            for rule in fallback_rules:
                try:
                    rule_evidence = rule.evaluate(**eval_kwargs)
                    evidence_list.extend(rule_evidence)
                except Exception as e:
                    logger.exception(
                        "Error executing fallback rule %s on table %s: %s",
                        rule.rule_id,
                        table_type,
                        e,
                    )
                    rule_errors.append(rule.rule_id)

            # Recompute real evidence after fallback rules
            real_evidence = [
                e
                for e in evidence_list
                if e.rule_id not in ("NOTE_STRUCTURE_UNDETERMINED",)
            ]

        # P0: Determine skip_reason if numeric table has no substantive evidence
        if is_numeric and not real_evidence:
            if skip_reason is None:
                if rule_errors:
                    skip_reason = f"{SKIP_REASON_ERROR_IN_RULE}_{rule_errors[0]}"
                elif not rules:
                    skip_reason = SKIP_REASON_NO_RULES_FOR_TYPE
                else:
                    skip_reason = SKIP_REASON_RULES_RAN_NO_EVIDENCE

            evidence_list.append(
                ValidationEvidence.warn_evidence(
                    rule_id="UNVERIFIED_NUMERIC_TABLE",
                    assertion_text=f"Numeric table unverified — {skip_reason}",
                    reason_code=skip_reason,
                    table_type=table_type,
                    table_id=table_id,
                    metadata={"low_confidence": low_confidence},
                )
            )

        # P0: Per-table diagnostics
        logger.info(
            "validate_table diag table_id=%s table_type=%s is_numeric=%s "
            "rules_resolved=%s evidence_count=%d skip_reason=%s low_confidence=%s",
            table_id,
            table_type,
            is_numeric,
            rules_resolved_ids,
            len(real_evidence),
            skip_reason,
            low_confidence,
        )

        return evidence_list

    def validate_model(self, model: FinancialModel) -> list[ValidationEvidence]:
        """
        Analyze a complete FinancialModel including cross-statement checks.

        Returns:
            List of all ValidationEvidence from the entire model.
        """
        from quality_audit.core.model.statement_model_builder import (
            StatementModelBuilder,
        )

        builder = StatementModelBuilder()
        all_evidence = []

        # Process standard statements
        for _, statement_tables in [
            ("FS_INCOME_STATEMENT", model.income_statements),
            ("FS_BALANCE_SHEET", model.balance_sheets),
            ("FS_CASH_FLOW", model.cash_flows),
            ("FS_EQUITY_CHANGES", model.equity_changes),
        ]:
            if not statement_tables:
                continue

            # Group tables by their specific table_type
            table_types: list[str] = sorted(
                {str(t.get("table_type")) for t in statement_tables if t.get("table_type")}
            )

            for t_type in table_types:
                rules = self.registry.resolve(t_type)
                if not rules:
                    continue

                relevant_tables = [
                    t for t in statement_tables if t.get("table_type") == t_type
                ]
                statement_model = builder.build(relevant_tables, t_type)

                for rule in rules:
                    # If the rule overrides evaluate_model, use it
                    if (
                        type(rule).evaluate_model
                        is not __import__(
                            "quality_audit.core.rules.base_rule", fromlist=["AuditRule"]
                        ).AuditRule.evaluate_model
                    ):
                        try:
                            logger.debug(
                                "Running statement-level rule %s", rule.rule_id
                            )
                            rule_evidence = rule.evaluate_model(
                                model=statement_model, materiality=self.materiality
                            )
                            all_evidence.extend(rule_evidence)
                        except Exception as e:
                            logger.exception(
                                "Error executing statement-level rule %s: %s",
                                rule.rule_id,
                                e,
                            )
                    else:
                        # Fallback to legacy evaluate with individual table slices
                        for t in relevant_tables:
                            if t.get("df") is None:
                                continue
                            try:
                                rule_evidence = rule.evaluate(
                                    df=t["df"],
                                    materiality=self.materiality,
                                    table_type=str(t.get("table_type") or ""),
                                    table_id=str(t.get("table_id") or ""),
                                    code_col=str(t.get("code_col") or ""),
                                    amount_cols=t.get("amount_cols", []),
                                    total_row_idx=t.get("total_row_idx"),
                                    detail_rows=t.get("detail_rows"),
                                )
                                all_evidence.extend(rule_evidence)
                            except Exception as e:
                                logger.exception(
                                    "Error executing legacy rule %s on table %s: %s",
                                    rule.rule_id,
                                    t.get("table_id"),
                                    e,
                                )

        # Notes are still validated individually since they are distinct
        for table_info in model.notes:
            all_evidence.extend(self.validate_table(table_info))

        # Perform cross-statement reconciliations
        recon_evidence = self.reconciler.reconcile(model)
        all_evidence.extend(recon_evidence)

        return all_evidence
