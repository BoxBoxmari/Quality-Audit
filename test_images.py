import pandas as pd
from quality_audit.core.routing.table_type_classifier import TableTypeClassifier
from quality_audit.core.validators.generic_validator import GenericTableValidator

print("1. Testing Cash Flow override logic...")
# Mock cash flow operating activities
df_cf = pd.DataFrame(
    {
        "Col1": [
            "Accounting profit before tax",
            "Depreciation",
            "Change in receivables",
            "Change in payables",
            "Net cash flow",
        ],
        "Code": ["1", "2", "9", "11", "20"],
    }
)

classifier = TableTypeClassifier()
result = classifier.classify(df_cf, "CASH FLOWS FROM OPERATING ACTIVITIES", 1.0)
print("Classification:", result.primary_type)
print("Reason:", result.reasons)

print("\n2. Testing GenericTableValidator on Equity table...")
df_equity = pd.DataFrame(
    {
        "Description": [
            "Balance at 1 Jan 2017",
            "Profit",
            "Balance at 1 Jan 2018",
            "Loss",
            "Balance at 31 Dec 2018",
        ],
        "Contributed": [127629418, 0, 127629418, 0, 127629418],
        "Retained": [309329416, 106223262, 415552678, -37747182, 377805496],
        "Total": [436958834, 106223262, 543182096, -37747182, 505434914],
    }
)

validator = GenericTableValidator()
res = validator.validate(df_equity, "Changes in Equity", {})
print("Validation Status:", res.status)
for mark in getattr(res, "marks", []):
    if not mark["ok"]:
        print(
            f"Failed mark: Row {mark.get('row', '?')}, Col {mark.get('col', '?')} -> {mark.get('comment', '')}"
        )
