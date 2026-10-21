from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Mapping, Sequence
from importlib import import_module
from importlib.util import find_spec
from pathlib import Path
from typing import Protocol, cast


SUPPORTED_INPUT_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}
EMPTY_OCR_NOTE = "未识别到可编辑文字，请确认图片或扫描件清晰，并检查 OCR 语言模型设置。"


class ArgsNamespace(argparse.Namespace):
    input: str
    output: str | None
    overwrite: bool
    lang: str
    device: str
    enable_mkldnn: bool

    def __init__(self) -> None:
        super().__init__()
        self.input = ""
        self.output = None
        self.overwrite = False
        self.lang = "ch"
        self.device = "cpu"
        self.enable_mkldnn = False


class OcrProvider(Protocol):
    def predict(self, input_path: str) -> object: ...


class PaddleOcrInstance(Protocol):
    def predict(self, input_path: str) -> object: ...


type PaddleOcrFactory = Callable[..., PaddleOcrInstance]


class DocxDocument(Protocol):
    def add_heading(self, text: str, level: int = 1) -> object: ...

    def add_paragraph(self, text: str = "") -> object: ...

    def save(self, path: str) -> None: ...


type DocumentFactory = Callable[[], DocxDocument]


class PaddleOcrProvider:
    def __init__(self, lang: str, device: str = "cpu", enable_mkldnn: bool = False) -> None:
        self.lang: str = lang
        self.device: str = device
        self.enable_mkldnn: bool = enable_mkldnn
        self._ocr: PaddleOcrInstance | None = None

    def predict(self, input_path: str) -> object:
        if self._ocr is None:
            self._ocr = self._create_ocr()
        ocr = self._ocr
        return ocr.predict(input_path)

    def _create_ocr(self) -> PaddleOcrInstance:
        if find_spec("paddlepaddle") is None and find_spec("paddle") is None:
            raise RuntimeError(
                "当前环境缺少 PaddlePaddle 推理引擎。请按 README 安装 OCR 可选依赖和 PaddlePaddle。"
            )

        try:
            module = import_module("paddleocr")
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "当前环境缺少 paddleocr。请先按 README 安装 OCR 可选依赖。"
            ) from exc

        paddle_ocr = getattr(module, "PaddleOCR", None)
        if not callable(paddle_ocr):
            raise RuntimeError(
                "当前环境中的 paddleocr 缺少可用的 PaddleOCR 接口，请尝试重新安装依赖。"
            )

        factory = cast(PaddleOcrFactory, paddle_ocr)
        return factory(
            lang=self.lang,
            device=self.device,
            enable_mkldnn=self.enable_mkldnn,
        )


def parse_args(argv: Sequence[str] | None = None) -> ArgsNamespace:
    parser = argparse.ArgumentParser(
        description="把扫描版 PDF 或图片 OCR 识别为可编辑文字 DOCX。",
    )
    _ = parser.add_argument(
        "input",
        help="输入的扫描版 PDF 或图片路径，支持 .pdf/.png/.jpg/.jpeg/.bmp/.tif/.tiff",
    )
    _ = parser.add_argument(
        "output",
        nargs="?",
        help="输出 DOCX 路径。若不传，则默认写到与输入文件同目录、同名 .docx 文件。",
    )
    _ = parser.add_argument(
        "--overwrite",
        action="store_true",
        help="允许覆盖已存在的 DOCX 文件。",
    )
    _ = parser.add_argument(
        "--lang",
        default="ch",
        help="PaddleOCR 语言模型，默认 ch。中英文混排通常可用中文模型，但请按实际识别效果调整。",
    )
    _ = parser.add_argument(
        "--device",
        default="cpu",
        help="PaddleOCR 推理设备，默认 cpu。如已正确配置 GPU，可传 gpu。",
    )
    _ = parser.add_argument(
        "--enable-mkldnn",
        action="store_true",
        dest="enable_mkldnn",
        help="启用 CPU MKLDNN/oneDNN 加速。默认关闭，以避开部分 Windows CPU PaddlePaddle 版本的 oneDNN 兼容问题。",
    )
    return parser.parse_args(argv, namespace=ArgsNamespace())


