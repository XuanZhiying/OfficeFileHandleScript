# Office 文件转换脚本（uv / Python 3.12）

这是一个最小可运行的 `uv` 项目，用来处理本地 Office 文档与 PDF 之间的单文件转换。

当前包含四类脚本：

- **Word 转 PDF**：基于 **Windows + Microsoft Word COM 自动化**
- **PDF 转 Word DOCX**：基于 `pdf2docx`
- **扫描版 PDF/图片 OCR 转 Word DOCX**：基于 `PaddleOCR` + `python-docx`，输出简单可编辑文字
- **Markdown 转 PDF（含本地图片）**：基于 `markdown-it-py` + 无头 Chrome/Edge 打印，图片会内联进 PDF

## 环境要求

- Windows
- Python 3.12
- `uv`

其中：

- 使用 `word2pdf` 时，本机需要已安装 Microsoft Word
- 使用 `pdf2word` 时，不要求安装 Microsoft Word，但转换效果依赖 PDF 本身的可解析程度
- 使用 `scanpdf2word` 时，会加载 PaddleOCR 模型；首次运行可能需要下载模型文件。脚本默认使用 CPU 并关闭 MKLDNN/oneDNN，以避开部分 Windows CPU + PaddlePaddle 版本的 oneDNN 兼容问题
- 使用 `md2pdf` 时，本机需要安装 Chrome 或 Edge（脚本自动查找，找不到可用 `--browser` 指定路径）
## 安装基础功能

```bash
uv sync --dev
```

### PaddleOCR / PaddlePaddle 说明

基础安装会保留 `word2pdf` 和 `pdf2word` 的轻量依赖，不会强制安装 PaddleOCR。只有使用 `scanpdf2word` 时才需要安装 OCR 可选依赖：

```bash
uv sync --dev --extra ocr
```

`paddlepaddle` 在 Windows + Python 3.12 下可能需要按 Paddle 官方发布情况选择安装源；如果 OCR 可选依赖没有自动装好 PaddlePaddle，请按当前环境手动安装，例如：

```bash
uv pip install paddlepaddle -i https://www.paddlepaddle.org.cn/packages/stable/cpu/
```

如需 GPU 版本，请以 PaddlePaddle 官方文档给出的 Windows 安装命令为准。

## Word 转 PDF

### 1. 使用项目脚本入口

```bash
uv run word2pdf "C:\docs\example.docx"
```

默认会在同目录生成同名 PDF，例如：

- 输入：`C:\docs\example.docx`
- 输出：`C:\docs\example.pdf`

### 2. 指定输出文件

```bash
uv run word2pdf "C:\docs\example.docx" "C:\output\example.pdf"
```

### 3. 允许覆盖已有 PDF

```bash
uv run word2pdf "C:\docs\example.docx" --overwrite
```

### 4. 直接运行 Python 文件

```bash
uv run python word_to_pdf.py "C:\docs\example.docx"
```

### 支持范围

- 支持：`.doc`、`.docx`
- 输出：`.pdf`
- 当前版本只处理**单个文件**，不包含目录批量转换

## PDF 转 Word DOCX

### 1. 使用项目脚本入口

```bash
uv run pdf2word "C:\docs\example.pdf"
```

默认会在同目录生成同名 DOCX，例如：

- 输入：`C:\docs\example.pdf`
- 输出：`C:\docs\example.docx`

### 2. 指定输出文件

```bash
uv run pdf2word "C:\docs\example.pdf" "C:\output\example.docx"
```

### 3. 允许覆盖已有 DOCX

```bash
uv run pdf2word "C:\docs\example.pdf" --overwrite
```

### 4. 直接运行 Python 文件

```bash
uv run python pdf_to_word.py "C:\docs\example.pdf"
```

### 支持范围

- 支持：`.pdf`
- 输出：`.docx`
- 当前版本只处理**单个文件**，不包含目录批量转换

