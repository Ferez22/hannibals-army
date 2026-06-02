"""Render LLM markdown output for different surfaces.

Two targets:
  - Telegram (parse_mode=HTML) — minimal tag set: b, i, u, s, code, pre, a
  - TUI Textual RichLog — use rich.markdown.Markdown (handled in the screen)

This module ships the markdown → Telegram HTML transformation. The TUI side
uses rich.markdown directly because RichLog accepts Renderable objects.
"""
from __future__ import annotations

import re


def markdown_to_telegram_html(text: str) -> str:
    """Convert common markdown idioms to Telegram-safe HTML.

    Supported:
      - `code` → <code>code</code>
      - ```multi-line code``` → <pre>code</pre>
      - **bold** → <b>bold</b>
      - *italic* / _italic_ → <i>italic</i>
      - ~~strike~~ → <s>strike</s>
      - # / ## / ### headers → <b>...</b>
      - [text](url) → <a href="url">text</a>
      - - / * bullet list → • bullet
      - blank lines preserved
    Escapes raw &/</> first so user-supplied LLM text can't inject HTML.
    """
    if not text:
        return ""

    # 1. HTML-escape everything
    out = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    # 2. Pull out fenced code blocks first (so they aren't mangled by other rules)
    code_blocks: list[str] = []

    def _stash_pre(m: re.Match) -> str:
        body = m.group(1).strip("\n")
        code_blocks.append(body)
        return f"\x00PRE{len(code_blocks) - 1}\x00"

    out = re.sub(r"```(?:\w+)?\n(.*?)```", _stash_pre, out, flags=re.DOTALL)

    # 3. Inline code (single backticks) — also stash
    inline_codes: list[str] = []

    def _stash_inline(m: re.Match) -> str:
        inline_codes.append(m.group(1))
        return f"\x00CODE{len(inline_codes) - 1}\x00"

    out = re.sub(r"`([^`\n]+)`", _stash_inline, out)

    # 4. Headers (# / ## / ###) on their own line → bold
    out = re.sub(r"(?m)^#{1,6}\s+(.+)$", r"<b>\1</b>", out)

    # 5. Bold: **text** or __text__
    out = re.sub(r"\*\*([^\*\n]+)\*\*", r"<b>\1</b>", out)
    out = re.sub(r"__([^_\n]+)__", r"<b>\1</b>", out)

    # 6. Strike: ~~text~~
    out = re.sub(r"~~([^~\n]+)~~", r"<s>\1</s>", out)

    # 7. Italic: *text* or _text_ (avoid bullet asterisks)
    #    require non-space first char inside
    out = re.sub(r"(?<![\w*])\*(?=\S)([^\*\n]+?)(?<=\S)\*(?![\w*])", r"<i>\1</i>", out)
    out = re.sub(r"(?<![\w_])_(?=\S)([^_\n]+?)(?<=\S)_(?![\w_])", r"<i>\1</i>", out)

    # 8. Links: [text](url)
    out = re.sub(
        r"\[([^\]\n]+)\]\(([^)\n\s]+)\)",
        lambda m: f'<a href="{m.group(2)}">{m.group(1)}</a>',
        out,
    )

    # 9. Bullet lines `- ` / `* ` / `+ ` → •
    out = re.sub(r"(?m)^\s*[-*+]\s+", "• ", out)

    # 10. Numbered lists stay as-is (`1. ` etc) — Telegram renders fine

    # 11. Restore inline code → <code>
    for i, c in enumerate(inline_codes):
        out = out.replace(f"\x00CODE{i}\x00", f"<code>{c}</code>")

    # 12. Restore code blocks → <pre>
    for i, c in enumerate(code_blocks):
        out = out.replace(f"\x00PRE{i}\x00", f"<pre>{c}</pre>")

    return out
