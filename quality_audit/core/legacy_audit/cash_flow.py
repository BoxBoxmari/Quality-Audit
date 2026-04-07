"""
Legacy hardcoded cash-flow formula map by statement code.

These are authoritative baseline relations used by default runtime.
"""

CASH_FLOW_CODE_FORMULAS = {
    # Legacy operating cash-flow subtotal
    "08": ("01", "02", "03", "04", "05", "06", "07"),
    # Legacy indirect adjustment block often emitted without explicit code cell
    "18": ("14", "15", "16", "17"),
    "20": ("08", "09", "10", "11", "12", "13", "14", "15", "16", "17"),
    "30": ("21", "22", "23", "24", "25", "26", "27"),
    "40": ("31", "32", "33", "34", "35", "36"),
    "50": ("20", "30", "40"),
    "60": ("50", "51", "52", "53", "54", "55", "56", "57"),
    "70": ("60", "61"),
}
