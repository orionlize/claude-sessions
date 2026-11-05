import html.parser
import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import mdhtml  # noqa: E402

spec = importlib.util.spec_from_file_location("preview_module", ROOT / "scripts" / "preview.py")
preview = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preview)

VOID = {"br", "hr"}


class Balance(html.parser.HTMLParser):
    """Fails on a tag closed out of order or left open."""

    def __init__(self):
        super().__init__()
        self.stack = []

    def handle_starttag(self, tag, attrs):
        if tag not in VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        assert self.stack and self.stack[-1] == tag, (tag, self.stack)
        self.stack.pop()


def render(text, lines=40, chars=2000, rows=6):
    out = mdhtml.to_html(text, lines, chars, rows)
    checker = Balance()
    checker.feed(out)
    checker.close()
    assert not checker.stack, checker.stack
    return out


def visible(out):
    class Text(html.parser.HTMLParser):
        def __init__(self):
            super().__init__()
            self.parts = []

        def handle_data(self, data):
            self.parts.append(data)

    t = Text()
    t.feed(out)
    return "".join(t.parts)


class Blocks(unittest.TestCase):
    def test_comment_in_code_stays_code(self):
        out = render("Run:\n```bash\n# install deps\nnpm i | grep x\n---\n```\nDone")
        self.assertNotIn("<b>", out)
        self.assertIn("# install deps\nnpm i | grep x\n---", out)
        self.assertNotIn("<th", out)
        self.assertIn("Done", out)

    def test_tilde_fence_and_longer_fence(self):
        out = render("~~~\n```\ninside\n~~~\nafter")
        self.assertIn("```\ninside", out)
        self.assertIn(">after</p>", out)

    def test_unclosed_fence_ends_at_text_end(self):
        out = render("```py\nx = 1\n")
        self.assertIn("x = 1", out)

    def test_heading_becomes_bold_line(self):
        out = render("## Summary ##\ntext")
        self.assertIn("<b>Summary</b>", out)
        self.assertNotIn("##", out)

    def test_setext_heading(self):
        self.assertIn("<b>Title</b>", render("Title\n====="))

    def test_table_may_interrupt_paragraph(self):
        out = render("Results:\n| a | b |\n|---|--:|\n| 1 | 2 |")
        self.assertIn("<th align=\"left\">a</th>", out)
        self.assertIn("<td align=\"right\">2</td>", out)

    def test_table_cell_pipe_in_code_or_escaped(self):
        self.assertEqual(mdhtml.split_cells("| `a|b` | c\\|d |"), ["`a|b`", "c|d"])

    def test_ordered_list_keeps_numbers_across_code(self):
        out = render("1. one\n\n```\ncode\n```\n\n2. two")
        self.assertIn(">1.</td>", out)
        self.assertIn(">2.</td>", out)

    def test_nested_list_and_tasks(self):
        out = render("1. top\n   - inner\n   - [x] done\n   - [ ] todo")
        self.assertEqual(out.count("<table"), 2)
        self.assertIn("☑", out)
        self.assertIn("☐", out)

    def test_indented_code_in_list_item(self):
        out = render("1. Install:\n   ```bash\n   # deps\n   npm i\n   ```\n2. Run")
        self.assertIn("# deps\nnpm i", out)
        self.assertIn(">2.</td>", out)

    def test_quote_and_rule(self):
        out = render("> note\n\n---\nend")
        self.assertIn("note", out)
        self.assertIn("<hr", out)

    def test_html_is_escaped(self):
        out = render("<script>x</script> & `<b>`")
        self.assertNotIn("<script>", out)
        self.assertIn("&lt;script&gt;", out)
        self.assertIn("&lt;b&gt;", out)


class Inline(unittest.TestCase):
    def test_spans(self):
        out = render("**bold** *it* ~~gone~~ `code` [doc](https://x.io/a)")
        for part in ("<b>bold</b>", "<i>it</i>", "<s>gone</s>", "code&nbsp;</span>", 'href="https://x.io/a"'):
            self.assertIn(part, out)

    def test_not_emphasis(self):
        out = render("snake_case_name and 2 * 3 * 4 and a**b")
        self.assertNotIn("<i>", out)
        self.assertNotIn("<b>", out)

    def test_bare_url_stops_at_punctuation(self):
        out = render("见 https://a.com/x。 (https://b.com/y).")
        self.assertIn('href="https://a.com/x"', out)
        self.assertIn('href="https://b.com/y"', out)

    def test_escapes(self):
        self.assertNotIn("<b>", render("\\*\\*not bold\\*\\*"))


class Budget(unittest.TestCase):
    def test_char_cut_closes_open_spans(self):
        out = render("这是**很重要的一段" + "字" * 300 + "**后面", chars=50)
        self.assertIn("…</b>", out)
        self.assertNotIn("**", out)
        self.assertNotIn("后面", out)
        self.assertLessEqual(len(visible(out)), 52)

    def test_char_cut_inside_code_span(self):
        out = render("`" + "x" * 100 + "`", chars=10)
        self.assertIn("x" * 10 + "…", out)

    def test_line_cut_adds_ellipsis_line(self):
        out = render("\n".join("line %d" % i for i in range(30)), lines=5)
        self.assertIn("line 4", out)
        self.assertNotIn("line 5", out)
        self.assertTrue(out.endswith("…</p>"))

    def test_exact_fit_has_no_ellipsis(self):
        self.assertNotIn("…", render("a\nb\nc", lines=3))

    def test_code_cut_by_lines(self):
        out = render("```\n" + "\n".join(str(i) for i in range(20)) + "\n```", lines=4)
        self.assertIn("0\n1\n2\n3\n…", out)

    def test_table_runs_past_line_budget(self):
        rows = "\n".join("| r%d | v |" % i for i in range(20))
        out = render("x\n| a | b |\n|---|---|\n" + rows, lines=3, rows=4)
        # One line left after x and the header: that row plus four more.
        self.assertIn("r4", out)
        self.assertNotIn("r5", out)
        self.assertIn('colspan="2">…', out)


class Preview(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.transcript = os.path.join(self.tmp.name, "t.jsonl")
        with open(self.transcript, "w") as f:
            for entry in (
                {"type": "user", "message": {"content": "hi"}},
                {"type": "assistant", "message": {"content": [{"type": "text", "text": "## Done\n`x`"}]}},
            ):
                f.write(json.dumps(entry) + "\n")

    def run_preview(self, style="{}"):
        env = dict(os.environ, XDG_RUNTIME_DIR=self.tmp.name)
        args = json.dumps([{"id": "s1", "transcript": self.transcript}])
        out = subprocess.run([sys.executable, "-S", str(ROOT / "scripts" / "preview.py"), args, style],
                             capture_output=True, text=True, env=env, check=True).stdout
        return json.loads(out)["s1"]

    def test_assistant_html_and_cached_rev(self):
        first = self.run_preview()
        kinds = [i["kind"] for i in first["items"]]
        self.assertEqual(kinds, ["user", "assistant"])
        self.assertIn("<b>Done</b>", first["items"][1]["html"])
        self.assertEqual(self.run_preview()["rev"], first["rev"])
        self.assertNotEqual(self.run_preview('{"link": "#fff"}')["rev"], first["rev"])

    def test_rev_moves_when_transcript_grows(self):
        first = self.run_preview()
        with open(self.transcript, "a") as f:
            f.write(json.dumps({"type": "user", "message": {"content": "more"}}) + "\n")
        second = self.run_preview()
        self.assertNotEqual(second["rev"], first["rev"])
        self.assertEqual(second["items"][-1]["text"], "more")


if __name__ == "__main__":
    unittest.main()