### 注意事项

- 扫描版 PDF、图片型 PDF，通常不能像可编辑文本 PDF 那样获得理想的 Word 结果
- 表格、分栏、浮动对象、复杂分页等版式，转换后可能需要手工校对
- `pdf2docx` 更适合文本层清晰、结构相对规整的 PDF 文档

## 扫描版 PDF/图片 OCR 转 Word DOCX

`scanpdf2word` 是独立的新命令，面向扫描版 PDF、截图、照片等图片型文件。它会调用 PaddleOCR 识别文字，再用 `python-docx` 写入普通段落，目标是得到**可编辑文本 DOCX**，不是还原原始版式。

首次使用前请先安装 OCR 可选依赖：

```bash
uv sync --dev --extra ocr
```

### 1. 使用项目脚本入口

```bash
uv run scanpdf2word "C:\docs\scan.pdf"
```

默认会在同目录生成同名 DOCX，例如：

- 输入：`C:\docs\scan.pdf`
- 输出：`C:\docs\scan.docx`

### 2. 指定输出文件

```bash
uv run scanpdf2word "C:\docs\scan.png" "C:\output\scan.docx"
```

### 3. 允许覆盖已有 DOCX

```bash
uv run scanpdf2word "C:\docs\scan.jpg" --overwrite
```

### 4. 指定 OCR 语言模型

```bash
uv run scanpdf2word "C:\docs\scan.pdf" --lang ch
```

默认语言是 `ch`。中英文混排通常可以先用中文模型尝试，但不同版本 PaddleOCR 支持的语言参数和模型效果会变化；如果识别质量不理想，请根据 PaddleOCR 文档调整 `--lang`。

### 5. 指定推理设备或启用 MKLDNN

默认使用 CPU：

```bash
uv run scanpdf2word "C:\docs\scan.pdf" --device cpu
```

如果你已经正确配置 GPU，可以尝试：

```bash
uv run scanpdf2word "C:\docs\scan.pdf" --device gpu
```

脚本默认关闭 CPU MKLDNN/oneDNN。原因是部分 Windows CPU + PaddlePaddle 版本在 PP-OCRv5 推理时可能出现 oneDNN 兼容错误。如果你确认本机 PaddlePaddle 版本没有这个问题，可以手动启用：

```bash
uv run scanpdf2word "C:\docs\scan.pdf" --enable-mkldnn
```

### 6. 直接运行 Python 文件

```bash
uv run python scan_pdf_to_word.py "C:\docs\scan.pdf"
```

### 支持范围

- 支持：`.pdf`、`.png`、`.jpg`、`.jpeg`、`.bmp`、`.tif`、`.tiff`
- 输出：`.docx`
- 当前版本只处理**单个文件**，不包含目录批量转换

### 与 `pdf2word` 的区别

- `pdf2word`：适合已有文本层的普通 PDF，尽量转换 PDF 结构和版式
- `scanpdf2word`：适合扫描件或图片，先 OCR 识别文字，再写成简单 DOCX 段落
- `scanpdf2word` 不追求高保真排版；表格、栏位、页眉页脚、复杂布局需要人工整理
- 如果 OCR 没有识别到文字，也会生成 DOCX，并写入“未识别到可编辑文字”的提示
## Markdown 转 PDF（含本地图片）

把 Markdown 文件转成 PDF。转换前会先检查文档引用的图片是否齐全（缺失只告警），Markdown 里的相对路径图片会被自动定位并以 base64 内联进 PDF，图片下方默认不加图注。

### 1. 使用项目脚本入口

```bash
uv run md2pdf "File\temu-app-review\product-testing-sop-en.md"
```

默认在同目录生成同名 PDF：

- 输入：`File\temu-app-review\product-testing-sop-en.md`
- 输出：`File\temu-app-review\product-testing-sop-en.pdf`

### 2. 指定输出文件

