"""
Secure file handling operations with path validation and safe file opening.
"""

from pathlib import Path
from typing import TYPE_CHECKING, Optional, Set

if TYPE_CHECKING:
    from quality_audit.core.cache_manager import AuditContext

# Module-level cache for tax rate mode and shared tax rate
_tax_rate_mode: Optional[str] = None  # "all" or "individual"
_shared_tax_rate: Optional[float] = None  # Cached tax rate for "all" mode


class FileHandler:
    """Handles secure file operations with path validation."""

    ALLOWED_EXTENSIONS = {".docx", ".xlsx"}
    MAX_FILE_SIZE_MB = 50  # Maximum file size in MB

    @staticmethod
    def validate_path(file_path: str) -> bool:
        """
        Validate file path for security.

        Args:
            file_path: Path to validate

        Returns:
            bool: True if path is valid and safe
        """
        return FileHandler.validate_path_secure(
            file_path, FileHandler.ALLOWED_EXTENSIONS
        )

    @staticmethod
    def validate_path_secure(
        file_path: str,
        allowed_extensions: Optional[Set[str]] = None,
        base_dir: Optional[Path] = None,
    ) -> bool:
        """
        Secure path validation with strict directory traversal prevention.

        Args:
            file_path: Path to validate
            allowed_extensions: Set of allowed file extensions (defaults to ALLOWED_EXTENSIONS)
            base_dir: Optional base directory to restrict paths to (None = no restriction)

        Returns:
            bool: True if path is valid and safe
        """
        try:
            allowed_extensions = allowed_extensions or FileHandler.ALLOWED_EXTENSIONS

            # Check for .. in raw path parts before resolve() (traversal detection)
            raw_path = Path(file_path)
            if ".." in raw_path.parts:
                return False

            # Resolve path and validate existence (strict=True raises if not exists)
            resolved_path = Path(file_path).resolve(strict=True)

            # If base_dir is provided, enforce directory restriction
            if base_dir is not None:
                base_path = Path(base_dir).resolve(strict=True)
                try:
                    # Check if resolved path is within base directory
                    resolved_path.relative_to(base_path)
                except ValueError:
                    # Path is outside base directory
                    return False

            # Extension check
            if resolved_path.suffix.lower() not in allowed_extensions:
                return False

            # File type check (already validated by strict=True, but double-check)
            if not resolved_path.is_file():
                return False

            # File size check
            max_size = FileHandler.MAX_FILE_SIZE_MB * 1024 * 1024  # Convert MB to bytes
            return not resolved_path.stat().st_size > max_size

        except (OSError, ValueError, FileNotFoundError):
            # Log specific error for debugging (if logger available)
            # logger.debug(f"Path validation failed: {e}")
            return False

    @staticmethod
    def validate_docx_safety(file_path: str) -> bool:
        """
        Validate DOCX file against zip-bomb attacks.
        Checks for excessive compression ratio and total size.

        Args:
            file_path: Path to DOCX file

        Returns:
            bool: True if safe, False if potential zip bomb
        """
        import zipfile

        max_ratio = 100  # Threshold for compression ratio
        max_unzipped_size = 500 * 1024 * 1024  # 500 MB limit

        try:
            with zipfile.ZipFile(file_path, "r") as zf:
                total_size = 0
                total_packed = 0
                for info in zf.infolist():
                    total_size += info.file_size
                    total_packed += info.compress_size

                if total_size > max_unzipped_size:
                    # Logs could be added here
                    return False

                if total_packed > 0:
                    ratio = total_size / total_packed
                    if ratio > max_ratio:
                        return False

            return True
        except zipfile.BadZipFile:
            return False
        except Exception:
            # Allow open failure to be handled later, but here return False for safety
            return False

    @staticmethod
    def select_word_file() -> Optional[str]:
        """
        Show secure file dialog for Word document selection.

        Returns:
            Optional[str]: Path to selected file or None if cancelled
        """
        try:
            import tkinter as tk
            from tkinter import filedialog
        except ImportError:
            # tkinter not available (headless environment)
            return None

        root = tk.Tk()
        root.withdraw()  # Hide main window

        try:
            file_path = filedialog.askopenfilename(
                title="Chọn file Word",
                filetypes=[("Word Documents", "*.docx"), ("All files", "*.*")],
            )

            if file_path and FileHandler.validate_path(file_path):
                return file_path
            else:
                return None

        finally:
            root.destroy()

    @staticmethod
    def select_excel_output() -> Optional[str]:
        """
        Show secure file dialog for Excel output path selection.

        Returns:
            Optional[str]: Path for Excel output or None if cancelled
        """
        try:
            import tkinter as tk
            from tkinter import filedialog
        except ImportError:
            # tkinter not available (headless environment)
            return None

        root = tk.Tk()
        root.withdraw()

        try:
            file_path = filedialog.asksaveasfilename(
                title="Chọn vị trí lưu file Excel",
                defaultextension=".xlsx",
                filetypes=[("Excel files", "*.xlsx"), ("All files", "*.*")],
            )

            if file_path:
                # Ensure .xlsx extension
                if not file_path.lower().endswith(".xlsx"):
                    file_path += ".xlsx"
                return file_path
            else:
                return None

        finally:
            root.destroy()

    @staticmethod
    def open_file_safely(file_path: str) -> bool:
        """
        Open file safely without command injection risk.

        Args:
            file_path: Path to file to open

        Returns:
            bool: True if file was opened successfully
        """
        return FileHandler.open_file_securely(file_path)

    @staticmethod
    def open_file_securely(file_path: str) -> bool:
        """
        Open file with system default application safely.

        Args:
            file_path: Path to file to open

        Returns:
            bool: True if file was opened successfully
        """
        try:
            path = Path(file_path)

            # Validate path first using secure validation
            if not FileHandler.validate_path_secure(
                str(path), FileHandler.ALLOWED_EXTENSIONS
            ):
                return False

            import platform
            import subprocess

            system = platform.system()

            if system == "Windows":
                # Use explorer.exe which is safer than cmd start
                subprocess.run(
                    ["explorer.exe", str(path)],
                    check=True,
                    capture_output=True,
                    timeout=10,
                )
            elif system == "Darwin":  # macOS
                subprocess.run(
                    ["open", str(path)], check=True, capture_output=True, timeout=10
                )
            else:  # Linux
                subprocess.run(
                    ["xdg-open", str(path)], check=True, capture_output=True, timeout=10
                )

            return True

        except subprocess.TimeoutExpired:
            return False
        except subprocess.CalledProcessError:
            return False
        except Exception:
            return False


