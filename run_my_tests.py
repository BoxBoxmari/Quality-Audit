import sys

from tests.test_heading_routing_fixes import (
    test_heading_junk_filter,
    test_structure_override_income_statement,
    test_structure_override_balance_sheet,
    test_structure_override_cashflow,
)


def run_tests():
    try:
        test_heading_junk_filter()
        print("test_heading_junk_filter: PASS")
    except Exception as e:
        print(f"test_heading_junk_filter: FAIL {e}")

    try:
        test_structure_override_income_statement()
        print("test_structure_override_income_statement: PASS")
    except Exception as e:
        print(f"test_structure_override_income_statement: FAIL {e}")

    try:
        test_structure_override_balance_sheet()
        print("test_structure_override_balance_sheet: PASS")
    except Exception as e:
        print(f"test_structure_override_balance_sheet: FAIL {e}")

    try:
        test_structure_override_cashflow()
        print("test_structure_override_cashflow: PASS")
    except Exception as e:
        print(f"test_structure_override_cashflow: FAIL {e}")


if __name__ == "__main__":
    run_tests()
