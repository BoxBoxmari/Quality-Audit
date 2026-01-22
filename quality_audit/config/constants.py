"""
Constants and configuration values for the Quality Audit application.
"""

import re

from openpyxl.styles import Alignment, Font, PatternFill

# Regex helpers
_SHEET_NAME_CLEAN_RE = re.compile(r"[:\\/*?\[\]]")
_CODE_COL_NAME = "code"
_NOTE_COL_NAME = "note"
_CODE_VALID_RE = re.compile(r"^[0-9]+[A-Z]?$")
_HEADER_DATE_RE = re.compile(r"\d{4}|\d{1,2}/\d{1,2}/\d{2,4}")

# Table types that need column-level checks
TABLES_NEED_COLUMN_CHECK = {
    "long-term prepaid expenses",
    "tangible fixed assets",
    "intangible fixed assets",
    "chi phí trả trước dài hạn",
    "tài sản cố định hữu hình",
    "tài sản cố định vô hình",
    "taxes payable to state treasury",
    "thuế và các khoản phải nộp nhà nước",
    "borrowings",
    "borrowings, bonds and finance lease liabilities",
    "short-term borrowings",
    "long-term borrowings",
}

# Form 1: Tables with possible subtotals, cross-ref at grand total
CROSS_CHECK_TABLES_FORM_1 = {
    "accounts receivable from customers",
    "accounts receivable from customers detailed by significant customer",
    "accounts receivable from customers detailed by significant customers",
    "receivables on construction contracts according to stages of completion",
    "payables on construction contracts according to stages of completion",
    "deferred tax assets and liabilities",
    "deferred tax assets",
    "deferred tax liabilities",
    "accrued expenses",
    "accrued expenses – short-term",
    "accrued expenses - short-term",
    "accrued expenses – long-term",
    "accrued expenses - long-term",
    "unearned revenue",
    "unearned revenue – short-term",
    "unearned revenue – long-term",
    "other payables",
    "other payables – short-term",
    "other payables – long-term",
    "long-term borrowings",
    "long-term borrowings, bonds and financial lease liabilities",
    "long-term bonds and financial lease liabilities",
    "long-term financial lease liabilities",
    "long-term bonds",
}

# Form 2: Tables with possible subtotals, cross-ref at both subtotal and grand total
CROSS_CHECK_TABLES_FORM_2 = {
    "revenue from sales of goods and provision of services",
    "revenue from sales of goods",
    "revenue from provision of services",
}

# Form 3: Tables without subtotals but not standard tables
CROSS_CHECK_TABLES_FORM_3 = {
    "investments",
    "trading securities",
    "held-to-maturity investments",
    "equity investments in other entities",
    "equity investments in other entity",
    "bad and doubtful debts",
    "shortage of assets awaiting resolution",
    "inventories",
    "long-term work in progress",
    "construction in progress",
    "long-term prepaid expenses",
    "accounts payable to suppliers",
    "accounts payable to suppliers detailed by significant suppliers",
    "accounts payable to suppliers detailed by significant supplier",
    "taxes and others payable to state treasury",
    "taxes and others receivable from state treasury",
    "taxes and others receivable from and payable to state treasury",
    "taxes receivable from state treasury",
    "taxes payable to state treasury",
    "short-term borrowings",
    "short-term borrowings, bonds and finance lease liabilities",
    "short-term bonds and finance lease liabilities",
    "short-term bonds",
    "preference shares",
    "provisions",
    "short-term provisions",
    "long-term provisions",
    "share capital",
    "contributed capital",
}

# Valid account codes
VALID_CODES = {"222", "223", "225", "226", "228", "229", "231", "232"}

# Tables that need separate checking logic
TABLES_NEED_CHECK_SEPARATELY = {
    "tangible fixed assets",
    "intangible fixed assets",
    "tài sản cố định hữu hình",
    "tài sản cố định vô hình",
}

# Tables without total rows
TABLES_WITHOUT_TOTAL = {
    "business costs by element",
    "Production and business costs by elements",
    "non-cash investing activity",
    "non-cash investing activities",
    "significant transactions with related parties",
    "significant transactions with related companies",
    "corresponding figures",
}

# Related party table patterns
RE_PARTY_TABLE = {
    "related parties",
    "related party",
    "related companies",
    "related company",
}

# Color definitions for Excel formatting
GREEN_FILL = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")
BLUE_FILL = PatternFill(start_color="90EE90", end_color="90EE90", fill_type="solid")
RED_FILL = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")
INFO_FILL = PatternFill(start_color="DAE8FC", end_color="DAE8FC", fill_type="solid")

GREEN_FONT = Font(color="32CD32")  # Green
RED_FONT = Font(color="FF0000")  # Red
RIGHT_ALIGN = Alignment(horizontal="right")  # Right align
