"""Markdown to the HTML subset Qt's rich text draws, cut to a budget.

Qt's own markdown support (md4c) gives no say over how code, tables or links look,
so tile previews are rendered here instead: GitHub-flavored blocks (fenced code,
tables, lists, task items, quotes, rules, headings as bold lines) and inline spans
(code, links, bold, italic, strike, bare URLs).

The cut happens while rendering, so it never splits a tag or leaves `**` showing:
whatever is open when the budget runs out is closed properly.
"""
import html
import re

# Colors are CSS strings; QML hands in its theme. These are fallbacks for tests.
DEFAULT_STYLE = {
    "mono": "monospace",
    "code_bg": "rgba(128,128,128,0.16)",
    "border": "rgba(128,128,128,0.45)",
    "link": "#8ab4f8",
    "muted": "#9a9aa0",
    "gap": 4,
}

FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})\s*([^`\s]*)")
HEADING = re.compile(r"^ {0,3}#{1,6}(?:\s+(.*?))?\s*$")
HEADING_TAIL = re.compile(r"\s+#+$")
HR = re.compile(r"^ {0,3}([-*_])(\s*\1){2,}\s*$")
SETEXT = re.compile(r"^ {0,3}(=+|-+)\s*$")
TABLE_RULE = re.compile(r"^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$")
QUOTE = re.compile(r"^ {0,3}> ?(.*)$")
LIST_ITEM = re.compile(r"^(\s*)([-*+]|\d{1,9}[.)])(\s+|$)(.*)$")
TASK = re.compile(r"^\[([ xX])\]\s+(.*)$", re.S)
# ASCII only, so a URL stops at CJK punctuation; trailing punctuation is not part of it.
URL = re.compile(r"https?://[A-Za-z0-9\-._~:/?#\[\]@!$&()*+,;=%]*[A-Za-z0-9/#=&%+@\-]")
ESCAPABLE = set("\\`*_{}[]()#+-.!|~<>\"'")


class Budget:
    """What is left to show: source lines (blank ones are free) and visible characters.
    Tables may run `table_rows` past the line budget, so a cut table still shows rows."""

    def __init__(self, lines, chars, table_rows=0):
        self.lines = lines
        self.chars = chars
        self.table_rows = table_rows
        self.cut = False
        # True when the cut already printed its "…" inline.
        self.marked = False

    def stop(self, marked=False):
        self.cut = True
        self.marked = self.marked or marked


def _attr(value):
    return html.escape(str(value), quote=True)


def _css_font(family):
    return "'" + str(family).replace("\\", "").replace("'", "") + "'"


# ---------------------------------------------------------------- blocks

def _is_table_start(lines, i):
    return ("|" in lines[i] and i + 1 < len(lines) and "-" in lines[i + 1]
            and TABLE_RULE.match(lines[i + 1]) is not None)


def _list_match(line):
    m = LIST_ITEM.match(line)
    if not m or HR.match(line):
        return None
    indent = len(m.group(1).expandtabs(4))
    marker = m.group(2)
    space = len(m.group(3))
    # Five or more spaces after the marker: the content starts one space in.
    offset = indent + len(marker) + (space if 1 <= space <= 4 else 1)
    return indent, marker, offset, m.group(4)


def _ordered(marker):
    return marker[0].isdigit()


def _starts_block(lines, i, in_paragraph=False):
    line = lines[i]
    if FENCE.match(line) or HEADING.match(line) or HR.match(line) or QUOTE.match(line):
        return True
    if _is_table_start(lines, i):
        return True
    item = _list_match(line)
    if item and item[3].strip():
        # Like GitHub: only a list starting at 1 may interrupt a paragraph.
        return not in_paragraph or not _ordered(item[1]) or item[1][:-1] == "1"
    return False


def _indent(line):
    return len(line) - len(line.lstrip(" \t"))


def _dedent(line, n):
    i = 0
    while i < n and i < len(line) and line[i] in " \t":
        i += 1
    return line[i:]


def split_cells(row):
    """Cells of a table row: split on `|` outside code spans, unless escaped."""
    row = row.strip()
    if row.startswith("|"):
        row = row[1:]
    if row.endswith("|") and not row.endswith("\\|"):
        row = row[:-1]
    cells, cur, tick, i = [], [], False, 0
    while i < len(row):
        c = row[i]
        if c == "\\" and i + 1 < len(row) and row[i + 1] == "|":
            cur.append("|")
            i += 2
            continue
        if c == "`":
            tick = not tick
        if c == "|" and not tick:
            cells.append("".join(cur).strip())
            cur = []
        else:
            cur.append(c)
        i += 1
    cells.append("".join(cur).strip())
    return cells


def parse(text):
    return parse_lines(text.replace("\r\n", "\n").replace("\r", "\n").split("\n"))


def parse_lines(lines):
    """Blocks as tuples: ("code", lines), ("heading", text), ("hr",), ("para", lines),
    ("quote", blocks), ("table", aligns, header, rows), ("list", ordered, items) with
    items as (marker, task or None, blocks)."""
    blocks, i, n = [], 0, len(lines)
    while i < n:
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        fence = FENCE.match(line)
        if fence:
            mark, indent = fence.group(1), _indent(line)
            body, i = [], i + 1
            while i < n:
                close = re.match(r"^ {0,3}(" + re.escape(mark[0]) + r"{" + str(len(mark)) + r",})\s*$", lines[i])
                if close:
                    i += 1
                    break
                body.append(_dedent(lines[i], indent))
                i += 1
            blocks.append(("code", body))
            continue
        heading = HEADING.match(line)
        if heading:
            blocks.append(("heading", HEADING_TAIL.sub("", heading.group(1) or "")))
            i += 1
            continue
        if HR.match(line):
            blocks.append(("hr",))
            i += 1
            continue
        if _is_table_start(lines, i):
            header = split_cells(line)
            aligns = []
            for cell in split_cells(lines[i + 1]):
                left, right = cell.startswith(":"), cell.endswith(":")
                aligns.append("center" if left and right else "right" if right else "left")
            rows, i = [], i + 2
            while i < n and lines[i].strip() and "|" in lines[i]:
                rows.append(split_cells(lines[i]))
                i += 1
            blocks.append(("table", aligns, header, rows))
            continue
        if QUOTE.match(line):
            inner = []
            while i < n and lines[i].strip():
                m = QUOTE.match(lines[i])
                if m:
                    inner.append(m.group(1))
                elif _starts_block(lines, i):
                    break
                else:
                    inner.append(lines[i])  # lazy continuation
                i += 1
            blocks.append(("quote", parse_lines(inner)))
            continue
        item = _list_match(line)
        if item:
            block, i = _parse_list(lines, i)
            blocks.append(block)
            continue
        para = [line.strip()]
        i += 1
        while i < n and lines[i].strip():
            if SETEXT.match(lines[i]):
                blocks.append(("heading", " ".join(para)))
                para = None
                i += 1
                break
            if _starts_block(lines, i, in_paragraph=True):
                break
            para.append(lines[i].strip())
            i += 1
        if para:
            blocks.append(("para", para))
    return blocks


def _parse_list(lines, i):
    n = len(lines)
    base, marker, offset, first = _list_match(lines[i])
    ordered = _ordered(marker)
    items, cur = [], None

    def start(marker, offset, text):
        return {"marker": marker, "offset": offset, "lines": [text]}

    cur = start(marker, offset, first)
    i += 1
    while i < n:
        line = lines[i]
        item = _list_match(line)
        if item and item[0] - base < 2:
            if _ordered(item[1]) != ordered:
                break
            items.append(cur)
            cur = start(item[1], item[2], item[3])
            i += 1
            continue
        if not line.strip():
            # A blank line continues the list only if more of it follows.
            j = i + 1
            while j < n and not lines[j].strip():
                j += 1
            if j >= n:
                break
            nxt = _list_match(lines[j])
            if _indent(lines[j]) > base or (nxt and nxt[0] - base < 2 and _ordered(nxt[1]) == ordered):
                cur["lines"].extend([""] * (j - i))
                i = j
                continue
            break
        if _indent(line) > base:
            cur["lines"].append(_dedent(line, min(_indent(line), cur["offset"])))
            i += 1
            continue
        # Lazy continuation of the item's paragraph.
        if cur["lines"][-1].strip() and not _starts_block(lines, i):
            cur["lines"].append(line.strip())
            i += 1
            continue
        break
    items.append(cur)
    out = []
    for it in items:
        task = None
        body = it["lines"]
        m = TASK.match(body[0]) if body else None
        if m:
            task = m.group(1) != " "
            body = [m.group(2)] + body[1:]
        out.append((it["marker"], task, parse_lines(body)))
    return ("list", ordered, out), i


# ---------------------------------------------------------------- inline

def _find_close(s, mark, start):
    """Index of the closing `mark` for an opener ending at `start`, or -1."""
    j = start
    while True:
        j = s.find(mark, j)
        if j < 0:
            return -1
        if j > start and not s[j - 1].isspace() and s[j - 1] != "\\":
            # `_` closes only at a word's end.
            if mark[0] != "_" or j + len(mark) >= len(s) or not s[j + len(mark)].isalnum():
                if len(mark) > 1 or s[j + 1:j + 2] != mark:
                    return j
        j += 1


def inline(s, budget, style):
    out, i, n = [], 0, len(s)

    def text(chunk):
        if budget.chars <= 0:
            return False
        if len(chunk) > budget.chars:
            out.append(html.escape(chunk[:budget.chars], quote=False) + "…")
            budget.chars = 0
            budget.stop(marked=True)
            return False
        out.append(html.escape(chunk, quote=False))
        budget.chars -= len(chunk)
        return True

    while i < n:
        if budget.chars <= 0:
            if not budget.cut:
                out.append("…")
                budget.stop(marked=True)
            break
        c = s[i]
        prev = s[i - 1] if i else " "
        if c == "\\" and i + 1 < n and s[i + 1] in ESCAPABLE:
            text(s[i + 1])
            i += 2
            continue
        if c == "`":
            run = len(s[i:]) - len(s[i:].lstrip("`"))
            close = s.find("`" * run, i + run)
            while close >= 0 and s[close + run:close + run + 1] == "`":
                close = s.find("`" * run, close + run + 1)
            if close < 0:
                text("`" * run)
                i += run
                continue
            code = s[i + run:close]
            if len(code) > 2 and code[0] == " " and code[-1] == " ":
                code = code[1:-1]
            shown = code if len(code) <= budget.chars else code[:budget.chars] + "…"
            budget.chars -= len(code)
            if budget.chars < 0:
                budget.chars = 0
                budget.stop(marked=True)
            out.append('<span style="font-family:%s; background-color:%s">&nbsp;%s&nbsp;</span>'
                       % (_attr(_css_font(style["mono"])), _attr(style["code_bg"]), html.escape(shown, quote=False)))
            i = close + run
            continue
        if c in "![" and (c == "[" or s[i + 1:i + 2] == "["):
            m = re.match(r"!?\[((?:\\.|[^\]\\])*)\]\(\s*<?([^\s)>]+)>?(?:\s+\"[^\"]*\")?\s*\)", s[i:])
            if m:
                label = m.group(1) or m.group(2)
                out.append('<a href="%s" style="color:%s">' % (_attr(m.group(2)), _attr(style["link"])))
                out.append(inline(("🖼 " if c == "!" else "") + label, budget, style))
                out.append("</a>")
                i += m.end()
                continue
        if c == "<":
            m = re.match(r"<(https?://[^\s>]+)>", s[i:])
            if m:
                out.append('<a href="%s" style="color:%s">' % (_attr(m.group(1)), _attr(style["link"])))
                text(m.group(1))
                out.append("</a>")
                i += m.end()
                continue
        if c == "h" and not prev.isalnum():
            m = URL.match(s, i)
            if m:
                out.append('<a href="%s" style="color:%s">' % (_attr(m.group(0)), _attr(style["link"])))
                text(m.group(0))
                out.append("</a>")
                i = m.end()
                continue
        matched = False
        for mark, tags in (("***", ("<b><i>", "</i></b>")), ("___", ("<b><i>", "</i></b>")),
                           ("**", ("<b>", "</b>")), ("__", ("<b>", "</b>")), ("~~", ("<s>", "</s>")),
                           ("*", ("<i>", "</i>")), ("_", ("<i>", "</i>"))):
            if not s.startswith(mark, i):
                continue
            after = s[i + len(mark):i + len(mark) + 1]
            if not after or after.isspace() or (mark[0] == "_" and prev.isalnum()):
                continue
            close = _find_close(s, mark, i + len(mark))
            if close < 0:
                continue
            out.append(tags[0] + inline(s[i + len(mark):close], budget, style) + tags[1])
            i = close + len(mark)
            matched = True
            break
        if matched:
            continue
        # Plain text up to the next character that could start a span.
        j = i + 1
        while j < n and s[j] not in "\\`![<h*_~":
            j += 1
        text(s[i:j])
        i = j
    return "".join(out)


# ---------------------------------------------------------------- render

def _p(body, top, extra=""):
    return '<p style="margin-top:%dpx; margin-bottom:0px%s">%s</p>' % (top, extra, body)


def _lines_html(lines, budget, style):
    """Lines of a paragraph, each costing one line of budget, joined by breaks
    (Claude Code prints the line breaks as written)."""
    parts = []
    for line in lines:
        if budget.lines <= 0 or budget.chars <= 0:
            budget.stop()
            break
        budget.lines -= 1
        parts.append(inline(line, budget, style))
        if budget.cut:
            break
    return "<br>".join(parts)


def render_blocks(blocks, budget, style, top=0):
    out = []
    gap = int(style["gap"])
    for block in blocks:
        if budget.cut:
            break
        if budget.lines <= 0 or budget.chars <= 0:
            budget.stop()
            break
        t = top if not out else gap
        kind = block[0]
        if kind == "para":
            out.append(_p(_lines_html(block[1], budget, style), t))
        elif kind == "heading":
            budget.lines -= 1
            out.append(_p("<b>" + inline(block[1], budget, style) + "</b>", t))
        elif kind == "hr":
            budget.lines -= 1
            out.append('<hr style="margin-top:%dpx">' % t)
        elif kind == "code":
            out.append(_code(block[1], budget, style, t))
        elif kind == "table":
            out.append(_table(block, budget, style, t))
        elif kind == "quote":
            inner = render_blocks(block[1], budget, style)
            out.append('<table cellspacing="0" cellpadding="0" style="margin-top:%dpx"><tr>'
                       '<td width="3" style="background-color:%s"></td>'
                       '<td style="padding-left:8px; color:%s">%s</td></tr></table>'
                       % (t, _attr(style["border"]), _attr(style["muted"]), inner))
        elif kind == "list":
            out.append(_list(block, budget, style, t))
    return "".join(out)


def _code(lines, budget, style, top):
    while lines and not lines[-1].strip():
        lines = lines[:-1]
    shown = []
    for line in lines:
        if budget.lines <= 0 or budget.chars <= 0:
            shown.append("…")
            budget.stop(marked=True)
            break
        budget.lines -= 1
        if len(line) > budget.chars:
            line = line[:budget.chars] + "…"
            budget.chars = 0
            budget.stop(marked=True)
            shown.append(line)
            break
        budget.chars -= len(line)
        shown.append(line)
    body = html.escape("\n".join(shown), quote=False) or "&nbsp;"
    return ('<table width="100%%" cellspacing="0" cellpadding="6" style="margin-top:%dpx; background-color:%s">'
            '<tr><td><p style="margin:0px; white-space:pre-wrap; font-family:%s">%s</p></td></tr></table>'
            % (top, _attr(style["code_bg"]), _attr(_css_font(style["mono"])), body))


def _table(block, budget, style, top):
    _, aligns, header, rows = block
    width = len(header)
    # A table started near the end of the budget still shows a few rows.
    room = max(0, budget.lines - 1) + budget.table_rows
    budget.lines -= 1

    def row(cells, tag):
        out = []
        for k in range(width):
            cell = cells[k] if k < len(cells) else ""
            align = aligns[k] if k < len(aligns) else "left"
            out.append('<%s align="%s">%s</%s>' % (tag, align, inline(cell, budget, style), tag))
        return "<tr>" + "".join(out) + "</tr>"

    body = [row(header, "th")]
    for k, cells in enumerate(rows):
        if budget.chars <= 0 or budget.cut:
            break
        if k >= room:
            body.append('<tr><td colspan="%d">…</td></tr>' % width)
            budget.stop(marked=True)
            break
        body.append(row(cells, "td"))
        budget.lines -= 1
    budget.lines = max(0, budget.lines)
    return ('<table cellspacing="0" cellpadding="3" border="1" style="margin-top:%dpx; border-color:%s; '
            'border-style:solid; border-collapse:collapse">%s</table>' % (top, _attr(style["border"]), "".join(body)))


def _list(block, budget, style, top):
    _, ordered, items = block
    rows = []
    for marker, task, body in items:
        if budget.cut or budget.lines <= 0 or budget.chars <= 0:
            budget.stop()
            break
        if task is not None:
            mark = "☑" if task else "☐"
        elif ordered:
            mark = html.escape(marker, quote=False)
        else:
            mark = "•"
        content = render_blocks(body, budget, style) if body else "&nbsp;"
        rows.append('<tr><td style="padding-right:6px">%s</td><td>%s</td></tr>' % (mark, content))
    return '<table cellspacing="0" cellpadding="0" style="margin-top:%dpx">%s</table>' % (top, "".join(rows))


def to_html(text, max_lines, max_chars, table_rows=0, style=None):
    """`text` as Qt rich text, cut after `max_lines` source lines or `max_chars`
    visible characters, with a muted "…" line when the cut fell between blocks."""
    st = dict(DEFAULT_STYLE)
    st.update({k: v for k, v in (style or {}).items() if k in DEFAULT_STYLE and v not in (None, "")})
    budget = Budget(max_lines, max_chars, table_rows)
    out = render_blocks(parse(text.strip()), budget, st)
    if budget.cut and not budget.marked:
        out += _p("…", int(st["gap"]), "; color:%s" % _attr(st["muted"]))
    return out
