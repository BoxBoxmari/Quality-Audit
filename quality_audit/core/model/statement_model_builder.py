from typing import Any, Dict, List

import pandas as pd


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

        table_id = table.get("table_id", "")
        for idx, row in df.iterrows():
            code = str(row[code_col]).strip() if pd.notna(row[code_col]) else ""

            # Heuristic for shifted code into note column due to PDF parsing alignment issues
            if not code and note_col and pd.notna(row[note_col]):
                note_val = str(row[note_col]).strip()
                if note_val.isdigit() and 1 <= len(note_val) <= 2:
                    code = note_val

            if code.endswith(".0"):
                code = code[:-2]
            if code.isdigit() and len(code) == 1:
                code = f"0{code}"

            label = (
                str(row[label_col]).strip()
                if label_col and pd.notna(row[label_col])
                else ""
            )

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


class StatementModelBuilder:
    def build(
        self, tables_info: List[Dict[str, Any]], statement_type: str
    ) -> StatementModel:
        model = StatementModel(statement_type)
        for t_info in tables_info:
            if t_info.get("table_type") == statement_type:
                model.add_table(t_info)
        return model