def _ask_tax_rate_mode() -> Optional[str]:
    """
    Ask user to choose tax rate mode: one for all files or individual per file.

    Returns:
        Optional[str]: "all" or "individual" or None if invalid
    """
    import os
    import sys

    is_interactive = hasattr(sys.stdin, "isatty") and sys.stdin.isatty()
    if not is_interactive or os.environ.get("CI") or os.environ.get("NON_INTERACTIVE"):
        return "all"  # Default to "all" in non-interactive mode

    max_attempts = 3
    for attempt in range(max_attempts):
        try:
            print("Tax rate option:")
            print("  1. One tax rate for all files")
            print("  2. Individual tax rate for each file")
            user_input = input("Choose option (1 or 2): ").strip().lower()

            if user_input in ["1", "one", "all"]:
                return "all"
            elif user_input in ["2", "two", "individual"]:
                return "individual"
            else:
                print(
                    f"ERROR: Please enter 1 or 2. {max_attempts - attempt - 1} attempts remaining."
                )
                continue
        except (KeyboardInterrupt, EOFError):
            return "all"  # Default to "all" on interrupt
        except Exception:
            return "all"  # Default to "all" on error

    return "all"  # Default to "all" if max attempts reached


def _get_tax_rate_value(filename: Optional[str] = None) -> Optional[float]:
    """
    Get tax rate value from user input with validation.

    Args:
        filename: Optional filename to include in the prompt for context

    Returns:
        Optional[float]: Tax rate as decimal (e.g., 0.25 for 25%) or None if invalid
    """
    import os
    import re
    import sys

    is_interactive = hasattr(sys.stdin, "isatty") and sys.stdin.isatty()
    if not is_interactive or os.environ.get("CI") or os.environ.get("NON_INTERACTIVE"):
        return 0.25  # Default 25% tax rate for Vietnam

    max_attempts = 3
    max_input_length = 10

    for attempt in range(max_attempts):
        try:
            prompt = "Enter company tax rate (%): "
            if filename:
                prompt = f"[{filename}] {prompt}"
            user_input = input(prompt).strip()

            if len(user_input) > max_input_length:
                print(
                    f"ERROR: Input too long. {max_attempts - attempt - 1} attempts remaining."
                )
                continue

            if not re.match(r"^[0-9]+([.,][0-9]+)?$", user_input):
                print(
                    f"ERROR: Please enter a valid number. {max_attempts - attempt - 1} attempts remaining."
                )
                continue

            normalized_input = user_input.replace(",", ".")

            if normalized_input.count(".") > 1:
                print(
                    f"ERROR: Invalid number format. {max_attempts - attempt - 1} attempts remaining."
                )
                continue

            tax_rate_percent = float(normalized_input)

            if not (0 <= tax_rate_percent <= 100):
                print(
                    f"ERROR: Tax rate must be 0% to 100%. {max_attempts - attempt - 1} attempts remaining."
                )
                continue

            return tax_rate_percent / 100

        except (ValueError, KeyboardInterrupt):
            print(
                f"ERROR: Invalid input. {max_attempts - attempt - 1} attempts remaining."
            )
            continue
        except (OSError, UnicodeError):
            return 0.25

    print("ERROR: Max attempts reached. Using default 25% tax rate.")
    return 0.25


