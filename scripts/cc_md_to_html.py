#!/usr/bin/env python3
"""Convert a Markdown report to a Gmail-compatible styled HTML file.

Usage:
    python3 scripts/cc_md_to_html.py report.md          # writes report.html
    python3 scripts/cc_md_to_html.py report.md out.html # custom output path
    python3 scripts/cc_md_to_html.py report.md --print  # print path only (for shell capture)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import markdown

HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{
  font-family: -apple-system, "Noto Sans TC", "Microsoft JhengHei", Arial, sans-serif;
  font-size: 14px;
  line-height: 1.75;
  color: #1a1a2e;
  background: #f4f6fb;
  padding: 24px 16px;
}}
.container {{ max-width: 900px; margin: 0 auto; background: #fff; border-radius: 10px; padding: 28px 32px; box-shadow: 0 2px 12px rgba(0,0,0,0.08); }}
h1 {{ font-size: 1.5em; color: #1a237e; border-bottom: 3px solid #3f51b5; padding-bottom: 8px; margin: 0 0 20px; }}
h2 {{ font-size: 1.15em; color: #283593; border-left: 4px solid #5c6bc0; padding-left: 10px; margin: 24px 0 12px; }}
h3 {{ font-size: 1em; color: #37474f; margin: 16px 0 8px; }}
p {{ margin: 8px 0; }}
ul, ol {{ margin: 8px 0 8px 20px; }}
li {{ margin: 3px 0; }}
code {{ background: #f0f0f0; padding: 1px 5px; border-radius: 3px; font-family: "Courier New", monospace; font-size: 0.9em; }}
pre {{ background: #f4f4f4; border: 1px solid #ddd; border-radius: 6px; padding: 12px; overflow-x: auto; margin: 12px 0; }}
pre code {{ background: none; padding: 0; }}
table {{ border-collapse: collapse; width: 100%; margin: 16px 0; font-size: 0.9em; }}
th {{ background: #3f51b5; color: #fff; padding: 8px 12px; text-align: left; font-weight: 600; }}
td {{ padding: 7px 12px; border-bottom: 1px solid #e0e0e0; }}
tr:nth-child(even) td {{ background: #f5f7ff; }}
tr:hover td {{ background: #e8eaf6; }}
blockquote {{ border-left: 4px solid #90caf9; background: #e3f2fd; margin: 12px 0; padding: 10px 16px; border-radius: 0 6px 6px 0; color: #1565c0; }}
strong {{ color: #c62828; }}
a {{ color: #3f51b5; }}
hr {{ border: none; border-top: 1px solid #e0e0e0; margin: 20px 0; }}
.footer {{ font-size: 0.8em; color: #9e9e9e; margin-top: 24px; border-top: 1px solid #eee; padding-top: 12px; }}
</style>
</head>
<body>
<div class="container">
{body}
<p class="footer">Claude2605 自動報告系統 ｜ 來源：<code>{source_path}</code></p>
</div>
</body>
</html>
"""


def convert(md_path: Path, out_path: Path) -> None:
    text = md_path.read_text(encoding="utf-8")
    body = markdown.markdown(
        text,
        extensions=["tables", "fenced_code", "nl2br", "sane_lists"],
    )
    title = md_path.stem.replace("_", " ")
    html = HTML_TEMPLATE.format(title=title, body=body, source_path=md_path.resolve())
    out_path.write_text(html, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path, help="Source .md file")
    parser.add_argument("output", type=Path, nargs="?", help="Output .html path (default: same stem)")
    parser.add_argument("--print", action="store_true", dest="print_path",
                        help="Print output path to stdout (for shell capture)")
    args = parser.parse_args()

    if not args.input.exists():
        print(f"ERROR: {args.input} not found", file=sys.stderr)
        return 1

    out = args.output if args.output else args.input.with_suffix(".html")
    convert(args.input, out)

    if args.print_path:
        print(out)
    else:
        print(f"HTML_PATH={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
