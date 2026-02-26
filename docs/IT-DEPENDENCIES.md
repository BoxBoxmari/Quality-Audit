# IT Dependencies Installation Guide - Quality Audit Tool

## Document Information

- **Tool Name**: Quality Audit - Financial Statement Validation Tool
- **Version**: 2.0.0
- **Date**: January 23, 2025
- **Prepared by**: Development Team
- **Approved by**: IT Security Team

## Executive Summary

This document outlines the Python dependencies required for the Quality Audit tool, a financial data validation system. All dependencies are standard, well-maintained Python packages from PyPI (Python Package Index) with no known security vulnerabilities.

## Required Dependencies Analysis

### 🔴 CRITICAL DEPENDENCIES (Required for Core Functionality)

#### 1. pandas >= 1.5.0
- **Purpose**: Data manipulation and analysis for financial statements
- **Risk Level**: LOW
- **Usage**: Processes Excel files, handles large datasets, performs data validation
- **Alternative**: None (core dependency)
- **Security Status**: ✅ No known vulnerabilities
- **License**: BSD-3-Clause

#### 2. openpyxl >= 3.0.0
- **Purpose**: Excel file reading and writing (.xlsx format)
- **Risk Level**: LOW
- **Usage**: Reads financial data from Excel files, writes validation reports
- **Alternative**: xlrd/xlwt (but openpyxl is more reliable for .xlsx)
- **Security Status**: ✅ No known vulnerabilities
- **License**: MIT

#### 3. python-docx >= 0.8.11
- **Purpose**: Word document processing (.docx format)
- **Risk Level**: LOW
- **Usage**: Extracts tables from Word documents containing financial statements
- **Alternative**: docx2python (but python-docx is more mature)
- **Security Status**: ✅ No known vulnerabilities
- **License**: MIT

#### 4. numpy >= 1.23.0
- **Purpose**: Numerical computing and array operations
- **Risk Level**: LOW
- **Usage**: Supports pandas operations, financial calculations
- **Alternative**: None (required by pandas)
- **Security Status**: ✅ No known vulnerabilities
- **License**: BSD-3-Clause

#### 5. tkinter >= 8.6
- **Purpose**: GUI components for file selection dialogs
- **Risk Level**: LOW
- **Usage**: Provides file browser interface (built-in Python module)
- **Alternative**: PyQt/PySide (but tkinter is standard)
- **Security Status**: ✅ Part of Python standard library
- **License**: PSF (Python Software Foundation)

## 🟡 OPTIONAL DEPENDENCIES (Render-first table extraction)

Khi bật đường DOCX → PDF → ảnh → OCR để trích bảng phức tạp, cần thêm các Python package sau. Thiếu thì tool tự fallback sang luồng legacy (OOXML/python-docx), không crash.

- **Pillow**: xử lý ảnh
- **opencv-python**: xử lý ảnh / layout
- **pytesseract**: wrapper Python cho Tesseract OCR
- **PyMuPDF** (fitz): render PDF
- **pdf2image**: PDF → ảnh (phụ thuộc binary Poppler)

Cài: `pip install -r requirements.txt` (file chính chứa cả optional render-first).

## 🟠 SYSTEM-LEVEL BINARIES (for render-first only)

**Binary hệ thống** là chương trình cài trên OS, **không** cài bằng `pip`. Khi đem tool sang máy khác phải cài lại trên từng máy/theo từng OS; `pip install -r requirements.txt` không cài giúp các binary này.

| Binary | Mục đích | Cài đặt (ví dụ) |
|--------|----------|-----------------|
| **Poppler** | PDF tools (có `pdftoppm` cho PDF→ảnh) | Ubuntu: `apt install poppler-utils`; Windows: `choco install poppler`; macOS: `brew install poppler` |
| **Tesseract** | OCR (nhận dạng chữ trên ảnh) | Ubuntu: `apt install tesseract-ocr`; Windows/macOS: tải installer từ dự án Tesseract |
| **LibreOffice** | Headless `soffice` chuyển DOCX→PDF | Cài bản desktop hoặc headless theo OS |
| **Microsoft Word (Windows-only, tùy chọn)** | DOCX→PDF qua COM automation (WordComConverter) | Cài Microsoft Word trên Windows; dùng PowerShell (`powershell.exe`) để điều khiển `Word.Application` nếu không có LibreOffice |

Hai chế độ chạy:

- **Chạy tối thiểu (main flow)**: Chỉ cần core Python (pandas, numpy, openpyxl, python-docx, lxml). Luồng: OOXML/python-docx → validate → Excel.
- **Chạy đủ render-first**: Cần thêm optional Python libs (Pillow, opencv-python, pytesseract, PyMuPDF, pdf2image) **và** cài Poppler, Tesseract, LibreOffice trên từng môi trường.

## 🟡 OPTIONAL DEPENDENCIES (Development/Testing Only)

#### Development Tools
```python
pytest>=7.0.0          # Testing framework
black>=22.0.0          # Code formatter
flake8>=4.0.0          # Linting tool
mypy>=0.950           # Type checker
```

## Installation Instructions

### For Production Environment

