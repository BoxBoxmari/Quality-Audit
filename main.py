import sys

from quality_audit.cli import main

if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
