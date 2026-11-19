# -*- coding: utf-8 -*-
"""
讲义 Markdown → PDF。

方案：Markdown → HTML（本地 KaTeX 渲染公式）→ 系统 Edge 无头打印 PDF。
不依赖 LibreOffice / pandoc，纯 Playwright + 本地 KaTeX 资源，离线可用。
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
KATEX_DIR = os.path.normpath(os.path.join(HERE, "..", "assets", "katex"))

STYLE = """
@page { size: A4; margin: 16mm 14mm; }
body { font-family: "Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", sans-serif;
       font-size: 11.5pt; line-height: 1.75; color: #1a1a1a; }
h1 { font-size: 22pt; text-align: center; margin: 0 0 10pt; }
h2 { font-size: 16pt; color: #1f4e79; border-bottom: 2px solid #1f4e79;
     padding-bottom: 4pt; margin-top: 18pt; page-break-after: avoid; }
h3 { font-size: 13.5pt; color: #2e74b5; margin-top: 14pt; page-break-after: avoid; }
h4 { font-size: 12pt; color: #2e74b5; margin-top: 12pt; page-break-after: avoid; }
p { margin: 5pt 0; }
blockquote { border-left: 4px solid #9cc3e5; background: #f4f8fc; margin: 8pt 0;
             padding: 6pt 10pt; color: #444; }
table { border-collapse: collapse; width: 100%; margin: 8pt 0; font-size: 10.5pt; }
th, td { border: 1px solid #bbb; padding: 4pt 6pt; vertical-align: top; }
th { background: #e8f1fa; }
pre { background: #f6f8fa; border: 1px solid #e1e4e8; padding: 8pt;
      white-space: pre-wrap; page-break-inside: avoid; }
code { font-family: Consolas, "Courier New", monospace; font-size: 0.92em; }
ul, ol { margin: 4pt 0; padding-left: 20pt; }
li { margin: 2pt 0; }
hr { border: none; border-top: 1px solid #ddd; margin: 12pt 0; }
.katex-display { margin: 8pt 0; }
"""


def _file_url(path):
    p = os.path.abspath(path).replace("\\", "/")
    return "file:///" + p


# Markdown 会把 \( \) \[ \] 当成转义字符吃掉反斜杠，导致 KaTeX 定界符失效。
# 渲染前先用占位符保护，渲染后再还原。
_LATEX_GUARDS = [
    ("\\(", "ZJLPAREN"), (("\\)"), "ZJRPAREN"),
    ("\\[", "ZJLBRACKET"), ("\\]", "ZJBRACKET"),
]


def _protect_latex(text):
    for src, tok in _LATEX_GUARDS:
        text = text.replace(src, tok)
    return text


def _restore_latex(html):
    for src, tok in _LATEX_GUARDS:
        html = html.replace(tok, src)
    return html


def render_pdf(md_path, pdf_path=None, progress=None):
    """把 Markdown 讲义渲染成 PDF，返回 PDF 路径。失败抛异常（由调用方决定是否忽略）。"""
    def log(msg):
        if progress:
            progress(msg)

    md_path = os.path.abspath(md_path)
    if not os.path.isfile(md_path):
        raise FileNotFoundError(md_path)
    with open(md_path, encoding="utf-8") as f:
        text = f.read()

    import markdown as mdlib
    html_body = mdlib.markdown(
        _protect_latex(text), extensions=["tables", "fenced_code", "sane_lists"])
    html_body = _restore_latex(html_body)

    katex_css = _file_url(os.path.join(KATEX_DIR, "katex.min.css"))
    katex_js = _file_url(os.path.join(KATEX_DIR, "katex.min.js"))
    auto_render = _file_url(os.path.join(
        KATEX_DIR, "contrib", "auto-render.min.js"))
    html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<link rel="stylesheet" href="{katex_css}">
<style>{STYLE}</style>
</head><body>
{html_body}
<script src="{katex_js}"></script>
<script src="{auto_render}"></script>
<script>
try {{
  renderMathInElement(document.body, {{
    delimiters: [
      {{left: "$$", right: "$$", display: true}},
      {{left: "$", right: "$", display: false}},
      {{left: "\\\\(", right: "\\\\)", display: false}},
      {{left: "\\\\[", right: "\\\\]", display: true}}
    ],
    throwOnError: false
  }});
}} catch (e) {{}}
</script>
</body></html>"""

    html_path = os.path.splitext(md_path)[0] + ".pdf.html"
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)
    pdf_path = pdf_path or os.path.splitext(md_path)[0] + ".pdf"

    log("渲染 PDF（KaTeX 公式 + Edge 打印）…")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = None
        for channel in ("msedge", "chrome"):
            try:
                browser = p.chromium.launch(channel=channel, headless=True)
                break
            except Exception:
                continue
        if browser is None:
            browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.on("pageerror", lambda e: log(f"[pageerror] {str(e)[:300]}"))
        try:
            page.goto(_file_url(html_path), wait_until="load", timeout=60000)
            page.wait_for_timeout(500)
            log("katex=" + str(page.evaluate("typeof window.katex")) +
                " autoRender=" + str(page.evaluate("typeof window.renderMathInElement")) +
                " rendered=" + str(page.evaluate("document.querySelectorAll('.katex').length")))
            try:
                page.wait_for_function(
                    "document.querySelectorAll('.katex').length > 0", timeout=8000)
            except Exception:
                pass            # 无公式的文档正常
            page.wait_for_timeout(300)
            page.pdf(path=pdf_path, format="A4", print_background=True,
                     margin={"top": "16mm", "bottom": "16mm",
                             "left": "14mm", "right": "14mm"})
        finally:
            browser.close()
            try:
                os.unlink(html_path)
            except OSError:
                pass
    log(f"PDF 已生成：{pdf_path}")
    return pdf_path
