import pandas as pd
from quality_audit.core.validators.base_validator import BaseValidator

df = pd.DataFrame(
    [
        ["", "31/12/2018", "", "1/1/2018", ""],
        ["", "Cost", "Allowance", "Cost", "Allowance"],
        ["", "VND", "VND", "VND", "VND"],
        ["", "", "", "", ""],
        ["Goods in transit", "1,034,514,676,278", "-", "1,111,303,413,550", "-"],
        ["Raw materials", "5,478,208,376,053", "-", "4,002,309,173,484", "-"],
        ["Tools and supplies", "244,281,506,425", "-", "195,176,744,027", "-"],
        ["Work in progress (*)", "6,762,259,095,513", "-", "6,164,436,624,872", "-"],
        [
            "Finished goods",
            "1,010,209,031,985",
            "(695,282,603)",
            "777,792,331,080",
            "(5,315,178,548)",
        ],
        ["", "", "", "", ""],
        [
            "",
            "14,529,472,686,254",
            "(695,282,603)",
            "12,251,018,287,013",
            "(5,315,178,548)",
        ],
    ]
)
df.columns = [str(c) for c in df.columns]


class MockValidator(BaseValidator):
    def validate(self, df):
        pass

    def get_rule_id(self):
        return "MOCK"


v = MockValidator(context=None)
idx = v._find_total_row(df)
print(f"Detected total row index: {idx}")