#### Option 1: Using requirements.txt (Recommended)
```bash
# Create virtual environment
python -m venv quality_audit_env
source quality_audit_env/bin/activate  # On Windows: quality_audit_env\Scripts\activate

# Install core dependencies only
pip install pandas>=1.5.0 openpyxl>=3.0.0 python-docx>=0.8.11 numpy>=1.23.0
```

#### Option 2: Using requirements.txt file
```bash
# Install all dependencies (including optional)
pip install -r requirements.txt
```

### For Development Environment

```bash
# Install all dependencies
pip install -r requirements.txt

# Optional: Install additional development tools
pip install ruff>=0.1.0 autopep8>=2.0.0 isort>=5.12.0
```

## Security Assessment

### Vulnerability Scan Results
- ✅ **pandas**: No known CVEs
- ✅ **openpyxl**: No known CVEs
- ✅ **python-docx**: No known CVEs
- ✅ **numpy**: No known CVEs
- ✅ **tkinter**: Part of Python stdlib (secure)

### Network Dependencies
- **pypi.org**: Required for initial installation only
- **No runtime external connections** required
- **All dependencies are offline-capable** after installation

## Compatibility Requirements

### Python Version
- **Supported**: Python 3.8, 3.9, 3.10, 3.11, 3.12
- **Recommended**: Python 3.10+ for optimal performance
- **Minimum**: Python 3.8 (as per pandas requirement)

### Operating System
- ✅ **Windows**: 10/11 (64-bit)
- ✅ **macOS**: 10.15+ (Intel/Apple Silicon)
- ✅ **Linux**: Ubuntu 18.04+, CentOS 7+, RHEL 8+

### Hardware Requirements
- **RAM**: Minimum 4GB, Recommended 8GB+
- **Storage**: 500MB free space
- **CPU**: Any modern processor (no specific requirements)

## Installation Verification

After installation, run this verification script:

```python
# verification.py
import sys

def check_dependencies():
    """Verify all critical dependencies are installed."""
    dependencies = [
        ('pandas', 'Data processing'),
        ('openpyxl', 'Excel file handling'),
        ('docx', 'Word document processing'),
        ('numpy', 'Numerical computing'),
    ]

    print("🔍 Checking Quality Audit Tool Dependencies...\n")

    all_good = True
    for module, purpose in dependencies:
        try:
            __import__(module)
            print(f"✅ {module} - {purpose}")
        except ImportError:
            print(f"❌ {module} - {purpose} - MISSING")
            all_good = False

    # Check tkinter (GUI)
    try:
        import tkinter
        print("✅ tkinter - GUI components")
    except ImportError:
        print("⚠️  tkinter - GUI components - Not available (may affect file dialogs)")

    print(f"\n{'🎉 All dependencies installed successfully!' if all_good else '⚠️  Some dependencies missing - please install'}")
    return all_good

if __name__ == "__main__":
    success = check_dependencies()
    sys.exit(0 if success else 1)
```

Run with: `python verification.py`

## Troubleshooting

### Common Installation Issues

#### 1. Permission Denied (Windows)
```bash
# Run PowerShell as Administrator, or use:
pip install --user package_name
```

#### 2. SSL Certificate Issues
```bash
# Use trusted certificates
pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org package_name
```

#### 3. Proxy Issues
```bash
# Set proxy environment variables
export HTTP_PROXY=http://proxy.company.com:8080
export HTTPS_PROXY=http://proxy.company.com:8080
pip install package_name
```

#### 4. tkinker Not Available (Linux)
```bash
# Ubuntu/Debian
sudo apt-get install python3-tk

# CentOS/RHEL
sudo yum install tkinter
```

## Approval Checklist

### IT Security Team Approval Required:
- [ ] Review dependency licenses (all BSD/MIT/PSF)
- [ ] Confirm no known CVEs in dependency chain
- [ ] Verify no network dependencies in runtime
- [ ] Check compatibility with company security policies
- [ ] Confirm installation in approved environments only

### System Administrator Checklist:
- [ ] Python 3.8+ installed on target systems
- [ ] Virtual environment permissions granted
- [ ] Network access to PyPI for initial installation
- [ ] Disk space requirements met (500MB+)
- [ ] RAM requirements verified (4GB+)

## Change Log

| Version | Date | Changes |
|---------|------|---------|
| 1.0.0 | 2024-01-01 | Initial documentation |
| 2.0.0 | 2025-01-23 | Updated for new architecture, added security assessment |

## Contact Information

- **Development Team**: development@company.com
- **IT Security**: security@company.com
- **System Administration**: sysadmin@company.com

---

**Approval Status**: ⏳ Pending IT Review

**Document ID**: IT-DEP-QA-2025-001

## System-Level Dependencies

### tkinter (GUI Support)
- **Purpose**: GUI framework for file dialogs and user interface
- **Installation**:
  - **Ubuntu/Debian**: `sudo apt-get install python3-tk`
  - **Fedora/RHEL**: `sudo dnf install python3-tkinter`
  - **macOS**: Included with official Python installer from python.org
  - **Windows**: Included with standard Python installation
- **Note**: tkinter is not pip-installable and must be installed at the system level