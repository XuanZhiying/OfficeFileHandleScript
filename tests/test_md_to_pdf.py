from __future__ import annotations

from pathlib import Path

import md_to_pdf


def test_markdown_to_html_renders_table() -> None:
    html = md_to_pdf.markdown_to_html("| a | b |\n| --- | --- |\n| 1 | 2 |\n")

    assert "<table>" in html
    assert "<th>a</th>" in html and "<td>1</td>" in html


def test_markdown_to_html_omits_caption_by_default() -> None:
    html = md_to_pdf.markdown_to_html("![Fig. 01 | Entry](images/01.png)\n")

    assert "<img" in html
    assert "figcaption" not in html
    assert "Fig. 01" not in html  # alt 只进属性，不作为可见文字


def test_markdown_to_html_can_enable_captions() -> None:
    html = md_to_pdf.markdown_to_html("![Fig. 01 | Entry](images/01.png)\n", captions=True)

    assert "<figcaption>Fig. 01 | Entry</figcaption>" in html
    assert "<p><figure>" not in html


def test_collect_image_refs_dedups_and_keeps_order() -> None:
    md = (
        "![a](images/01.png)\n"
        "![b](images/02.png \"title\")\n"
        "![a again](images/01.png)\n"
        '<img src="images/03.png">\n'
        "![remote](https://example.com/x.png)\n"
    )

    assert md_to_pdf.collect_image_refs(md) == [
        "images/01.png",
        "images/02.png",
        "images/03.png",
        "https://example.com/x.png",
    ]


def test_check_images_splits_found_missing_and_external(tmp_path: Path) -> None:
    (tmp_path / "images").mkdir()
    _ = (tmp_path / "images" / "ok.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")
    refs = ["images/ok.png", "images/gone.png", "https://example.com/x.png"]

    found, missing, external = md_to_pdf.check_images(refs, tmp_path)

    assert [ref for ref, _ in found] == ["images/ok.png"]
    assert [ref for ref, _ in missing] == ["images/gone.png"]
    assert external == ["https://example.com/x.png"]
    assert missing[0][1] == (tmp_path / "images" / "gone.png").resolve()


def test_report_image_check_warns_but_does_not_raise(
    tmp_path: Path, capsys
) -> None:
    md_path = tmp_path / "doc.md"
    found = [("images/ok.png", tmp_path / "images" / "ok.png")]
    missing = [("images/gone.png", tmp_path / "images" / "gone.png")]

    md_to_pdf.report_image_check(md_path, found, missing, [])  # 只打印，不抛异常

    captured = capsys.readouterr()
    assert "存在 1，缺失 1" in captured.out
    assert "images/gone.png" in captured.err
    assert "--strict-images" in captured.err


def test_convert_stops_before_browser_when_strict_images_and_missing(
    tmp_path: Path,
) -> None:
    md_path = tmp_path / "doc.md"
    _ = md_path.write_text("![x](images/gone.png)\n", encoding="utf-8")

    try:
        md_to_pdf.convert(md_path, strict_images=True)
    except FileNotFoundError as exc:
        assert "缺少 1 张图片" in str(exc)
    else:  # pragma: no cover - 走不到这里
        raise AssertionError("strict_images 未生效")
    assert not (tmp_path / "doc.pdf").exists()



def test_inline_local_images_embeds_base64(tmp_path: Path) -> None:
    image_dir = tmp_path / "images"
    image_dir.mkdir()
    _ = (image_dir / "a.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")
    html = '<p><img src="images/a.png" alt="x"></p>'

    result, missing = md_to_pdf.inline_local_images(html, tmp_path, tmp_path, use_data_uri=True)

    assert missing == []
    assert 'src="data:image/png;base64,' in result


def test_inline_local_images_reports_missing_file(tmp_path: Path) -> None:
    result, missing = md_to_pdf.inline_local_images(
        '<img src="images/none.png" alt="x">', tmp_path, tmp_path, use_data_uri=True
    )

    assert missing == ["images/none.png"]
    assert "[image missing]" in result


def test_inline_local_images_keeps_remote_and_data_urls(tmp_path: Path) -> None:
    html = '<img src="https://example.com/a.png"><img src="data:image/png;base64,AAA">'

    result, missing = md_to_pdf.inline_local_images(html, tmp_path, tmp_path, use_data_uri=True)

    assert result == html
    assert missing == []
