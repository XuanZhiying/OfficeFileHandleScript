"""Markdown 转 PDF（含本地图片），基于 markdown-it-py + 无头 Chrome/Edge 打印。

特性
- 转换前先检查图片：缺失只告警，`--strict-images` 时改为报错退出
- 支持 GFM 表格、代码块、删除线、自动链接
- 把 Markdown 中的本地图片内联为 base64，避免相对路径/中文路径导致的丢图
- A4 版式、中文字体、表格边框、图片不跨页断裂；默认不生成图注（`--captions` 可开启）
- 优先使用本机 Chrome，找不到时回退到 Edge

用法
    python md_to_pdf.py doc.md                    # 输出 doc.pdf（与 md 同目录）
    python md_to_pdf.py doc.md -o out/report.pdf
    python md_to_pdf.py doc.md --browser edge --keep-html
    python md_to_pdf.py doc.md --strict-images     # 缺图直接报错，不生成 PDF
    python md_to_pdf.py doc.md --captions          # 用 alt 文本作为图片下方的图注

依赖
    pip install markdown-it-py pymupdf   （本项目 .venv 已包含）
"""

from __future__ import annotations

import argparse
import base64
import mimetypes
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
from pathlib import Path
from markdown_it import MarkdownIt

BROWSER_CANDIDATES = {
    "chrome": [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        "chrome",
        "google-chrome",
        "chromium",
    ],
    "edge": [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        "msedge",
    ],
}