def get_validated_tax_rate(
    filename: Optional[str] = None, context: Optional["AuditContext"] = None
) -> Optional[float]:
    """
    Get validated tax rate from user input with enhanced security.

    SCRUM-6 P0: Detects non-interactive mode (no tty/stdin) and returns
    default tax rate without triggering UnicodeEncodeError on Windows.

    Supports two modes:
    - "all": One tax rate for all files (asked once, cached)
    - "individual": Individual tax rate for each file (asked per file)

    Args:
        filename: Optional filename to include in the prompt for context
        context: Optional AuditContext containing TaxRateConfig

    Returns:
        Optional[float]: Tax rate as decimal (e.g., 0.25 for 25%) or None if invalid
    """
    import os
    import sys
    from pathlib import Path

    global _tax_rate_mode, _shared_tax_rate

    # Check for context-based configuration first (CLI v2)
    if context and context.tax_rate_config:
        config = context.tax_rate_config
        if config.mode == "all":
            return config.all_rate
        elif config.mode == "individual":
            # Resolve rate from map using filename
            # Since filename is not guaranteed to be a full path or even exist here,
            # we rely on what was passed. If it's just a name, we use it.
            # Ideally, CLI passes full path context if available, but validator usually has data only.
            # However, context.current_filename might be available?
            # The argument 'filename' comes from tax_validator line 118:
            # filename = self.context.current_filename
            # So let's use that.

            # Resolve rate from map using path context
            f_path = Path(filename) if filename else Path("unknown")
            base = context.base_path if context.base_path else Path(".")

            return config.resolve_rate(f_path, base)

    # SCRUM-6 P0: Detect non-interactive mode (batch processing)
    is_interactive = hasattr(sys.stdin, "isatty") and sys.stdin.isatty()

    if not is_interactive or os.environ.get("CI") or os.environ.get("NON_INTERACTIVE"):
        return 0.25  # Default 25% tax rate for Vietnam

    # Ask for mode selection on first call
    if _tax_rate_mode is None:
        _tax_rate_mode = _ask_tax_rate_mode()
        if _tax_rate_mode is None:
            _tax_rate_mode = "all"  # Default to "all" if selection failed

    # Handle "all" mode: use cached tax rate or ask once
    if _tax_rate_mode == "all":
        if _shared_tax_rate is not None:
            return _shared_tax_rate
        else:
            # Ask for tax rate once for all files
            _shared_tax_rate = _get_tax_rate_value(filename="ALL FILES")
            return _shared_tax_rate

    # Handle "individual" mode: ask for each file
    else:  # _tax_rate_mode == "individual"
        return _get_tax_rate_value(filename=filename)