def build_output_path(input_path: Path, output_path: Path | None) -> Path:
    if output_path is None:
        return input_path.with_suffix(".docx").resolve()
    return output_path.resolve()


def validate_paths(input_path: Path, output_path: Path, overwrite: bool) -> None:
    if not input_path.exists():
        raise FileNotFoundError(f"输入文件不存在：{input_path}")
    if input_path.is_dir():
        raise IsADirectoryError(f"输入路径是目录，不是文件：{input_path}")
    if input_path.suffix.lower() not in SUPPORTED_INPUT_SUFFIXES:
        raise ValueError("输入文件必须是 .pdf、.png、.jpg、.jpeg、.bmp、.tif 或 .tiff")
    if output_path.suffix.lower() != ".docx":
        raise ValueError("输出文件必须使用 .docx 扩展名")
    if not output_path.parent.exists():
        raise FileNotFoundError(f"输出目录不存在：{output_path.parent}")
    if output_path.exists() and output_path.is_dir():
        raise IsADirectoryError(f"输出路径是目录，不是文件：{output_path}")
    if output_path.exists() and not overwrite:
        raise FileExistsError(
            f"输出文件已存在：{output_path}。如需覆盖，请传入 --overwrite"
        )


def _load_document_factory() -> DocumentFactory:
    try:
        module = import_module("docx")
    except ModuleNotFoundError as exc:
        raise RuntimeError("当前环境缺少 python-docx。请先执行 `uv sync --dev` 安装依赖。") from exc

    document = getattr(module, "Document", None)
    if not callable(document):
        raise RuntimeError(
            "当前环境中的 python-docx 缺少可用的 Document 接口，请尝试重新安装依赖。"
        )

    return cast(DocumentFactory, document)


def extract_text_pages(ocr_result: object) -> list[list[str]]:
    if isinstance(ocr_result, Sequence) and not isinstance(ocr_result, str | bytes | bytearray):
        pages = [_extract_lines_from_node(item) for item in ocr_result]
        return [page for page in pages if page]

    lines = _extract_lines_from_node(ocr_result)
    if not lines:
        return []
    return [lines]


def _extract_lines_from_node(node: object) -> list[str]:
    lines: list[str] = []

    def add_line(value: object) -> None:
        if isinstance(value, str):
            line = value.strip()
            if line:
                lines.append(line)

    def visit(value: object, key_hint: str | None = None) -> None:
        if isinstance(value, str):
            if _is_text_key(key_hint):
                add_line(value)
            return

        if isinstance(value, Mapping):
            mapping = cast(Mapping[object, object], value)
            for raw_key, item in mapping.items():
                key = str(raw_key)
                if _is_text_key(key):
                    _collect_text_value(item, add_line)
                else:
                    visit(item, key)
            return

        if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
            sequence = value
            if _looks_like_ocr_tuple(sequence):
                _collect_text_value(sequence[1], add_line)
                return
            for item in sequence:
                visit(item, key_hint)
            return

        json_method = getattr(value, "json", None)
        if callable(json_method):
            try:
                visit(json_method())
                return
            except Exception:  # noqa: BLE001
                pass
        if json_method is not None:
            visit(json_method)
            return

        to_dict_method = getattr(value, "to_dict", None)
        if callable(to_dict_method):
            try:
                visit(to_dict_method())
                return
            except Exception:  # noqa: BLE001
                pass

        dict_attr = getattr(value, "__dict__", None)
        if isinstance(dict_attr, Mapping):
            visit(cast(Mapping[object, object], dict_attr))

    visit(node)
    return lines


def _is_text_key(key: str | None) -> bool:
    if key is None:
        return False
    normalized = key.lower()
    return normalized in {
        "rec_text",
        "rec_texts",
        "text",
        "texts",
        "label",
        "transcription",
        "ocr_text",
    }


def _collect_text_value(value: object, add_line: Callable[[object], None]) -> None:
    if isinstance(value, str):
        add_line(value)
        return
    if isinstance(value, Mapping):
        for item in value.values():
            _collect_text_value(item, add_line)
        return
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        sequence = value
        if _looks_like_score_tuple(sequence):
            add_line(sequence[0])
            return
        for item in sequence:
            _collect_text_value(item, add_line)


