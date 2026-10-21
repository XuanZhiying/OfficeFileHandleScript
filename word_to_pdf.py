from __future__ import annotations

import argparse
import sys
from importlib import import_module
from pathlib import Path
from typing import Any, Sequence

WD_EXPORT_FORMAT_PDF = 17


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="把 Word 文档转换为 PDF。需要 Windows 本机已安装 Microsoft Word。",
    )
    parser.add_argument("input", help="输入的 Word 文件路径，支持 .doc / .docx")
    parser.add_argument(
        "output",
        nargs="?",
        help="输出 PDF 路径。若不传，则默认写到与输入文件同目录、同名 .pdf 文件。",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="允许覆盖已存在的 PDF 文件。",
    )
    return parser.parse_args(argv)


def build_output_path(input_path: Path, output_path: Path | None) -> Path:
    if output_path is None:
        return input_path.with_suffix(".pdf").resolve()
    return output_path.resolve()


def validate_paths(input_path: Path, output_path: Path, overwrite: bool) -> None:
    if not input_path.exists():
        raise FileNotFoundError(f"输入文件不存在：{input_path}")
    if input_path.is_dir():
        raise IsADirectoryError(f"输入路径是目录，不是文件：{input_path}")
    if input_path.suffix.lower() not in {".doc", ".docx"}:
        raise ValueError("输入文件必须是 .doc 或 .docx")
    if output_path.suffix.lower() != ".pdf":
        raise ValueError("输出文件必须使用 .pdf 扩展名")
    if not output_path.parent.exists():
        raise FileNotFoundError(f"输出目录不存在：{output_path.parent}")
    if output_path.exists() and not overwrite:
        raise FileExistsError(
            f"输出文件已存在：{output_path}。如需覆盖，请传入 --overwrite"
        )


def _load_word_client() -> Any:
    try:
        return import_module("win32com.client")
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "当前环境缺少 pywin32。请先执行 `uv sync` 安装依赖。"
        ) from exc


def _cleanup_word_objects(document: Any | None, word_app: Any | None) -> list[str]:
    cleanup_errors: list[str] = []

    if document is not None:
        try:
            document.Close(False)
        except Exception as exc:  # noqa: BLE001
            cleanup_errors.append(f"关闭 Word 文档失败：{exc}")

    if word_app is not None:
        try:
            word_app.Quit()
        except Exception as exc:  # noqa: BLE001
            cleanup_errors.append(f"退出 Word 进程失败：{exc}")

    return cleanup_errors


def convert_word_to_pdf(input_path: Path, output_path: Path) -> list[str]:
    win32_client = _load_word_client()
    word_app: Any | None = None
    document: Any | None = None
    cleanup_errors: list[str] = []

    try:
        try:
            word_app = win32_client.DispatchEx("Word.Application")
            word_app.Visible = False
            word_app.DisplayAlerts = 0

            document = word_app.Documents.Open(
                str(input_path.resolve()),
                ConfirmConversions=False,
                ReadOnly=True,
                AddToRecentFiles=False,
            )
            document.ExportAsFixedFormat(
                OutputFileName=str(output_path.resolve()),
                ExportFormat=WD_EXPORT_FORMAT_PDF,
                OpenAfterExport=False,
            )
        finally:
            cleanup_errors = _cleanup_word_objects(document, word_app)
    except Exception as exc:  # noqa: BLE001
        message = (
            f"Word 转 PDF 失败：{input_path} -> {output_path}。"
            "请确认已安装 Microsoft Word，源文件没有被其他程序占用，"
            "并且输出目录可写。"
        )
        if cleanup_errors:
            message = f"{message} 清理阶段还出现错误：{'；'.join(cleanup_errors)}"
        raise RuntimeError(message) from exc
    except BaseException as exc:
        if cleanup_errors:
            raise RuntimeError(
                f"Word 转 PDF 在中断后清理失败：{'；'.join(cleanup_errors)}"
            ) from exc
        raise

    if cleanup_errors:
        if output_path.exists() and output_path.is_file():
            return cleanup_errors
        raise RuntimeError(
            f"PDF 可能已经生成，但清理 Word 进程时发生错误：{'；'.join(cleanup_errors)}"
        )

    return []


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)

    try:
        input_path = Path(args.input).expanduser().resolve()
        output_arg = Path(args.output).expanduser() if args.output else None
        output_path = build_output_path(input_path, output_arg)

        validate_paths(input_path, output_path, overwrite=args.overwrite)
        warnings = convert_word_to_pdf(input_path, output_path)
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
