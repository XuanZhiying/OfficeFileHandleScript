from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import scan_pdf_to_word

if TYPE_CHECKING:
    from _pytest.capture import CaptureFixture
    from _pytest.monkeypatch import MonkeyPatch


class FakeOcrProvider:
    def __init__(self, result: object) -> None:
        self.result: object = result
        self.predict_calls: list[str] = []

    def predict(self, input_path: str) -> object:
        self.predict_calls.append(input_path)
        return self.result


class FakeDocument:
    instances: list[FakeDocument] = []

    def __init__(self) -> None:
        self.headings: list[tuple[str, int]] = []
        self.paragraphs: list[str] = []
        self.saved_path: str | None = None
        self.__class__.instances.append(self)

    def add_heading(self, text: str, level: int = 1) -> object:
        self.headings.append((text, level))
        return object()

    def add_paragraph(self, text: str = "") -> object:
        self.paragraphs.append(text)
        return object()

    def save(self, path: str) -> None:
        self.saved_path = path


def fake_document_factory() -> FakeDocument:
    return FakeDocument()


def test_build_output_path_uses_docx_suffix(tmp_path: Path) -> None:
    input_file = tmp_path / "scan.pdf"
    expected_output = (tmp_path / "scan.docx").resolve()

    assert scan_pdf_to_word.build_output_path(input_file, None) == expected_output


def test_validate_paths_rejects_unsupported_input_suffix(tmp_path: Path) -> None:
    input_file = tmp_path / "scan.txt"
    output_file = tmp_path / "scan.docx"
    _ = input_file.write_text("not-supported", encoding="utf-8")

    try:
        scan_pdf_to_word.validate_paths(input_file, output_file, overwrite=True)
    except ValueError as exc:
        assert ".pdf" in str(exc)
        assert ".tiff" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_validate_paths_rejects_existing_output_without_overwrite(
    tmp_path: Path,
) -> None:
    input_file = tmp_path / "scan.png"
    output_file = tmp_path / "scan.docx"
    _ = input_file.write_text("fake-image-content", encoding="utf-8")
    _ = output_file.write_text("existing-docx", encoding="utf-8")

    try:
        scan_pdf_to_word.validate_paths(input_file, output_file, overwrite=False)
    except FileExistsError as exc:
        assert "--overwrite" in str(exc)
    else:
        raise AssertionError("expected FileExistsError")


def test_extract_text_pages_handles_rec_texts_and_nested_text_fields() -> None:
    result = [
        {"rec_texts": ["第一页第一行", "第一页第二行"]},
        {
            "page": {
                "blocks": [
                    {"text": "第二页第一行"},
                    {"items": [{"transcription": "第二页第二行"}]},
                ]
            }
        },
    ]

    assert scan_pdf_to_word.extract_text_pages(result) == [
        ["第一页第一行", "第一页第二行"],
        ["第二页第一行", "第二页第二行"],
    ]


def test_extract_text_pages_preserves_repeated_lines() -> None:
    result = [{"rec_texts": ["合计", "合计"]}]

    assert scan_pdf_to_word.extract_text_pages(result) == [["合计", "合计"]]


def test_extract_text_pages_handles_paddle_tuple_like_results() -> None:
    result = [[[[0, 0], [1, 1]], ("识别文本", 0.99)]]

    assert scan_pdf_to_word.extract_text_pages(result) == [["识别文本"]]


def test_extract_text_pages_handles_json_property_result() -> None:
    class JsonPropertyResult:
        @property
        def json(self) -> dict[str, list[str]]:
            return {"rec_texts": ["属性文本"]}

    assert scan_pdf_to_word.extract_text_pages([JsonPropertyResult()]) == [["属性文本"]]


def test_extract_text_pages_returns_empty_for_unknown_shape() -> None:
    assert scan_pdf_to_word.extract_text_pages({"boxes": [[[0, 0], [1, 1]]]}) == []


def test_convert_scan_to_word_writes_ocr_lines_with_fakes(tmp_path: Path) -> None:
    FakeDocument.instances.clear()
    input_file = tmp_path / "scan.pdf"
    output_file = tmp_path / "scan.docx"
    _ = input_file.write_text("fake-pdf-content", encoding="utf-8")
    provider = FakeOcrProvider([{"rec_texts": ["第一行", "Second line"]}])

    warnings = scan_pdf_to_word.convert_scan_to_word(
        input_file,
        output_file,
        ocr_provider=provider,
        document_factory=fake_document_factory,
    )

    assert warnings == []
    assert provider.predict_calls == [str(input_file.resolve())]
    assert len(FakeDocument.instances) == 1
    document = FakeDocument.instances[0]
    assert document.headings == [("OCR 识别结果", 1)]
    assert document.paragraphs == ["第一行", "Second line"]
    assert document.saved_path == str(output_file.resolve())


