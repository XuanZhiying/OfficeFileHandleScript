from __future__ import annotations

from typing import TYPE_CHECKING
from pathlib import Path

import pdf_to_word

if TYPE_CHECKING:
    from _pytest.capture import CaptureFixture
    from _pytest.monkeypatch import MonkeyPatch


def test_build_output_path_uses_docx_suffix(tmp_path: Path) -> None:
    input_file = tmp_path / "report.pdf"
    expected_output = (tmp_path / "report.docx").resolve()

    assert pdf_to_word.build_output_path(input_file, None) == expected_output


def test_validate_paths_rejects_existing_output_without_overwrite(
    tmp_path: Path,
) -> None:
    input_file = tmp_path / "report.pdf"
    output_file = tmp_path / "report.docx"
    _ = input_file.write_text("fake-pdf-content", encoding="utf-8")
    _ = output_file.write_text("existing-docx", encoding="utf-8")

    try:
        pdf_to_word.validate_paths(input_file, output_file, overwrite=False)
    except FileExistsError as exc:
        assert "--overwrite" in str(exc)
    else:
        raise AssertionError("expected FileExistsError")


def test_validate_paths_rejects_output_directory(tmp_path: Path) -> None:
    input_file = tmp_path / "report.pdf"
    output_dir = tmp_path / "target.docx"
    _ = input_file.write_text("fake-pdf-content", encoding="utf-8")
    output_dir.mkdir()

    try:
        pdf_to_word.validate_paths(input_file, output_dir, overwrite=True)
    except IsADirectoryError as exc:
        assert "输出路径是目录" in str(exc)
    else:
        raise AssertionError("expected IsADirectoryError")


def test_main_calls_converter_with_default_output(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    input_file = tmp_path / "report.pdf"
    _ = input_file.write_text("fake-pdf-content", encoding="utf-8")
    captured_paths: dict[str, Path] = {}

    def fake_convert(input_path: Path, output_path: Path) -> list[str]:
        captured_paths["input"] = input_path
        captured_paths["output"] = output_path
        return []

    monkeypatch.setattr(pdf_to_word, "convert_pdf_to_word", fake_convert)

    exit_code = pdf_to_word.main([str(input_file)])

    assert exit_code == 0
    assert captured_paths["input"] == input_file.resolve()
    assert captured_paths["output"] == (tmp_path / "report.docx").resolve()
    assert "转换成功" in capsys.readouterr().out


def test_main_returns_error_for_missing_input(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    missing_file = tmp_path / "missing.pdf"

    exit_code = pdf_to_word.main([str(missing_file)])

    assert exit_code == 1
    assert "输入文件不存在" in capsys.readouterr().err


def test_main_returns_error_when_converter_api_is_unavailable(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    input_file = tmp_path / "report.pdf"
    _ = input_file.write_text("fake-pdf-content", encoding="utf-8")

    def fake_load_converter_class() -> object:
        raise RuntimeError("当前环境中的 pdf2docx 缺少可用的 Converter 接口")

    monkeypatch.setattr(pdf_to_word, "_load_converter_class", fake_load_converter_class)

    exit_code = pdf_to_word.main([str(input_file)])

    assert exit_code == 1
    assert "pdf2docx 缺少可用的 Converter 接口" in capsys.readouterr().err


def test_main_returns_success_with_cleanup_warning(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    input_file = tmp_path / "report.pdf"
    _ = input_file.write_text("fake-pdf-content", encoding="utf-8")

    def fake_convert(_: Path, _output_path: Path) -> list[str]:
        return ["关闭 PDF 转换器失败：mock warning"]

    monkeypatch.setattr(pdf_to_word, "convert_pdf_to_word", fake_convert)

    exit_code = pdf_to_word.main([str(input_file)])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "警告：关闭 PDF 转换器失败：mock warning" in captured.err
    assert "转换成功" in captured.out


def test_convert_pdf_to_word_cleans_up_after_conversion_failure(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    class FakeConverter:
        def __init__(self, source: str) -> None:
            self.source: str = source
            self.convert_calls: list[str] = []
            self.close_called: bool = False

        def convert(self, target: str) -> None:
            self.convert_calls.append(target)
            raise RuntimeError("convert failed")

        def close(self) -> None:
            self.close_called = True

    created_converters: list[FakeConverter] = []

    def fake_load_converter_class() -> type[FakeConverter]:
        class FakeConverterFactory(FakeConverter):
            def __init__(self, source: str) -> None:
                super().__init__(source)
                created_converters.append(self)

        return FakeConverterFactory

    monkeypatch.setattr(pdf_to_word, "_load_converter_class", fake_load_converter_class)

    input_file = tmp_path / "report.pdf"
    output_file = tmp_path / "report.docx"

    try:
        _ = pdf_to_word.convert_pdf_to_word(input_file, output_file)
    except RuntimeError as exc:
        assert "PDF 转 Word 失败" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")

    assert len(created_converters) == 1
    assert created_converters[0].source == str(input_file.resolve())
    assert created_converters[0].convert_calls == [str(output_file.resolve())]
    assert created_converters[0].close_called is True