def _looks_like_ocr_tuple(sequence: Sequence[object]) -> bool:
    return len(sequence) >= 2 and _looks_like_points(sequence[0]) and _contains_text_candidate(sequence[1])


def _looks_like_points(value: object) -> bool:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes | bytearray):
        return False
    sequence = value
    return bool(sequence) and all(_looks_like_point(item) for item in sequence)


def _looks_like_point(value: object) -> bool:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes | bytearray):
        return False
    sequence = value
    return len(sequence) >= 2 and all(isinstance(item, int | float) for item in sequence[:2])


def _looks_like_score_tuple(sequence: Sequence[object]) -> bool:
    return len(sequence) >= 2 and isinstance(sequence[0], str) and isinstance(sequence[1], int | float)


def _contains_text_candidate(value: object) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, Mapping):
        mapping = cast(Mapping[object, object], value)
        return any(
            _is_text_key(str(key)) or _contains_text_candidate(item)
            for key, item in mapping.items()
        )
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return any(_contains_text_candidate(item) for item in value)
    return False


def write_docx(
    output_path: Path,
    pages: Sequence[Sequence[str]],
    document_factory: DocumentFactory | None = None,
) -> None:
    factory = document_factory if document_factory is not None else _load_document_factory()
    document = factory()
    _ = document.add_heading("OCR 识别结果", level=1)

    if not pages:
        _ = document.add_paragraph(EMPTY_OCR_NOTE)
    else:
        for page_number, lines in enumerate(pages, start=1):
            if len(pages) > 1:
                _ = document.add_heading(f"第 {page_number} 页", level=2)
            for line in lines:
                _ = document.add_paragraph(line)

    document.save(str(output_path.resolve()))


def convert_scan_to_word(
    input_path: Path,
    output_path: Path,
    lang: str = "ch",
    device: str = "cpu",
    enable_mkldnn: bool = False,
    ocr_provider: OcrProvider | None = None,
    document_factory: DocumentFactory | None = None,
) -> list[str]:
    provider = (
        ocr_provider
        if ocr_provider is not None
        else PaddleOcrProvider(lang=lang, device=device, enable_mkldnn=enable_mkldnn)
    )

    try:
        ocr_result = provider.predict(str(input_path.resolve()))
    except Exception as exc:  # noqa: BLE001
        message = (
            f"扫描件 OCR 识别失败：{input_path}。"
            f"底层原因：{type(exc).__name__}: {exc}。"
            "请确认输入文件清晰、PaddleOCR/PaddlePaddle 已正确安装；"
            "如在 Windows CPU 上遇到 oneDNN/MKLDNN 错误，请保持默认关闭 MKLDNN。"
        )
        raise RuntimeError(message) from exc

    try:
        pages = extract_text_pages(ocr_result)
    except Exception as exc:  # noqa: BLE001
        message = (
            f"OCR 结果解析失败：{input_path}。"
            f"底层原因：{type(exc).__name__}: {exc}。"
        )
        raise RuntimeError(message) from exc

    try:
        write_docx(output_path, pages, document_factory=document_factory)
    except Exception as exc:  # noqa: BLE001
        message = (
            f"写入 Word 失败：{output_path}。"
            f"底层原因：{type(exc).__name__}: {exc}。"
            "请确认输出目录存在且可写。"
        )
        raise RuntimeError(
            message
        ) from exc

    return []


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)

    try:
        input_path = Path(args.input).expanduser().resolve()
        output_arg = Path(args.output).expanduser() if args.output else None
        output_path = build_output_path(input_path, output_arg)

        validate_paths(input_path, output_path, overwrite=args.overwrite)
        warnings = convert_scan_to_word(
            input_path,
            output_path,
            lang=args.lang,
            device=args.device,
            enable_mkldnn=args.enable_mkldnn,
        )
    except (
        FileNotFoundError,
        FileExistsError,
        IsADirectoryError,
        RuntimeError,
        ValueError,
    ) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1

    for warning in warnings:
        print(f"警告：{warning}", file=sys.stderr)

    print(f"转换成功：{output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
