from pathlib import Path

import pytest


def make_dummy_converters(word_available: bool, soffice_available: bool):
    class DummyWordCom:
        def __init__(self):
            self._available = word_available
            self.called = False

        def is_available(self) -> bool:
            return self._available

        def convert_docx_to_pdf(self, docx_path: Path, output_pdf_path: Path):
            self.called = True
            # Succeed only when marked available
            if self._available:
                return True, ""
            return False, "word failure"

    class DummyLocalSoffice:
        def __init__(self):
            self._available = soffice_available
            self.called = False

        def is_available(self) -> bool:
            return self._available

        def convert_docx_to_pdf(self, docx_path: Path, output_pdf_path: Path):
            self.called = True
            if self._available:
                return True, ""
            return False, "soffice failure"

    return DummyWordCom, DummyLocalSoffice


@pytest.mark.parametrize(
    "word_available, soffice_available, expected_mode",
    [
        (True, True, "word_com"),
        (True, False, "word_com"),
        (False, True, "local"),
        (False, False, "unavailable"),
    ],
)
def test_fallback_converter_mode_selection(
    monkeypatch, word_available, soffice_available, expected_mode
):
    """
    FallbackConverter should prefer WordComConverter when available, otherwise soffice,
    and report 'unavailable' when no backend is available.
    """
    from quality_audit.io.extractors.conversion import converter
    from quality_audit.io.extractors.conversion import FallbackConverter

    DummyWordCom, DummyLocalSoffice = make_dummy_converters(
        word_available, soffice_available
    )

    # Patch the converter classes used inside FallbackConverter
    monkeypatch.setattr(converter, "WordComConverter", DummyWordCom)
    monkeypatch.setattr(converter, "LocalSofficeConverter", DummyLocalSoffice)

    conv = FallbackConverter()

    assert conv.get_available_mode() == expected_mode

    success, mode, error = conv.convert(Path("in.docx"), Path("out.pdf"))

    word = conv._word_com_converter
    local = conv._local_converter

    if expected_mode == "unavailable":
        assert success is False
        assert mode == "unavailable"
        assert "no converter available" in error
        assert word.called is False
        assert local.called is False
    elif expected_mode == "word_com":
        assert success is True
        assert mode == "word_com"
        assert word.called is True
        # When Word COM succeeds, soffice must not be called.
        assert local.called is False
    else:
        # expected_mode == "local"
        assert success is True
        assert mode == "local"
        assert local.called is True
        assert word.called is False


def test_fallback_converter_falls_back_to_soffice_when_word_fails(monkeypatch):
    """When Word COM fails, FallbackConverter should still try local soffice."""
    from quality_audit.io.extractors.conversion import converter
    from quality_audit.io.extractors.conversion import FallbackConverter

    class FailingWordCom:
        def __init__(self):
            self.called = False

        def is_available(self) -> bool:
            return True

        def convert_docx_to_pdf(self, docx_path: Path, output_pdf_path: Path):
            self.called = True
            return False, "word failure"

    class SuccessfulLocalSoffice:
        def __init__(self):
            self.called = False

        def is_available(self) -> bool:
            return True

        def convert_docx_to_pdf(self, docx_path: Path, output_pdf_path: Path):
            self.called = True
            return True, ""

    monkeypatch.setattr(converter, "WordComConverter", FailingWordCom)
    monkeypatch.setattr(converter, "LocalSofficeConverter", SuccessfulLocalSoffice)

    conv = FallbackConverter()

    success, mode, error = conv.convert(Path("in.docx"), Path("out.pdf"))

    assert success is True
    assert mode == "local"
    assert error == ""
    assert conv._word_com_converter.called is True
    assert conv._local_converter.called is True


@pytest.mark.parametrize(
    "os_name, which_result, expected_available",
    [
        ("nt", "C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe", True),
        ("nt", None, False),
        ("posix", "/usr/bin/powershell", False),
    ],
)
def test_word_com_is_available_depends_on_windows_and_powershell(
    monkeypatch, os_name, which_result, expected_available
):
    """WordComConverter.is_available should depend on OS type and PowerShell presence."""
    from quality_audit.io.extractors.conversion import WordComConverter
    from quality_audit.io.extractors.conversion import converter

    # Patch OS name and shutil.which inside the converter module
    monkeypatch.setattr(converter.os, "name", os_name, raising=False)

    def fake_which(name: str):
        return which_result

    monkeypatch.setattr(converter.shutil, "which", fake_which, raising=False)

    conv = WordComConverter()

    # First call populates the cached value
    assert conv.is_available() is expected_available
    # Second call should use cached value and return the same result
    assert conv.is_available() is expected_available