CSS = """
@page {
  size: A4;
  margin: 18mm 16mm 18mm 16mm;
}
html { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
body {
  font-family: "Segoe UI", "Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", sans-serif;
  font-size: 10.5pt;
  line-height: 1.62;
  color: #1f2328;
  margin: 0;
  word-wrap: break-word;
}
h1, h2, h3, h4, h5, h6 {
  font-weight: 600;
  line-height: 1.3;
  margin: 1.15em 0 0.5em;
  break-after: avoid;
  page-break-after: avoid;
}
h1 { font-size: 20pt; border-bottom: 2px solid #d0d7de; padding-bottom: 6px; margin-top: 0; }
h2 { font-size: 15pt; border-bottom: 1px solid #e3e7eb; padding-bottom: 4px; }
h3 { font-size: 12.5pt; }
h4 { font-size: 11pt; }
p, li { orphans: 3; widows: 3; }
a { color: #0b62c4; text-decoration: none; }
code {
  font-family: Consolas, "Cascadia Mono", "Courier New", monospace;
  font-size: 0.9em;
  background: #f2f4f7;
  border: 1px solid #e3e7eb;
  border-radius: 3px;
  padding: 0.1em 0.32em;
}
pre {
  background: #f6f8fa;
  border: 1px solid #e3e7eb;
  border-radius: 4px;
  padding: 9px 11px;
  overflow: hidden;
  white-space: pre-wrap;
  break-inside: avoid;
  page-break-inside: avoid;
}
pre code { background: none; border: none; padding: 0; font-size: 0.86em; }
blockquote {
  margin: 0.9em 0;
  padding: 0.45em 0.9em;
  border-left: 3px solid #b6c2cf;
  background: #f7f9fb;
  color: #444c56;
  break-inside: avoid;
}
blockquote p { margin: 0.3em 0; }
table {
  border-collapse: collapse;
  width: 100%;
  margin: 0.85em 0;
  font-size: 9.5pt;
  break-inside: auto;
}
th, td {
  border: 1px solid #cfd6dd;
  padding: 5px 7px;
  vertical-align: top;
  text-align: left;
}
th { background: #eef1f5; font-weight: 600; }
tr { break-inside: avoid; page-break-inside: avoid; }
thead { display: table-header-group; }
img {
  max-width: 100%;
  height: auto;
  display: block;
  margin: 0.7em auto;
  border: 1px solid #d8dee4;
  border-radius: 4px;
  break-inside: avoid;
  page-break-inside: avoid;
}
hr { border: none; border-top: 1px solid #d8dee4; margin: 1.4em 0; }
ul, ol { padding-left: 1.5em; margin: 0.5em 0; }
li > p { margin: 0.25em 0; }
figure {
  margin: 0.9em 0;
  text-align: center;
  break-inside: avoid;
  page-break-inside: avoid;
}
figcaption {
  font-size: 8.8pt;
  color: #57606a;
  margin-top: 4px;
  line-height: 1.45;
}
"""

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>{css}</style>
</head>
<body>
{body}
</body>
</html>
"""


def find_browser(preferred: str = "auto") -> str:
    """返回可用的浏览器可执行文件路径。"""
    order = ["chrome", "edge"] if preferred == "auto" else [preferred]
    for name in order:
        for candidate in BROWSER_CANDIDATES.get(name, []):
            found = shutil.which(candidate) or (candidate if Path(candidate).is_file() else None)
            if found:
                return found
    raise RuntimeError("未找到 Chrome 或 Edge，请用 --browser 指定浏览器可执行文件路径")


def _trim(text: str) -> str:
    """Chrome 在无头模式下对过长的 data URI 更稳，去掉图片 base64 中的换行。"""
    return text.replace("\n", "")


def inline_local_images(html: str, base_dir: Path, tmp_dir: Path, use_data_uri: bool) -> tuple[str, list[str]]:
    """把 <img src="相对路径"> 换成 base64 data URI 或绝对 file URI。

    返回 (处理后 html, 缺失图片列表)。缺失图片会替换为可见的提示框，避免静默丢图。
    """
    out = []
    missing: list[str] = []
    pos = 0
    needle = "<img"
    while True:
        start = html.find(needle, pos)
        if start == -1:
            out.append(html[pos:])
            break
        out.append(html[pos:start])
        end = html.find(">", start)
        if end == -1:
            out.append(html[start:])
            break
        tag = html[start : end + 1]
        pos = end + 1

        src_at = tag.find('src="')
        if src_at == -1:
            out.append(tag)
            continue
        src_at += len('src="')
        src_end = tag.find('"', src_at)
        src = tag[src_at:src_end]

        if src.startswith(("http://", "https://", "data:", "file:")):
            out.append(tag)
            continue

        candidate = Path(urllib.parse.unquote(src))
        if not candidate.is_absolute():
            candidate = (base_dir / candidate).resolve()
        if not candidate.is_file():
            missing.append(src)
            print(f"[warn] 图片不存在，已插入占位提示: {src}", file=sys.stderr)
            out.append(
                '<div style="border:1px dashed #d1242f;color:#d1242f;padding:10px;'
                'text-align:center;font-size:9pt;margin:0.6em 0;">'
                f"[image missing] {src}</div>"
            )
            continue

        if use_data_uri:
            mime = mimetypes.guess_type(candidate.name)[0] or "image/png"
            data = _trim(base64.b64encode(candidate.read_bytes()).decode("ascii"))
            tag = f'{tag[:src_at]}data:{mime};base64,{data}{tag[src_end:]}'
        else:
            # 复制到临时目录，规避中文/空格路径在 file:// 下的转义问题
            target = tmp_dir / f"img{len(missing)}{candidate.suffix}"
            shutil.copyfile(candidate, target)
            tag = f'{tag[:src_at]}{target.as_uri()}{tag[src_end:]}'
        out.append(tag)
    return "".join(out), missing

IMAGE_REFS_MD = re.compile(
    r"!\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+[\"'][^\"']*[\"'])?\s*\)"
)
IMAGE_REFS_HTML = re.compile(r"<img\b[^>]*?\bsrc=[\"']([^\"']+)[\"']", re.IGNORECASE)


def _is_external(ref: str) -> bool:
    return ref.startswith(("http://", "https://", "//", "data:", "file:"))


def collect_image_refs(md_text: str) -> list[str]:
    """按文档出现顺序收集图片地址（`![]()` 与内嵌 `<img>`），去重保序。"""
    hits: list[tuple[int, str]] = []
    for pattern in (IMAGE_REFS_MD, IMAGE_REFS_HTML):
        hits.extend((match.start(), match.group(1).strip()) for match in pattern.finditer(md_text))
    refs: list[str] = []
    for _, ref in sorted(hits):
        if ref and ref not in refs:
            refs.append(ref)
    return refs


def resolve_image_ref(ref: str, base_dir: Path) -> Path:
    """把图片引用解析成绝对路径（相对路径基于 md 所在目录）。"""
    candidate = Path(urllib.parse.unquote(ref))
    return candidate if candidate.is_absolute() else (base_dir / candidate).resolve()


def check_images(
    refs: list[str], base_dir: Path
) -> tuple[list[tuple[str, Path]], list[tuple[str, Path]], list[str]]:
    """转换前检查图片是否齐全。

    返回 (存在的图片, 缺失的图片, 外部/远程引用)，每项都是 (原始引用, 绝对路径)。
    """
    found: list[tuple[str, Path]] = []
    missing: list[tuple[str, Path]] = []
    external: list[str] = []
    for ref in refs:
        if _is_external(ref):
            external.append(ref)
            continue
        path = resolve_image_ref(ref, base_dir)
        (found if path.is_file() else missing).append((ref, path))
    return found, missing, external


def report_image_check(
    md_path: Path,
    found: list[tuple[str, Path]],
    missing: list[tuple[str, Path]],
    external: list[str],
) -> None:
    """打印转换前的图片检查结果；缺失的图片只告警，不阻断转换。"""
    total = len(found) + len(missing) + len(external)
    if total == 0:
        print("[check] 图片引用: 0 个（文档中未引用图片）")
        return
    print(
        f"[check] 图片引用: {total} 个（本地 {len(found) + len(missing)} / 外部 {len(external)}），"
        f"存在 {len(found)}，缺失 {len(missing)}"
    )
    if external:
        print(f"[check] 外部引用交由浏览器加载: {', '.join(external)}")
    if not missing:
        print("[check] 所有本地图片均已找到 ✓")
        return
    print(f"[warn] 有 {len(missing)} 张图片缺失，转换仍会继续，PDF 中会显示红色占位框:", file=sys.stderr)
    for ref, path in missing:
        print(f"[warn]   {ref}  ->  {path}", file=sys.stderr)
    print(
        f"[warn] 文档: {md_path}\n"
        "[warn] 请补齐图片后重新转换；若希望缺失即报错退出，可加 --strict-images",
        file=sys.stderr,
    )
def _render_image(self, tokens, idx, options, env) -> str:
    """图片渲染为纯 <img>（默认不加图注）。

    alt 文本仍保留在 alt 属性里，但不会作为可见文字输出。
    add_render_rule 会把函数绑定到 renderer 上，因此第一个参数是 renderer 自身。
    """
    return f"<img{self.renderAttrs(tokens[idx])}>"


def _render_captioned_image(self, tokens, idx, options, env) -> str:
    """图片渲染为带图注的 <figure>，图注取自 alt 文本（需显式 --captions 开启）。"""
    token = tokens[idx]
    alt = token.content or ""
    img = f"<img{self.renderAttrs(token)}>"
    if not alt.strip():
        return img
    return f"<figure>{img}<figcaption>{alt}</figcaption></figure>"


def markdown_to_html(md_text: str, captions: bool = False) -> str:
    options = {"html": True, "typographer": False}
    try:  # linkify 需要可选的 linkify-it-py，装了才启用
        import linkify_it  # noqa: F401

        options["linkify"] = True
    except ImportError:
        options["linkify"] = False
    md = MarkdownIt("gfm-like", options)
    md.add_render_rule("image", _render_captioned_image if captions else _render_image)
    html = md.render(md_text)
    if not captions:
        return html
    # <figure> 是块级元素，不能包在 <p> 里，去掉包裹它的空段落
    return html.replace("<p><figure>", "<figure>").replace("</figure></p>", "</figure>")


def print_to_pdf(browser: str, html_path: Path, pdf_path: Path, timeout: int = 120) -> None:
    """用无头浏览器把本地 HTML 打印成 PDF。"""
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="md2pdf-profile-") as profile:
        cmd = [
            browser,
            "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            "--no-default-browser-check",
            "--no-pdf-header-footer",
            "--virtual-time-budget=15000",
            "--run-all-compositor-stages-before-draw",
            f"--user-data-dir={profile}",
            f"--print-to-pdf={pdf_path}",
            html_path.as_uri(),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if not pdf_path.is_file() or pdf_path.stat().st_size == 0:
        raise RuntimeError(
            "PDF 生成失败：\n" + (proc.stderr or proc.stdout or "无输出").strip()[-2000:]
        )


def pdf_info(pdf_path: Path) -> tuple[int, tuple[float, float]]:
    """返回 (页数, (宽pt, 高pt))；PyMuPDF 不可用时返回 (0, (0, 0))。"""
    try:
        import fitz  # PyMuPDF
    except ImportError:
        return 0, (0.0, 0.0)
    with fitz.open(pdf_path) as doc:
        page = doc[0]
        return doc.page_count, (round(page.rect.width, 1), round(page.rect.height, 1))


def convert(
    md_path: Path,
    pdf_path: Path | None = None,
    browser_pref: str = "auto",
    keep_html: bool = False,
    use_data_uri: bool = True,
    captions: bool = False,
    strict_images: bool = False,
) -> Path:
    md_path = md_path.resolve()
    if not md_path.is_file():
        raise FileNotFoundError(f"Markdown 文件不存在: {md_path}")
    pdf_path = (pdf_path or md_path.with_suffix(".pdf")).resolve()
    base_dir = md_path.parent

    md_text = md_path.read_text(encoding="utf-8")

    # 转换前先检查图片：缺图只告警，仍然继续转换（--strict-images 时改为报错退出）
    found, missing_refs, external = check_images(collect_image_refs(md_text), base_dir)
    report_image_check(md_path, found, missing_refs, external)
    if missing_refs and strict_images:
        raise FileNotFoundError(
            f"缺少 {len(missing_refs)} 张图片（--strict-images 已开启，放弃转换）: "
            + ", ".join(ref for ref, _ in missing_refs)
        )

    html = markdown_to_html(md_text, captions=captions)

    with tempfile.TemporaryDirectory(prefix="md2pdf-file-") as tmp:
        tmp_dir = Path(tmp)
        html, missing = inline_local_images(html, base_dir, tmp_dir, use_data_uri)
        page = HTML_TEMPLATE.format(
            lang="zh-CN", title=md_path.stem, css=CSS, body=html
        )
        html_path = (base_dir / f"{md_path.stem}.md2pdf.html") if keep_html else tmp_dir / "page.html"
        html_path.write_text(page, encoding="utf-8")

        browser = find_browser(browser_pref)
        print(f"[info] 浏览器: {browser}")
        print(f"[info] 图片: 内联 {html.count('data:image')} 个，缺失 {len(missing)} 个")
        print_to_pdf(browser, html_path, pdf_path)

    if keep_html:
        print(f"[info] HTML 已保留: {html_path}")

    pages, size = pdf_info(pdf_path)
    print(f"[ok] 输出: {pdf_path}  ({pdf_path.stat().st_size / 1024:.1f} KB)")
    if pages:
        print(f"[ok] 共 {pages} 页，首页尺寸 {size[0]}x{size[1]} pt (A4 = 595x842)")
    return pdf_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Markdown（含本地图片）转 PDF")
    parser.add_argument("md", type=Path, help="输入的 .md 文件")
    parser.add_argument("-o", "--output", type=Path, help="输出的 .pdf 路径，默认与 md 同目录同名")
    parser.add_argument(
        "--browser", default="auto", help="auto | chrome | edge | 浏览器可执行文件绝对路径"
    )
    parser.add_argument("--keep-html", action="store_true", help="保留中间 HTML 便于调试")
    parser.add_argument(
        "--url-images", action="store_true", help="图片改用 file:// 引用而非 base64 内联"
    )
    parser.add_argument(
        "--captions", action="store_true", help="把图片 alt 文本渲染为图注（默认不显示图注）"
    )
    parser.add_argument(
        "--strict-images",
        action="store_true",
        help="图片缺失时报错退出（默认只告警并继续转换）",
    )
    args = parser.parse_args(argv)

    try:
        convert(
            args.md,
            args.output,
            args.browser,
            args.keep_html,
            use_data_uri=not args.url_images,
            captions=args.captions,
            strict_images=args.strict_images,
        )
    except Exception as exc:  # noqa: BLE001 - CLI 入口统一报错
        print(f"[error] {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
