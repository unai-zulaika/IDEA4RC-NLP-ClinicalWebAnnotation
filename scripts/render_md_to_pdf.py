#!/usr/bin/env python3
"""Render markdown files to PDF using weasyprint with the same visual style as
the original NLP_variables_analysis.pdf (serif body, monospace tables, clean
table borders).
"""
from __future__ import annotations
from pathlib import Path
import sys

import markdown  # type: ignore
from weasyprint import HTML, CSS  # type: ignore

CSS_RULES = """
@page { size: A4; margin: 22mm 18mm; }
body { font-family: "Liberation Serif", "Times New Roman", serif; font-size: 11pt; line-height: 1.4; color: #111; }
h1 { font-size: 18pt; margin-top: 0; }
h2 { font-size: 14pt; margin-top: 1.4em; border-bottom: 1px solid #aaa; padding-bottom: 0.15em; }
h3 { font-size: 12pt; margin-top: 1.0em; }
p { margin: 0.5em 0; }
table { border-collapse: collapse; width: 100%; margin: 0.8em 0; font-size: 9.5pt; }
th, td { border: 1px solid #999; padding: 5px 8px; text-align: left; vertical-align: top; }
th { background: #f3f3f3; }
code { font-family: "Liberation Mono", "Courier New", monospace; font-size: 9.5pt; background: #f6f6f6; padding: 0 3px; border-radius: 2px; }
ul, ol { margin: 0.4em 0 0.4em 1.4em; }
li { margin: 0.15em 0; }
strong { color: #000; }
hr { border: none; border-top: 1px solid #ccc; margin: 1em 0; }
"""


def render(md_path: Path, pdf_path: Path) -> None:
    md_text = md_path.read_text(encoding="utf-8")
    html_body = markdown.markdown(md_text, extensions=["tables", "fenced_code"])
    full_html = f"<!doctype html><html><head><meta charset='utf-8'></head><body>{html_body}</body></html>"
    HTML(string=full_html).write_pdf(str(pdf_path), stylesheets=[CSS(string=CSS_RULES)])
    print(f"[ok] {md_path.name} -> {pdf_path}")


def main() -> None:
    # Ad-hoc mode: render an arbitrary markdown file.
    #   python scripts/render_md_to_pdf.py <input.md> [output.pdf]
    if len(sys.argv) > 1:
        md = Path(sys.argv[1]).resolve()
        pdf = Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else md.with_suffix(".pdf")
        render(md, pdf)
        return

    # Default mode: the center-specific report set (override via NLP_REPORT_CENTER).
    import os
    center = os.environ.get("NLP_REPORT_CENTER", "INT-SARC")
    base = Path("docs") / "reports" / center
    pairs = [
        (base / "NLP_variables_analysis_27B.md",  base / "NLP_variables_analysis_27B.pdf"),
        (base / "NLP_4B_vs_27B_comparison.md",    base / "NLP_4B_vs_27B_comparison.pdf"),
    ]
    repo_root = Path(__file__).resolve().parents[1]
    for md, pdf in pairs:
        render(repo_root / md, repo_root / pdf)


if __name__ == "__main__":
    main()