def test_convert_scan_to_word_writes_note_for_empty_ocr_result(tmp_path: Path) -> None:
    FakeDocument.instances.clear()
    input_file = tmp_path / "scan.jpg"
    output_file = tmp_path / "scan.docx"
    _ = input_file.write_text("fake-image-content", encoding="utf-8")
    provider = FakeOcrProvider([])

    _ = scan_pdf_to_word.convert_scan_to_word(
        input_file,
        output_file,
        ocr_provider=provider,
        document_factory=fake_document_factory,
    )

    assert FakeDocument.instances[0].paragraphs == [scan_pdf_to_word.EMPTY_OCR_NOTE]


def test_main_calls_converter_with_default_output_and_lang(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    input_file = tmp_path / "scan.tiff"
    _ = input_file.write_text("fake-image-content", encoding="utf-8")
    captured: dict[str, object] = {}

    def fake_convert(
        input_path: Path,
        output_path: Path,
        lang: str = "ch",
        device: str = "cpu",
        enable_mkldnn: bool = False,
    ) -> list[str]:
        captured["input"] = input_path
        captured["output"] = output_path
        captured["lang"] = lang
        captured["device"] = device
        captured["enable_mkldnn"] = enable_mkldnn
        return []

    monkeypatch.setattr(scan_pdf_to_word, "convert_scan_to_word", fake_convert)

    exit_code = scan_pdf_to_word.main([str(input_file), "--lang", "en"])

    assert exit_code == 0
    assert captured["input"] == input_file.resolve()
    assert captured["output"] == (tmp_path / "scan.docx").resolve()
    assert captured["lang"] == "en"
    assert captured["device"] == "cpu"
    assert captured["enable_mkldnn"] is False
    assert "转换成功" in capsys.readouterr().out


def test_main_passes_device_and_mkldnn_option(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    input_file = tmp_path / "scan.png"
    _ = input_file.write_text("fake-image-content", encoding="utf-8")
    captured: dict[str, object] = {}

    def fake_convert(
        input_path: Path,
        output_path: Path,
        lang: str = "ch",
        device: str = "cpu",
        enable_mkldnn: bool = False,
    ) -> list[str]:
        captured["device"] = device
        captured["enable_mkldnn"] = enable_mkldnn
        return []

    monkeypatch.setattr(scan_pdf_to_word, "convert_scan_to_word", fake_convert)

    exit_code = scan_pdf_to_word.main(
        [str(input_file), "--device", "gpu", "--enable-mkldnn"]
    )

    assert exit_code == 0
    assert captured == {"device": "gpu", "enable_mkldnn": True}


def test_main_returns_error_for_missing_input(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    missing_file = tmp_path / "missing.pdf"

    exit_code = scan_pdf_to_word.main([str(missing_file)])

    assert exit_code == 1
    assert "输入文件不存在" in capsys.readouterr().err


def test_convert_scan_to_word_reports_ocr_root_cause(tmp_path: Path) -> None:
    input_file = tmp_path / "scan.pdf"
    output_file = tmp_path / "scan.docx"
    _ = input_file.write_text("fake-pdf-content", encoding="utf-8")

    class FailingProvider:
        def predict(self, input_path: str) -> object:
            raise NotImplementedError("oneDNN failed")

    try:
        _ = scan_pdf_to_word.convert_scan_to_word(
            input_file,
            output_file,
            ocr_provider=FailingProvider(),
            document_factory=fake_document_factory,
        )
    except RuntimeError as exc:
        assert "扫描件 OCR 识别失败" in str(exc)
        assert "NotImplementedError: oneDNN failed" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


def test_main_returns_error_when_conversion_fails_cleanly(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    input_file = tmp_path / "scan.bmp"
    _ = input_file.write_text("fake-image-content", encoding="utf-8")

    def fake_convert(
        _: Path,
        _output_path: Path,
        lang: str = "ch",
        device: str = "cpu",
        enable_mkldnn: bool = False,
    ) -> list[str]:
        raise RuntimeError(f"模拟 OCR 失败：{lang}")

    monkeypatch.setattr(scan_pdf_to_word, "convert_scan_to_word", fake_convert)

    exit_code = scan_pdf_to_word.main([str(input_file)])

    assert exit_code == 1
    assert "错误：模拟 OCR 失败：ch" in capsys.readouterr().err
