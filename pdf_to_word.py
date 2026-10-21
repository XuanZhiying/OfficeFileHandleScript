from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from importlib import import_module
from pathlib import Path
from typing import Protocol, cast


class ArgsNamespace(argparse.Namespace):
    input: str
    output: str | None
    overwrite: bool

    def __init__(self) -> None:
        super().__init__()
        self.input = ""
        self.output = None
        self.overwrite = False


class PdfConverter(Protocol):
    def convert(self, target: str) -> None: ...

    def close(self) -> None: ...


type ConverterFactory = Callable[[str], PdfConverter]


def parse_args(argv: Sequence[str] | None = None) -> ArgsNamespace:
    parser = argparse.ArgumentParser(
        description="把 PDF 文件转换为 Word DOCX 文档。",
    )
    _ = parser.add_argument("input", help="输入的 PDF 文件路径，支持 .pdf")
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
    if input_path.suffix.lower() != ".pdf":
        raise ValueError("输入文件必须是 .pdf")
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


def _load_converter_class() -> ConverterFactory:
    try:
        module = import_module("pdf2docx")
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "当前环境缺少 pdf2docx。请先执行 `uv sync --dev` 安装依赖。"
        ) from exc

    converter = getattr(module, "Converter", None)
    if not callable(converter):
        raise RuntimeError(
            "当前环境中的 pdf2docx 缺少可用的 Converter 接口，请尝试重新安装依赖。"
        )

    return cast(ConverterFactory, converter)


def _cleanup_converter(converter: PdfConverter | None) -> list[str]:
    cleanup_errors: list[str] = []

    if converter is not None:
        try:
            converter.close()
        except Exception as exc:  # noqa: BLE001
            cleanup_errors.append(f"关闭 PDF 转换器失败：{exc}")

    return cleanup_errors


def convert_pdf_to_word(input_path: Path, output_path: Path) -> list[str]:
    converter_class = _load_converter_class()
    converter: PdfConverter | None = None
    cleanup_errors: list[str] = []

    try:
        try:
            active_converter = converter_class(str(input_path.resolve()))
            converter = active_converter
            active_converter.convert(str(output_path.resolve()))
        finally:
            cleanup_errors = _cleanup_converter(converter)
    except Exception as exc:  # noqa: BLE001
        message = (
            f"PDF 转 Word 失败：{input_path} -> {output_path}。"
            "请确认 PDF 文件未损坏、不是扫描件或极复杂版式导致无法正确解析，"
            "并且输出目录可写。"
        )
        if cleanup_errors:
            message = f"{message} 清理阶段还出现错误：{'；'.join(cleanup_errors)}"
        raise RuntimeError(message) from exc
    except BaseException as exc:
        if cleanup_errors:
            raise RuntimeError(
                f"PDF 转 Word 在中断后清理失败：{'；'.join(cleanup_errors)}"
            ) from exc
        raise

    if cleanup_errors:
        if output_path.exists() and output_path.is_file():
            return cleanup_errors
        raise RuntimeError(
            f"DOCX 可能已经生成，但清理转换器时发生错误：{'；'.join(cleanup_errors)}"
        )

    return []


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)

    try:
        input_path = Path(args.input).expanduser().resolve()
        output_arg = Path(args.output).expanduser() if args.output else None
        output_path = build_output_path(input_path, output_arg)

        validate_paths(input_path, output_path, overwrite=args.overwrite)
        warnings = convert_pdf_to_word(input_path, output_path)
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
