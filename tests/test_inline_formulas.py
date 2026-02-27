import pytest
import pandas as pd
from quality_audit.core.validators.income_statement_validator import IncomeStatementValidator

def test_parse_inline_formula_basic():
    validator = IncomeStatementValidator()
    
    # Simple addition
    res = validator._parse_inline_formula("Lợi nhuận gộp (20 = 01 - 11)")
    assert res is not None
    code, children = res
    assert code == "20"
    assert children == ["01", "-11"]

    # Complex formula with parentheses
    res2 = validator._parse_inline_formula("Lợi nhuận kế toán trước thuế (50 = 30 + (40 - 41) - 42)")
    assert res2 is not None
    code2, children2 = res2
    assert code2 == "50"
    assert children2 == ["30", "40", "-41", "-42"]

    # Complex formula provided by user
    res3 = validator._parse_inline_formula("Test user case (30 = 20 + (21 - 22) - 25 - 26)")
    assert res3 is not None
    code3, children3 = res3
    assert code3 == "30"
    assert children3 == ["20", "21", "-22", "-25", "-26"]

    # Missing parentheses
    res4 = validator._parse_inline_formula("This is an unclosed parens text 30 = 20 + 21 - 22 - 25 - 26)")
    assert res4 is not None
    code4, children4 = res4
    assert code4 == "30"
    assert children4 == ["20", "21", "-22", "-25", "-26"]

def test_custom_formula_overrides_default():
    # Setup dataframe where default rule (30 = 20 + 21 - 22 + 24 - 25 - 26) fails
    # But custom rule (30 = 20 + 21 - 22 - 25 - 26) passes
    
    data = {
        "Description": [
            "Lợi nhuận gộp",
            "Doanh thu tài chính",
            "Chi phí tài chính",
            "Chi phí bán hàng",
            "Chi phí quản lý doanh nghiệp",
            "Lợi nhuận thuần (30 = 20 + 21 - 22 - 25 - 26)"
        ],
        "Code": ["20", "21", "22", "25", "26", "30"],
        "Current Year": [1000, 200, 100, 300, 200, 600], # 1000 + 200 - 100 - 300 - 200 = 600
        "Prior Year": [1000, 200, 100, 300, 200, 600]
    }
    
    df = pd.DataFrame(data)
    
    validator = IncomeStatementValidator()
    result = validator.validate(df)
    
    # Look at the issues, should be PASS and no calculation mismatches
    assert result.status.startswith("PASS")
    assert result.assertions_count > 0
