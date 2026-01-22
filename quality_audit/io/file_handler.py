"""
Secure file handling operations with path validation and safe file opening.
"""

import tkinter as tk
from pathlib import Path
from tkinter import filedialog
from typing import Optional, Set


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
        file_path: str, allowed_extensions: Optional[Set[str]] = None
    ) -> bool:
        """
        Secure path validation with strict directory traversal prevention.

        Args:
            file_path: Path to validate
            allowed_extensions: Set of allowed file extensions (defaults to ALLOWED_EXTENSIONS)

        Returns:
            bool: True if path is valid and safe
        """
        try:
            allowed_extensions = allowed_extensions or FileHandler.ALLOWED_EXTENSIONS
            resolved_path = Path(file_path).resolve()
            str_path = str(resolved_path)

            # Strict path traversal prevention - check path parts
            path_parts = resolved_path.parts
            if ".." in path_parts or any(".." in part for part in path_parts):
                return False

            # Check if path is within allowed base directory (current working directory)
            base_path = Path.cwd()
            try:
                # Try to get relative path - will raise ValueError if outside base
                resolved_path.relative_to(base_path)
            except ValueError:
                # Path is outside base directory - reject for security
                # Only allow if it's a user-selected file (handled by file dialogs)
                return False

            # Extension check
            if resolved_path.suffix.lower() not in allowed_extensions:
                return False

            # File existence and type check
            if not resolved_path.exists() or not resolved_path.is_file():
                return False

            # File size check
            max_size = FileHandler.MAX_FILE_SIZE_MB * 1024 * 1024  # Convert MB to bytes
            if resolved_path.stat().st_size > max_size:
                return False

            return True

        except (OSError, ValueError):
            return False

    @staticmethod
    def select_word_file() -> Optional[str]:
        """
        Show secure file dialog for Word document selection.

        Returns:
            Optional[str]: Path to selected file or None if cancelled
        """
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


def get_validated_tax_rate() -> Optional[float]:
    """
    Get validated tax rate from user input with enhanced security.

    Returns:
        Optional[float]: Tax rate as decimal (e.g., 0.25 for 25%) or None if invalid
    """
    import re

    max_attempts = 3
    max_input_length = 10  # Prevent extremely long inputs

    for attempt in range(max_attempts):
        try:
            user_input = input("Vui lòng nhập thuế suất công ty (%): ").strip()

            # Input length validation
            if len(user_input) > max_input_length:
                print(
                    f"ERROR: Đầu vào quá dài. Còn {max_attempts - attempt - 1} lần thử."
                )
                continue

            # Enhanced input sanitization with regex
            # Allow only digits, single decimal point, and single comma
            if not re.match(r"^[0-9]+([.,][0-9]+)?$", user_input):
                print(
                    f"ERROR: Vui lòng nhập số hợp lệ. Còn {
                        max_attempts - attempt - 1} lần thử."
                )
                continue

            # Normalize decimal separator
            normalized_input = user_input.replace(",", ".")

            # Prevent multiple decimal points
            if normalized_input.count(".") > 1:
                print(
                    f"ERROR: Định dạng số không hợp lệ. Còn {
                        max_attempts - attempt - 1} lần thử."
                )
                continue

            tax_rate_percent = float(normalized_input)

            # Validate range
            if not (0 <= tax_rate_percent <= 100):
                print(
                    f"ERROR: Thuế suất phải từ 0% đến 100%. Còn {
                        max_attempts - attempt - 1} lần thử."
                )
                continue

            return tax_rate_percent / 100

        except (ValueError, KeyboardInterrupt):
            print(
                f"ERROR: Đầu vào không hợp lệ. Còn {
                    max_attempts - attempt - 1} lần thử."
            )
            continue
        except Exception:
            print(
                f"ERROR: Lỗi không xác định. Còn {max_attempts - attempt - 1} lần thử."
            )
            continue

    print("ERROR: Đã hết số lần thử. Sử dụng thuế suất mặc định 25%.")
    return 0.25  # Default tax rate