```bash
uv run md2pdf "File\temu-app-review\product-testing-sop-en.md" -o "C:\output\sop-en.pdf"
```

### 3. 指定浏览器

```bash
uv run md2pdf doc.md --browser edge
uv run md2pdf doc.md --browser "D:\Chrome\chrome.exe"
```

### 4. 其他开关

```bash
uv run md2pdf doc.md --keep-html       # 保留 doc.md2pdf.html 便于排查样式
uv run md2pdf doc.md --url-images      # 图片用 file:// 引用而非 base64 内联
uv run md2pdf doc.md --captions        # 把 alt 文本渲染成图片下方的图注
uv run md2pdf doc.md --strict-images   # 图片缺失时报错退出（默认只告警）
```

### 支持范围

- **转换前图片检查**：先扫描文档里所有 `![...](...)` 与 `<img src>`，列出缺失的图片并告警，然后照常转换
- GFM 表格、代码块、引用块、列表、删除线、自动链接
- 本地图片（相对或绝对路径，支持中文路径），图片不跨页断裂
- 排列为 A4 版式、中文字体、表格边框；页眉页脚不输出
- 图片下方**默认不生成图注**（alt 文本只保留在 `alt` 属性里）；需要图注时加 `--captions`
- 缺失的图片会替换成红色 `[image missing]` 占位框，不会静默丢图

### 图片检查与 `--strict-images`

转换前会先做一次图片检查，输出类似：

```text
[check] 图片引用: 4 个（本地 4 / 外部 0），存在 4，缺失 0
[check] 所有本地图片均已找到 ✓
```

有缺图时只告警、不中断，PDF 里对应位置显示红色占位框：

```text
[check] 图片引用: 4 个（本地 4 / 外部 0），存在 3，缺失 1
[warn] 有 1 张图片缺失，转换仍会继续，PDF 中会显示红色占位框:
[warn]   images/05-ship-label.png  ->  E:\...\images\05-ship-label.png
[warn] 请补齐图片后重新转换；若希望缺失即报错退出，可加 --strict-images
```

希望缺图直接失败（如 CI 场景）：

```bash
uv run md2pdf doc.md --strict-images   # 缺图时报错，退出码 1，不生成 PDF
```

### 注意事项

- 依赖本机 Chrome 或 Edge（脚本按 Chrome → Edge 顺序自动查找）；纯命令行环境/CI 需显式 `--browser`
- 输出为“打印版”PDF：交互式折叠块、HTML 内联脚本不会生效
- 图片宽度按页面宽度自适应，超大图会等比缩小
- 远程图片（`http(s)://`）不做本地检查，交由浏览器直接加载，需要网络可访问

## 常见问题

### 1. 为什么必须安装 Microsoft Word？

因为 `word2pdf` 脚本直接调用了 Word 的导出能力，这样生成 PDF 的版式通常最接近用户在 Word 里看到的效果。

### 2. 没安装 Word 可以用吗？

如果你要用的是 `word2pdf`，当前这版不行；它依赖本机安装的 Microsoft Word。

如果你要用的是 `pdf2word`，则不依赖 Word，但转换质量取决于 PDF 内容是否容易解析。

### 3. 运行失败时应该检查什么？

- `word2pdf` 场景下：Word 是否已正确安装、输入文件是否被占用
- `pdf2word` 场景下：PDF 是否损坏、是否属于扫描件或极复杂版式
- `scanpdf2word` 场景下：PaddleOCR/PaddlePaddle 是否安装成功、图片是否清晰、`--lang` 是否适合输入内容
- 输出目录是否存在、是否可写
- 是否先执行了 `uv sync --dev`

## 开发验证

```bash
uv run pytest -q
uv run python -m py_compile word_to_pdf.py pdf_to_word.py scan_pdf_to_word.py
uv run word2pdf --help
uv run pdf2word --help
uv run scanpdf2word --help
```
