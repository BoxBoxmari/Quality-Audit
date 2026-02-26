"""
Helper functions for command line argument formatting and quoting.
"""


def quote_cmd_arg(arg: str) -> str:
    """
    Quote a command line argument for Windows CMD if necessary.

    Rules:
    - If arg is empty, return "".
    - If arg contains spaces or special characters, wrap in double quotes.
    - Escape internal double quotes by doubling them.
    - Always safe to quote if unsure.
    """
    if not arg:
        return '""'

    # Check if needs quoting
    needs_quote = False
    special_chars = {
        " ",
        "\t",
        "&",
        "(",
        ")",
        "[",
        "]",
        "{",
        "}",
        "^",
        "=",
        ";",
        "!",
        "'",
        "+",
        ",",
        "`",
        "~",
    }

    if any(c in special_chars for c in arg):
        needs_quote = True

    # Handle internal quotes
    escaped_arg = arg.replace('"', '""')

    if needs_quote or '"' in arg:
        return f'"{escaped_arg}"'

    return arg


def format_command_line(executable: str, module: str, argv: list) -> str:
    """
    Format a full command line string for preview.
    """
    parts = [executable, "-m", module]
    # Quote all user arguments
    parts.extend(quote_cmd_arg(str(a)) for a in argv)
    return " ".join(parts)
