#!/usr/bin/env python3
"""
Quality Audit Tool - Dependency Verification Script
Run this script after installation to verify all dependencies are working correctly.
"""

import platform
import sys
from typing import Dict, Tuple


def check_python_version() -> Tuple[bool, str]:
    """Check if Python version meets requirements."""
    version = sys.version_info
    current = f"{version.major}.{version.minor}.{version.micro}"

    if version.major < 3 or (version.major == 3 and version.minor < 8):
        return False, f"Python {current} is too old. Minimum required: 3.8.0"

    return True, f"Python {current} - OK"


def check_dependencies() -> Tuple[bool, Dict[str, str]]:
    """Check all required dependencies."""
    dependencies = {
        "pandas": "Data processing and analysis",
        "numpy": "Numerical computing",
        "openpyxl": "Excel file handling",
        "docx": "Word document processing",
    }

    results = {}

    for module, purpose in dependencies.items():
        try:
            __import__(module)
            # Try to get version
            try:
                module_obj = __import__(module)
                version = getattr(module_obj, "__version__", "unknown")
                results[module] = f"OK (v{version}) - {purpose}"
            except (AttributeError, TypeError):
                results[module] = f"OK - {purpose}"
        except ImportError as e:
            results[module] = f"FAILED - {purpose}: {e}"

    # Check tkinter separately
    try:
        import tkinter  # noqa: F401

        results["tkinter"] = "OK - GUI components"
    except ImportError:
        results["tkinter"] = (
            "WARNING - GUI components not available (file dialogs may not work)"
        )

    all_good = all(not result.startswith("FAILED") for result in results.values())
    return all_good, results


def check_system_info() -> Dict[str, str]:
    """Get system information."""
    return {
        "Platform": platform.platform(),
        "Architecture": platform.machine(),
        "Python Executable": sys.executable,
        "Working Directory": sys.path[0],
    }


def main():
    """Main verification function."""
    print("=" * 60)
    print("QUALITY AUDIT TOOL - DEPENDENCY VERIFICATION")
    print("=" * 60)
    print()

    # System information
    print("SYSTEM INFORMATION:")
    print("-" * 30)
    system_info = check_system_info()
    for key, value in system_info.items():
        print(f"{key}: {value}")
    print()

    # Python version check
    print("PYTHON VERSION CHECK:")
    print("-" * 30)
    python_ok, python_msg = check_python_version()
    status = "PASS" if python_ok else "FAIL"
    print(f"{status}: {python_msg}")
    print()

    # Dependencies check
    print("DEPENDENCY CHECK:")
    print("-" * 30)
    deps_ok, dep_results = check_dependencies()

    for module, result in dep_results.items():
        if result.startswith("OK"):
            print(f"PASS: {module} - {result}")
        elif result.startswith("WARNING"):
            print(f"WARN: {module} - {result}")
        else:
            print(f"FAIL: {module} - {result}")
    print()

    # Overall result
    print("VERIFICATION RESULT:")
    print("-" * 30)

    overall_success = python_ok and deps_ok

    if overall_success:
        print("ALL CHECKS PASSED")
        print("Quality Audit Tool is ready for use!")
        return_code = 0
    else:
        print("SOME CHECKS FAILED")
        print("Please resolve the issues above before using the tool.")
        return_code = 1

    print()
    print("=" * 60)

    # Instructions
    if not overall_success:
        print("TROUBLESHOOTING:")
        print("- Check if Python 3.8+ is installed")
        print("- Run: pip install -r requirements.txt")
        print("- For tkinter issues on Linux: sudo apt-get install python3-tk")
        print("- Contact IT support if issues persist")
        print("=" * 60)

    sys.exit(return_code)


if __name__ == "__main__":
    main()
