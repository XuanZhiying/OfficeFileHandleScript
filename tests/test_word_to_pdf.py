from __future__ import annotations

from pathlib import Path

import word_to_pdf


def test_build_output_path_uses_pdf_suffix(tmp_path: Path) -> None:
    input_file = tmp_path / "report.docx"
    expected_output = (tmp_path / "report.pdf").resolve()

    assert word_to_pdf.build_output_path(input_file, None) == expected_output


def test_validate_paths_rejects_existing_output_without_overwrite(
    tmp_path: Path,
) -> None:
    input_file = tmp_path / "report.docx"
    output_file = tmp_path / "report.pdf"
    input_file.write_text("fake-word-content", encoding="utf-8")
    output_file.write_text("existing-pdf", encoding="utf-8")

    try:
        word_to_pdf.validate_paths(input_file, output_file, overwrite=False)
    except FileExistsError as exc:
        assert "--overwrite" in str(exc)
    else:
        raise AssertionError("expected FileExistsError")


def test_main_calls_converter_with_default_output(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    input_file = tmp_path / "report.docx"
    input_file.write_text("fake-word-content", encoding="utf-8")
    captured_paths: dict[str, Path] = {}

    def fake_convert(input_path: Path, output_path: Path) -> list[str]:
        captured_paths["input"] = input_path
        captured_paths["output"] = output_path
        return []

    monkeypatch.setattr(word_to_pdf, "convert_word_to_pdf", fake_convert)

    exit_code = word_to_pdf.main([str(input_file)])

    assert exit_code == 0
    assert captured_paths["input"] == input_file.resolve()
    assert captured_paths["output"] == (tmp_path / "report.pdf").resolve()
    assert "转换成功" in capsys.readouterr().out


def test_main_returns_error_for_missing_input(tmp_path: Path, capsys) -> None:
    missing_file = tmp_path / "missing.docx"

    exit_code = word_to_pdf.main([str(missing_file)])

    assert exit_code == 1
    assert "输入文件不存在" in capsys.readouterr().err


def test_main_returns_success_with_cleanup_warning(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    input_file = tmp_path / "report.docx"
    input_file.write_text("fake-word-content", encoding="utf-8")

    def fake_convert(_: Path, __: Path) -> list[str]:
        return ["退出 Word 进程失败：mock warning"]

    monkeypatch.setattr(word_to_pdf, "convert_word_to_pdf", fake_convert)

    exit_code = word_to_pdf.main([str(input_file)])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "警告：退出 Word 进程失败：mock warning" in captured.err
    assert "转换成功" in captured.out


def test_convert_word_to_pdf_cleans_up_after_conversion_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    class FakeDocument:
        def __init__(self) -> None:
            self.close_args: list[bool] = []

        def ExportAsFixedFormat(self, **_: object) -> None:
            raise RuntimeError("export failed")

        def Close(self, save_changes: bool) -> None:
            self.close_args.append(save_changes)

    class FakeDocuments:
        def __init__(self, document: FakeDocument) -> None:
            self.document = document

        def Open(self, *_: object, **__: object) -> FakeDocument:
            return self.document

    class FakeWordApp:
        def __init__(self, document: FakeDocument) -> None:
            self.Visible = True
            self.DisplayAlerts = 1
            self.Documents = FakeDocuments(document)
            self.quit_called = False

        def Quit(self) -> None:
            self.quit_called = True

    class FakeClient:
        def __init__(self, word_app: FakeWordApp) -> None:
            self.word_app = word_app

        def DispatchEx(self, name: str) -> FakeWordApp:
            assert name == "Word.Application"
            return self.word_app

    document = FakeDocument()
    word_app = FakeWordApp(document)
    monkeypatch.setattr(word_to_pdf, "_load_word_client", lambda: FakeClient(word_app))

    input_file = tmp_path / "report.docx"
    output_file = tmp_path / "report.pdf"

    try:
        word_to_pdf.convert_word_to_pdf(input_file, output_file)
    except RuntimeError as exc:
        assert "Word 转 PDF 失败" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")

    assert document.close_args == [False]
    assert word_app.quit_called is True
