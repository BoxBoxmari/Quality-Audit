"""
Command formatting utilities for CMD-safe preview and copy functionality.
"""


def quote_cmd_token(token: str) -> str:
    """
    Wrap token in double quotes if it contains spaces or special chars.
    Escape embedded quotes by doubling: " -> ""

    Args:
        token: Command line token to quote

    Returns:
        Quoted token if needed, otherwise unquoted token
    """
    if not token:
        return '""'

    # Special characters that require quoting in Windows CMD
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
        "~",
    }

    needs_quote = any(c in token for c in special_chars)

    # Escape embedded quotes by doubling
    escaped_token = token.replace('"', '""')

    if needs_quote or '"' in token:
        return f'"{escaped_token}"'

    return token


def format_cmd_preview(argv: list[str], wrap_width: int = 86) -> str:
    """
    Format command preview with multi-line grouping for readability.
    Preserves all tokens from argv and wraps at token boundaries.

    Args:
        argv: List of command line arguments
        wrap_width: Maximum line width for wrapping

    Returns:
        Multi-line formatted command string
    """
    if not argv:
        return "$ python -m quality_audit.cli"

    # Quote all tokens first
    quoted_tokens = [quote_cmd_token(str(arg)) for arg in argv]

    # First line: base command with input path
    base_cmd = "$ python -m quality_audit.cli"
    first_token = quoted_tokens[0] if quoted_tokens else ""
    first_line = f"{base_cmd} {first_token}"
    lines = [first_line]

    # Process remaining tokens with width-aware wrapping
    remaining_tokens = quoted_tokens[1:]
    if not remaining_tokens:
        return lines[0]

    indent = "  "
    current_line = indent
    current_length = len(indent)

    for token in remaining_tokens:
        # Calculate space needed: current line length + space + token length
        space_needed = current_length + 1 + len(token)

        # If adding this token would exceed wrap_width, start a new line
        if current_length > len(indent) and space_needed > wrap_width:
            lines.append(current_line.rstrip())
            current_line = indent + token
            current_length = len(indent) + len(token)
        else:
            # Add token to current line
            if current_length > len(indent):
                current_line += " " + token
                current_length += 1 + len(token)
            else:
                current_line += token
                current_length += len(token)

    # Append the last line if it has content
    if current_line.strip() != indent.strip():
        lines.append(current_line.rstrip())

    return "\n".join(lines)


def flatten_cmd(argv: list[str]) -> str:
    """
    Join all tokens into a single-line CMD-safe string.

    Args:
        argv: List of command line arguments

    Returns:
        Single-line command string with proper quoting
    """
    parts = ["python", "-m", "quality_audit.cli"]
    parts.extend(quote_cmd_token(str(arg)) for arg in argv)
    return " ".join(parts)
