from typing import Any, Dict, List

import pandas as pd

# Subtotal label keywords for CF code 13 (do not assign code so row is excluded from code-13 sum)
_CF20_SUBTOTAL_LABEL_KEYWORDS = (
    "subtotal",
    "cash generated from operations",
    "total from operating",
    "tổng từ hoạt động kinh doanh",
)


def _is_cf20_subtotal_label(label: str) -> bool:
    label = (label or "").lower()
    return any(kw in label for kw in _CF20_SUBTOTAL_LABEL_KEYWORDS)


class StatementRow:
    def __init__(
        self,
        code: str,
        label: str,
        values: Dict[str, float],
        source_idx: int = -1,
        table_id: str = "",
    ):
        self.code = str(code).strip()
        if self.code.endswith(".0"):
            self.code = self.code[:-2]
        if self.code.isdigit() and len(self.code) == 1:
            self.code = f"0{self.code}"
        self.label = str(label).strip()
        self.values = values
        self.source_idx = source_idx
        self.table_id = table_id


class StatementModel:
    def __init__(self, statement_type: str):
        self.statement_type = statement_type
        self.rows: List[StatementRow] = []

    def add_table(self, table: Dict[str, Any]):
        df = table.get("df")
        if df is None or df.empty:
            return

        code_col = table.get("code_col")
        amount_cols = table.get("amount_cols", [])

        if not code_col or not amount_cols:
            return

        # Find a label column and note column
        label_col = None
        note_col = None
        for col in df.columns:
            if col != code_col and col not in amount_cols:
                col_str = str(col).lower()
                if not note_col and (
                    "note" in col_str or "thuyết minh" in col_str or col_str == "tm"
                ):
                    note_col = col
                elif not label_col:
                    label_col = col

        # Fallback candidate columns for shifted codes (e.g. codes parsed into a
        # neighbouring non-amount column such as "Unnamed: 2").
        candidate_code_cols: List[str] = []
        for col in df.columns:
            if col in (code_col, note_col) or col in amount_cols:
                continue
            candidate_code_cols.append(col)

        table_id = table.get("table_id", "")
        for idx, row in df.iterrows():
            code = str(row[code_col]).strip() if pd.notna(row[code_col]) else ""

            # Heuristic for shifted code into note column due to PDF parsing alignment issues
            if not code and note_col and pd.notna(row[note_col]):
                note_val = str(row[note_col]).strip()
                if note_val.isdigit() and 1 <= len(note_val) <= 2:
                    code = note_val

            # Additional heuristic: scan other non-amount columns for short numeric
            # strings that look like codes when primary code and note columns are empty.
            if not code and candidate_code_cols:
                for cand_col in candidate_code_cols:
                    val = row[cand_col]
                    if pd.isna(val) or val is None:
                        continue
                    cand_str = str(val).strip()
                    if cand_str.endswith(".0"):
                        cand_str = cand_str[:-2]
                    if cand_str.isdigit() and 1 <= len(cand_str) <= 2:
                        code = cand_str
                        break

            if code.endswith(".0"):
                code = code[:-2]
            if code.isdigit() and len(code) == 1:
                code = f"0{code}"

            label = (
                str(row[label_col]).strip()
                if label_col and pd.notna(row[label_col])
                else ""
            )

            if (
                table.get("table_type") == "FS_CASH_FLOW"
                and code == "13"
                and _is_cf20_subtotal_label(label)
            ):
                code = ""

            values = {}
            for col in amount_cols:
                val = row[col]
                vf = 0.0
                if pd.notna(val) and val is not None:
                    if isinstance(val, (int, float)):
                        vf = float(val)
                    else:
                        s = str(val).strip()
                        is_negative = False
                        if s.startswith("(") and s.endswith(")"):
                            is_negative = True
                            s = s[1:-1].strip()
                        elif s.startswith("-"):
                            is_negative = True
                            s = s[1:].strip()
                        s = s.replace(",", "").replace(" ", "")
                        try:
                            vf = float(s)
                            if is_negative:
                                vf = -vf
                        except ValueError:
                            pass
                values[col] = vf

            self.rows.append(StatementRow(code, label, values, idx, table_id))

    def find_code(self, code: str) -> List[StatementRow]:
        code = str(code).strip()
        if code.isdigit() and len(code) == 1:
            code = f"0{code}"
        return [r for r in self.rows if r.code == code]

    def find_label(self, text: str) -> List[StatementRow]:
        return [r for r in self.rows if text.lower() in r.label.lower()]

    @property
    def is_narrative_statement(self) -> bool:
        """
        Check if the table is likely a narrative/note table misrouted as an FS table.
        Heuristic: if a significant portion of the non-empty codes are letters (a, b, c)
        or roman numerals (i, ii), it's probably a note.
        """
        if not self.rows:
            return False

        narrative_codes = 0
        valid_codes = 0
        for r in self.rows:
            c = r.code.strip().lower()
            if not c:
                continue
            valid_codes += 1
            # Check for single letters (a, b, c) or common roman numerals
            if (len(c) == 1 and c.isalpha()) or c in (
                "i",
                "ii",
                "iii",
                "iv",
                "v",
                "vi",
            ):
                narrative_codes += 1

        if valid_codes == 0:
            return False

        # If >= 30% of rows have narrative-style keys, consider it a narrative table
        return (narrative_codes / valid_codes) >= 0.3


class StatementModelBuilder:
    def build(
        self, tables_info: List[Dict[str, Any]], statement_type: str
    ) -> StatementModel:
        model = StatementModel(statement_type)
        for t_info in tables_info:
            if t_info.get("table_type") == statement_type:
                model.add_table(t_info)
        return model
