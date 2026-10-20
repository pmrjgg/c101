"""Tests for the writing pack scripts: manuscript.py (project scaffolding) and prose_check.py (prose analysis).

Both are stdlib CLIs under .claude/skills/*/scripts/; they are exercised as subprocesses (exit codes included) in
temporary directories only.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # so `-m unittest tests.test_writing_scripts` finds stackenv
import stackenv  # noqa: E402,F401  (scrub leaked env vars before anything else, see tests/stackenv.py)
import importlib.util  # noqa: E402
import json  # noqa: E402
import re  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402
import unittest  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

MS = os.path.join(ROOT, ".claude", "skills", "manuscript-project", "scripts", "manuscript.py")
PC_DIR = os.path.join(ROOT, ".claude", "skills", "prose-style-analysis", "scripts")
PC = os.path.join(PC_DIR, "prose_check.py")
WORDLIST = os.path.join(PC_DIR, "wordlists", "en-US.json")


class Result:
    def __init__(self, proc):
        self.rc = proc.returncode
        self.out = proc.stdout
        self.err = proc.stderr
        try:
            self.data = json.loads(proc.stdout) if proc.stdout.strip() else None
        except ValueError:
            self.data = None


def run(script, *args):
    proc = subprocess.run([sys.executable, script] + [str(a) for a in args], capture_output=True, text=True,
                          encoding="utf-8", timeout=120)
    return Result(proc)


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def read(path):
    with open(path, encoding="utf-8", newline="") as fh:
        return fh.read()


def lineof(text, needle):
    """1-based line number of the first line containing needle."""
    for i, line in enumerate(text.split("\n"), 1):
        if needle in line:
            return i
    raise AssertionError("%r not in text" % needle)


class TempCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name

    def p(self, *parts):
        return os.path.join(self.tmp, *parts)

    def init(self, name="book", *extra):
        res = run(MS, "init", self.p(name), "--title", "Test Book", *extra)
        self.assertEqual(res.rc, 0, res.err)
        return self.p(name)

    def chapters(self, proj, sub="chapters"):
        return sorted(f for f in os.listdir(os.path.join(proj, sub)) if not f.startswith("."))


class ManuscriptTests(TempCase):
    def test_init_creates_layout_and_never_overwrites(self):
        proj = self.init("book", "--author", "A. Writer", "--pov", "third limited", "--target-words", "70000")
        for rel in ("manuscript.md", "outline.md", "style-sheet.md", "bible/characters.md", "bible/places.md",
                    "bible/timeline.md", "bible/glossary.md", "reviews", "notes"):
            self.assertTrue(os.path.exists(os.path.join(proj, rel)), rel)
        self.assertEqual(self.chapters(proj), ["001_chapter-1.md", "002_chapter-2.md", "003_chapter-3.md"])
        ch = read(os.path.join(proj, "chapters", "001_chapter-1.md"))
        self.assertIn("status: outline", ch)
        self.assertIn("# Chapter 1", ch)
        mpath = os.path.join(proj, "manuscript.md")
        text = read(mpath)
        self.assertIn("title: Test Book", text)
        self.assertIn("target_words: 70000", text)
        self.assertIn("<!-- chapters:start -->", text)
        # second init: nothing is created, nothing changes, everything is reported as skipped
        write(mpath, text + "\nMY PRECIOUS EDIT\n")
        write(os.path.join(proj, "chapters", "002_chapter-2.md"), "---\nstatus: draft\n---\n# Two\n\nKeep me.\n")
        res = run(MS, "init", proj, "--title", "Other")
        self.assertEqual(res.rc, 0, res.err)
        self.assertEqual(res.data["created"], [])
        self.assertIn("manuscript.md", res.data["skipped"])
        self.assertIn("chapters/002_chapter-2.md", res.data["skipped"])
        self.assertIn("MY PRECIOUS EDIT", read(mpath))
        self.assertIn("Keep me.", read(os.path.join(proj, "chapters", "002_chapter-2.md")))

    def test_init_start_zero_adds_prologue(self):
        proj = self.init("book", "--start", "0", "--chapters", "2")
        self.assertEqual(self.chapters(proj), ["000_prologue.md", "001_chapter-1.md", "002_chapter-2.md"])
        self.assertEqual(run(MS, "validate", proj).rc, 0)

    def test_init_does_not_duplicate_a_number_with_a_different_slug(self):
        proj = self.p("book")
        write(os.path.join(proj, "chapters", "001_the-storm.md"), "# The Storm\n\nText.\n")
        res = run(MS, "init", proj, "--title", "T", "--chapters", "2")
        self.assertEqual(res.rc, 0, res.err)
        self.assertIn("chapters/001_chapter-1.md", res.data["skipped"])
        self.assertEqual(self.chapters(proj), ["001_the-storm.md", "002_chapter-2.md"])

    def test_validate_fresh_project_is_clean(self):
        proj = self.init()
        res = run(MS, "validate", proj)
        self.assertEqual(res.rc, 0, res.out)
        self.assertTrue(res.data["ok"])
        self.assertEqual(res.data["errors"], [])
        self.assertEqual(res.data["warnings"], [])
        self.assertEqual(res.data["chapters"], 3)

    def test_validate_catches_duplicates_bad_names_and_gaps(self):
        proj = self.init()
        cdir = os.path.join(proj, "chapters")
        write(os.path.join(cdir, "001_duplicate.md"), "# Dup\n\nText.\n")
        write(os.path.join(cdir, "Bad Name.md"), "# Bad\n")
        write(os.path.join(cdir, "notes.txt"), "not a chapter")
        write(os.path.join(cdir, "005_no-heading.md"), "No heading here.\n")
        os.remove(os.path.join(cdir, "002_chapter-2.md"))
        os.makedirs(os.path.join(cdir, "reviews"))
        res = run(MS, "validate", proj)
        self.assertEqual(res.rc, 1, res.out)
        self.assertFalse(res.data["ok"])
        errors = {(e["code"], e["file"]) for e in res.data["errors"]}
        self.assertIn(("duplicate_number", "chapters/001_chapter-1.md"), errors)
        self.assertIn(("duplicate_number", "chapters/001_duplicate.md"), errors)
        self.assertIn(("bad_name", "chapters/Bad Name.md"), errors)
        warnings = {(w["code"], w["file"]) for w in res.data["warnings"]}
        self.assertIn(("missing_h1", "chapters/005_no-heading.md"), warnings)
        self.assertIn(("non_chapter_file", "chapters/notes.txt"), warnings)
        self.assertIn(("directory_in_chapter_dir", "chapters/reviews"), warnings)
        gaps = [w for w in res.data["warnings"] if w["code"] == "numbering_gap"]
        self.assertTrue(gaps and "2" in gaps[0]["message"])

    def test_validate_missing_manuscript_and_chapter_dir(self):
        proj = self.p("bare")
        os.makedirs(proj)
        res = run(MS, "validate", proj)
        self.assertEqual(res.rc, 1)
        codes = {e["code"] for e in res.data["errors"]}
        self.assertEqual(codes, {"missing_manuscript", "missing_chapter_dir"})

    def test_validate_reports_unparsable_front_matter(self):
        proj = self.init()
        write(os.path.join(proj, "manuscript.md"), "---\ntitle: ok\nnot a key value line\n---\n# T\n")
        res = run(MS, "validate", proj)
        self.assertEqual(res.rc, 1)
        self.assertIn("bad_front_matter", {e["code"] for e in res.data["errors"]})

    def test_index_reports_chapters_and_write_only_touches_marker_block(self):
        proj = self.init()
        write(os.path.join(proj, "chapters", "001_chapter-1.md"),
              "---\nstatus: draft\npov: Anna\n---\n# The Door\n\nOne two three four five.\n")
        mpath = os.path.join(proj, "manuscript.md")
        before = read(mpath)
        res = run(MS, "index", proj)
        self.assertEqual(res.rc, 0, res.err)
        first = res.data["chapters"][0]
        self.assertEqual((first["number"], first["slug"], first["title"], first["words"], first["status"], first["pov"]),
                         (1, "chapter-1", "The Door", 5, "draft", "Anna"))
        self.assertEqual(res.data["totals"]["chapters"], 3)
        self.assertEqual(res.data["totals"]["words"], 5)
        self.assertEqual(read(mpath), before, "index without --write must not touch manuscript.md")
        s, e = before.index("<!-- chapters:start -->"), before.index("<!-- chapters:end -->")
        write(mpath, before[:s] + "<!-- chapters:start -->\nSTALE LINE\n" + before[e:] + "\nTRAILER AFTER\n")
        edited = read(mpath)
        res = run(MS, "index", proj, "--write")
        self.assertEqual(res.rc, 0, res.err)
        self.assertTrue(res.data["changed"])
        after = read(mpath)
        s2, e2 = after.index("<!-- chapters:start -->"), after.index("<!-- chapters:end -->")
        self.assertEqual(after[:s2], edited[:edited.index("<!-- chapters:start -->")])
        self.assertEqual(after[e2:], edited[edited.index("<!-- chapters:end -->"):])
        block = after[s2:e2]
        self.assertNotIn("STALE LINE", block)
        self.assertIn("[The Door](chapters/001_chapter-1.md)", block)
        self.assertIn("5 words", block)
        self.assertIn("TRAILER AFTER", after)
        res = run(MS, "index", proj, "--write")
        self.assertFalse(res.data["changed"], "second write must be a no-op")
        self.assertEqual(read(mpath), after)

    def test_index_write_requires_markers(self):
        proj = self.init()
        write(os.path.join(proj, "manuscript.md"), "---\ntitle: T\n---\n# T\n")
        res = run(MS, "index", proj, "--write")
        self.assertEqual(res.rc, 2)
        self.assertEqual(read(os.path.join(proj, "manuscript.md")), "---\ntitle: T\n---\n# T\n")

    def test_stats_dialogue_ratio_and_totals(self):
        proj = self.init("book", "--chapters", "1")
        write(os.path.join(proj, "chapters", "001_chapter-1.md"),
              '---\nstatus: draft\n---\n# One\n\n"Come here now," she said. The sun rose. It was late.\n\n'
              '<!-- ignored comment words -->\n```\ncode block words\n```\nAnother paragraph here.\n')
        res = run(MS, "stats", proj)
        self.assertEqual(res.rc, 0, res.err)
        row = res.data["chapters"][0]
        self.assertEqual(row["words"], 14)
        self.assertEqual(row["dialogue_words"], 3)
        self.assertAlmostEqual(row["dialogue_ratio"], round(3 / 14.0, 4))
        self.assertEqual(row["paragraphs"], 2)
        self.assertEqual(row["sentences"], 4)
        self.assertEqual(res.data["totals"]["words"], 14)
        self.assertEqual(res.data["totals"]["reading_minutes"], round(14 / 250.0, 1))
        one = run(MS, "stats", proj, "--chapter", "001")
        self.assertEqual(one.rc, 0)
        self.assertEqual(run(MS, "stats", proj, "--chapter", "009").rc, 2)

    def test_new_appends_next_number(self):
        proj = self.init()
        res = run(MS, "new", proj, "--slug", "the-storm", "--title", "The Storm")
        self.assertEqual(res.rc, 0, res.err)
        self.assertEqual(res.data["number"], 4)
        self.assertEqual(res.data["shifted"], [])
        self.assertIn("004_the-storm.md", self.chapters(proj))
        self.assertIn("# The Storm", read(os.path.join(proj, "chapters", "004_the-storm.md")))

    def test_new_rejects_invalid_slug_and_existing_target(self):
        proj = self.init()
        self.assertEqual(run(MS, "new", proj, "--slug", "Bad Slug").rc, 2)
        self.assertEqual(run(MS, "new", proj, "--slug", "-leading").rc, 2)
        self.assertEqual(len(self.chapters(proj)), 3)

    def test_new_after_shifts_later_chapters_highest_first(self):
        proj = self.init()
        for n in (1, 2, 3):
            write(os.path.join(proj, "chapters", "%03d_chapter-%d.md" % (n, n)), "# Chapter %d\n\nMARKER-%d\n" % (n, n))
        res = run(MS, "new", proj, "--slug", "interlude", "--after", "1")
        self.assertEqual(res.rc, 0, res.err)
        self.assertEqual(res.data["number"], 2)
        self.assertEqual(res.data["created"], "chapters/002_interlude.md")
        self.assertEqual([s["from"] for s in res.data["shifted"]], ["chapters/003_chapter-3.md", "chapters/002_chapter-2.md"])
        self.assertEqual(self.chapters(proj), ["001_chapter-1.md", "002_interlude.md", "003_chapter-2.md", "004_chapter-3.md"])
        self.assertIn("MARKER-2", read(os.path.join(proj, "chapters", "003_chapter-2.md")))
        self.assertIn("MARKER-3", read(os.path.join(proj, "chapters", "004_chapter-3.md")))
        self.assertIn("MARKER-1", read(os.path.join(proj, "chapters", "001_chapter-1.md")))
        self.assertEqual(run(MS, "validate", proj).rc, 0)

    def test_renumber_dry_run_then_apply(self):
        proj = self.init()
        cdir = os.path.join(proj, "chapters")
        os.remove(os.path.join(cdir, "002_chapter-2.md"))
        write(os.path.join(cdir, "007_late.md"), "# Late\n\nMARKER-LATE\n")
        before = self.chapters(proj)
        res = run(MS, "renumber", proj)
        self.assertEqual(res.rc, 0, res.err)
        self.assertFalse(res.data["applied"])
        self.assertEqual([(m["from"], m["to"]) for m in res.data["mapping"]],
                         [("chapters/003_chapter-3.md", "chapters/002_chapter-3.md"), ("chapters/007_late.md", "chapters/003_late.md")])
        self.assertEqual(res.data["unchanged"], 1)
        self.assertEqual(self.chapters(proj), before, "dry run must not rename anything")
        res = run(MS, "renumber", proj, "--apply")
        self.assertEqual(res.rc, 0, res.err)
        self.assertTrue(res.data["applied"])
        self.assertEqual(self.chapters(proj), ["001_chapter-1.md", "002_chapter-3.md", "003_late.md"])
        self.assertIn("MARKER-LATE", read(os.path.join(cdir, "003_late.md")))
        self.assertEqual([f for f in os.listdir(cdir) if f.startswith(".renumber")], [])
        self.assertEqual(run(MS, "validate", proj).rc, 0)
        self.assertEqual(run(MS, "renumber", proj).data["mapping"], [])

    def test_renumber_swaps_without_collisions_and_resolves_duplicates(self):
        proj = self.init("book", "--chapters", "0")
        cdir = os.path.join(proj, "chapters")
        write(os.path.join(cdir, "003_a.md"), "# A\n")
        write(os.path.join(cdir, "003_b.md"), "# B\n")
        write(os.path.join(cdir, "004_c.md"), "# C\n")
        res = run(MS, "renumber", proj, "--apply")
        self.assertEqual(res.rc, 0, res.err)
        self.assertEqual(self.chapters(proj), ["001_a.md", "002_b.md", "003_c.md"])

    def test_concat_refuses_inside_chapter_dir(self):
        proj = self.init()
        target = os.path.join(proj, "chapters", "all.md")
        res = run(MS, "concat", proj, "--out", target)
        self.assertEqual(res.rc, 2)
        self.assertFalse(os.path.exists(target))
        res = run(MS, "concat", proj, "--out", os.path.join(proj, "chapters", "sub", "x.md"))
        self.assertEqual(res.rc, 2)
        self.assertFalse(os.path.exists(os.path.join(proj, "chapters", "sub")))
        self.assertEqual(run(MS, "concat", proj, "--out", os.path.join(proj, "manuscript.md")).rc, 2)

    def test_concat_orders_chapters_and_strips_front_matter(self):
        proj = self.init()
        for n in (1, 2, 3):
            write(os.path.join(proj, "chapters", "%03d_chapter-%d.md" % (n, n)),
                  "---\nstatus: draft\n---\n# Chapter %d\n\nBODY-%d\n" % (n, n))
        out = self.p("export", "full.md")
        res = run(MS, "concat", proj, "--out", out)
        self.assertEqual(res.rc, 0, res.err)
        text = read(out)
        self.assertNotIn("status:", text)
        self.assertLess(text.index("BODY-1"), text.index("BODY-2"))
        self.assertLess(text.index("BODY-2"), text.index("BODY-3"))
        self.assertIn("# Chapter 2", text)
        self.assertEqual(res.data["chapters"], 3)

    def test_custom_chapter_dir_and_pattern_are_honored(self):
        proj = self.p("custom")
        write(os.path.join(proj, "manuscript.md"),
              "---\ntitle: Custom\nchapter_dir: text\nchapter_pattern: '^ch(\\d+)-([a-z]+)\\.md$'\n---\n# Custom\n\n"
              "<!-- chapters:start -->\n<!-- chapters:end -->\n")
        write(os.path.join(proj, "text", "ch1-alpha.md"), "# Alpha\n\nOne two.\n")
        write(os.path.join(proj, "text", "ch2-beta.md"), "# Beta\n\nThree four five.\n")
        write(os.path.join(proj, "chapters", "001_ignored.md"), "# Not a chapter here\n")
        res = run(MS, "validate", proj)
        self.assertEqual(res.rc, 0, res.out)
        self.assertEqual(res.data["chapters"], 2)
        res = run(MS, "index", proj, "--write")
        self.assertEqual([c["file"] for c in res.data["chapters"]], ["text/ch1-alpha.md", "text/ch2-beta.md"])
        self.assertIn("(text/ch2-beta.md)", read(os.path.join(proj, "manuscript.md")))
        res = run(MS, "new", proj, "--slug", "gamma")
        self.assertEqual(res.rc, 0, res.err)
        self.assertEqual(res.data["created"], "text/ch3-gamma.md")
        res = run(MS, "new", proj, "--slug", "mid", "--after", "1")
        self.assertEqual(res.rc, 0, res.err)
        self.assertEqual(sorted(os.listdir(os.path.join(proj, "text"))),
                         ["ch1-alpha.md", "ch2-mid.md", "ch3-beta.md", "ch4-gamma.md"])

    def test_invalid_pattern_group_count_is_a_validate_error_and_a_usage_error_elsewhere(self):
        proj = self.init()
        write(os.path.join(proj, "manuscript.md"), "---\ntitle: T\nchapter_pattern: '^(\\d+)\\.md$'\n---\n# T\n")
        res = run(MS, "validate", proj)
        self.assertEqual(res.rc, 1)
        self.assertIn("bad_config", {e["code"] for e in res.data["errors"]})
        self.assertEqual(run(MS, "index", proj).rc, 2)

    def test_chapter_dir_cannot_escape_the_project(self):
        proj = self.init()
        write(os.path.join(proj, "manuscript.md"), "---\ntitle: T\nchapter_dir: ../elsewhere\n---\n# T\n")
        self.assertEqual(run(MS, "validate", proj).rc, 1)
        self.assertEqual(run(MS, "renumber", proj, "--apply").rc, 2)

    def test_front_matter_parser(self):
        spec = importlib.util.spec_from_file_location("manuscript_under_test", MS)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        meta, body, first = mod.parse_front_matter(
            '---\n# a comment\ntitle: "A: B"\nn: 42\nneg: -3\nok: true\ntags: [a, "b, c", 7]\nplain: some words # note\n'
            "pat: '^(\\d{3})_x$'\nempty:\n---\n# Body\n")
        self.assertEqual(meta["title"], "A: B")
        self.assertEqual((meta["n"], meta["neg"], meta["ok"]), (42, -3, True))
        self.assertEqual(meta["tags"], ["a", "b, c", 7])
        self.assertEqual(meta["plain"], "some words")
        self.assertEqual(meta["pat"], "^(\\d{3})_x$")
        self.assertEqual(meta["empty"], "")
        self.assertEqual(body, "# Body\n")
        self.assertEqual(first, 12)
        self.assertEqual(mod.parse_front_matter("# no front matter\n")[0], {})
        for bad in ("---\ntitle: x\n", "---\nkey value\n---\n", "---\na: 1\na: 2\n---\n", "---\n  nested: 1\n---\n", '---\na: "open\n---\n'):
            with self.assertRaises(mod.FrontMatterError, msg=bad):
                mod.parse_front_matter(bad)

    def test_every_subcommand_has_help(self):
        for sub in ("init", "validate", "index", "stats", "new", "renumber", "concat"):
            res = run(MS, sub, "--help")
            self.assertEqual(res.rc, 0, sub)
            self.assertIn("usage:", res.out)
        self.assertEqual(run(MS).rc, 2)
        self.assertEqual(run(MS, "frobnicate").rc, 2)


STYLE_SAMPLE = (
    "---\n"                                                                     # 1
    "title: Sample\n"                                                           # 2
    "---\n"                                                                     # 3
    "# Chapter One\n"                                                           # 4
    "\n"                                                                        # 5
    "<!-- she felt angry, a testament to nothing -->\n"                         # 6
    "Anna felt the cold. It was a testament to her patience.\n"                 # 7
    "\n"                                                                        # 8
    "## She felt like running\n"                                                # 9
    "\n"                                                                        # 10
    "She was afraid of the dark.\n"                                             # 11
    "\n"                                                                        # 12
    "```\n"                                                                     # 13
    "She felt sad in a code block.\n"                                           # 14
    "```\n"                                                                     # 15
    "\n"                                                                        # 16
    "He noticed the door. \"I felt angry,\" she said.\n"                        # 17
)


class ProseCheckTests(TempCase):
    def style(self, text, *extra):
        path = self.p("chapters", "001_chapter-1.md")
        write(path, text)
        res = run(PC, "style", path, *extra)
        self.assertEqual(res.rc, 0, res.err)
        return res.data["files"][0]

    def flags(self, row, check):
        return [(f["line"], f["match"].lower()) for f in row["flags"] if f["check"] == check]

    def test_wordlist_is_complete(self):
        with open(WORDLIST, encoding="utf-8") as fh:
            wl = json.load(fh)
        for key in ("filter_words", "weak_verb_patterns", "intensifiers", "cliches", "ai_tells", "emotion_words",
                    "said_bookisms", "tell_verbs", "british_to_us", "confused_words", "stopwords"):
            self.assertIn(key, wl)
        self.assertGreaterEqual(len(wl["cliches"]), 60)
        self.assertGreaterEqual(len(wl["ai_tells"]), 60)
        self.assertGreaterEqual(len(wl["emotion_words"]), 80)
        self.assertGreaterEqual(len(wl["british_to_us"]), 150)
        for needle in ("a testament to", "tapestry of", "delve into", "in the realm of", "a symphony of", "couldn't help but",
                       "sent shivers down", "the weight of", "palpable", "unspoken", "it's worth noting"):
            self.assertIn(needle, wl["ai_tells"])
        self.assertEqual(wl["british_to_us"]["colour"], "color")
        for pattern in wl["weak_verb_patterns"].values():
            re.compile(pattern)
        for item in wl["confused_words"]:
            re.compile(item["pattern"])

    def test_scripts_do_not_touch_the_network(self):
        for path in (MS, PC):
            src = read(path)
            for forbidden in ("import socket", "urllib", "http.client", "import requests", "import ssl", "ftplib", "smtplib", "webbrowser"):
                self.assertNotIn(forbidden, src, "%s mentions %s" % (os.path.basename(path), forbidden))

    def test_style_flags_with_original_line_numbers(self):
        row = self.style(STYLE_SAMPLE)
        self.assertEqual(self.flags(row, "filter_words"), [(7, "felt"), (17, "noticed")])
        self.assertEqual(self.flags(row, "ai_tells"), [(7, "a testament to")])
        self.assertEqual(self.flags(row, "tell_emotion"), [(11, "was afraid")])
        # nothing from front matter (1-3), heading (4, 9), comment (6) or the fenced block (13-15)
        for f in row["flags"]:
            self.assertNotIn(f["line"], (1, 2, 3, 4, 6, 9, 13, 14, 15), f)
        flag = [f for f in row["flags"] if f["check"] == "ai_tells"][0]
        self.assertEqual(flag["col"], STYLE_SAMPLE.split("\n")[6].index("a testament") + 1)
        self.assertLessEqual(len(flag["context"]), 120)
        self.assertEqual(row["words"], 26)

    def test_style_dialogue_is_not_flagged_for_narration_only_checks(self):
        row = self.style(STYLE_SAMPLE)
        self.assertNotIn((17, "felt"), self.flags(row, "filter_words"))
        self.assertNotIn((17, "felt angry"), self.flags(row, "tell_emotion"))

    def test_style_detects_ai_tells_in_curly_dialogue_and_multiline_paragraphs(self):
        text = "# T\n\nShe let out a breath she didn't know she was holding, and\nit sent shivers down her spine.\n\n“Delve into it,” he said.\n"
        row = self.style(text)
        tells = self.flags(row, "ai_tells")
        self.assertIn((3, "a breath she didn't know she was holding"), tells)
        self.assertIn((4, "sent shivers down"), tells)
        self.assertIn((6, "delve into"), tells)
        dialogue = [f for f in row["flags"] if f["check"] == "ai_tells" and f["line"] == 6][0]
        self.assertTrue(dialogue["in_dialogue"])
        self.assertEqual(dialogue["severity"], "low")

    def test_style_other_checks(self):
        text = (
            "# T\n\n"
            "He was very tired. She was running and he began to laugh.\n\n"                                      # 3
            "\"No,\" she growled quietly.\n\n"                                                                  # 5
            "The dark, cold, wet night fell like a stone, and the hush was as deep as a grave.\n\n"             # 7
            "She ran. She hid. She waited. She listened.\n\n"                                                   # 9
            "The stone was heavy and the stone sat on the heavy road.\n"                                        # 11
        )
        row = self.style(text)
        self.assertIn((3, "very"), self.flags(row, "intensifiers"))
        self.assertIn((3, "was running"), self.flags(row, "weak_verbs"))
        self.assertIn((3, "began to"), self.flags(row, "weak_verbs"))
        self.assertIn((5, "growled"), self.flags(row, "dialogue_tags"))
        self.assertIn((5, "growled quietly"), self.flags(row, "adverbs"))
        self.assertIn((7, "dark, cold, wet"), self.flags(row, "purple"))
        self.assertTrue(any(line == 9 for line, _m in self.flags(row, "repetition")))
        self.assertTrue(any(line == 11 for line, _m in self.flags(row, "repetition")))
        self.assertIn("sentence_mean_words", row["metrics"])
        self.assertEqual(row["metrics"]["tags"]["bookisms"], 1)

    def test_style_checks_selection_top_and_out(self):
        text = "# T\n\n" + "\n\n".join("She felt the rain on day %d." % i for i in range(30)) + "\n"
        path = self.p("c", "001_x.md")
        write(path, text)
        out = self.p("full.json")
        res = run(PC, "style", path, "--checks", "filter_words", "--top", "5", "--out", out)
        self.assertEqual(res.rc, 0, res.err)
        row = res.data["files"][0]
        self.assertEqual(list(row["counts"]), ["filter_words"])
        self.assertEqual(row["counts"]["filter_words"], 30)
        self.assertEqual(len(row["flags"]), 5)
        with open(out, encoding="utf-8") as fh:
            full = json.load(fh)
        self.assertEqual(len(full["files"][0]["flags"]), 30)
        self.assertEqual(run(PC, "style", path, "--checks", "nonsense").rc, 2)
        self.assertEqual(run(PC, "style", path, "--language", "xx-XX").rc, 2)
        self.assertEqual(run(PC, "style", self.p("missing.md")).rc, 2)

    def test_style_output_is_deterministic(self):
        path = self.p("c", "001_x.md")
        write(path, STYLE_SAMPLE)
        self.assertEqual(run(PC, "style", path).out, run(PC, "style", path).out)

    def test_style_accepts_project_directory_in_chapter_order(self):
        proj = self.init("book", "--chapters", "2")
        write(os.path.join(proj, "chapters", "002_chapter-2.md"), "# Two\n\nBeta saw the sky.\n")
        write(os.path.join(proj, "chapters", "001_chapter-1.md"), "# One\n\nAlpha saw the sea.\n")
        res = run(PC, "style", proj, "--checks", "filter_words")
        self.assertEqual(res.rc, 0, res.err)
        self.assertEqual([os.path.basename(r["file"]) for r in res.data["files"]], ["001_chapter-1.md", "002_chapter-2.md"])
        self.assertEqual(res.data["totals"]["counts"]["filter_words"], 2)

    def mechanics(self, text, *extra):
        path = self.p("chapters", "001_chapter-1.md")
        write(path, text)
        res = run(PC, "mechanics", path, *extra)
        self.assertEqual(res.rc, 0, res.err)
        return res.data["files"][0]

    def test_mechanics_flags(self):
        text = (
            "---\ntitle: m\n---\n"
            "# Heading with the the repeat\n\n"
            "\"I'm leaving.\" he said.\n\n"
            "The colour of the sky was grey, and she walked towards it.\n\n"
            "She  waited  here.\n\n"
            "He said \"hello\" and \u201cgoodbye\u201d to them.\n\n"
            "\"Wait,\" She said. It was the the end -- or so she thought...\n\n"
            "She counted 12 stars and 5 owls.\n"
        )
        row = self.mechanics(text)
        by = {}
        for f in row["flags"]:
            by.setdefault(f["check"], []).append((f["line"], f["match"].lower()))
        ln = lambda needle: lineof(text, needle)  # noqa: E731
        self.assertIn((ln("I'm leaving"), '." he'), by["dialogue_punct"])
        self.assertIn((ln("Wait,"), '," she'), by["dialogue_punct"])
        self.assertEqual(sorted(by["british_spelling"]), [(ln("colour"), "colour"), (ln("colour"), "grey"), (ln("colour"), "towards")])
        self.assertEqual(by["double_space"], [(ln("She  waited"), "  ")] * 2)
        self.assertTrue(by["quote_mix"])
        self.assertEqual(by["repeated_word"], [(ln("Wait,"), "the the")])
        self.assertEqual(by["dash"], [(ln("Wait,"), "--")])
        self.assertEqual([m for _l, m in by["number_style"]], ["12", "5"])
        self.assertNotIn(ln("# Heading"), [f["line"] for f in row["flags"]], "headings must be skipped")
        suggestions = {f["match"].lower(): f["note"] for f in row["flags"] if f["check"] == "british_spelling"}
        self.assertEqual(suggestions["colour"], "US: color")

    def test_mechanics_clean_text_and_options(self):
        text = "# T\n\n“I'm leaving,” he said. The color of the sky was gray.\n\nShe waited—then ran… quickly.\n"
        row = self.mechanics(text)
        self.assertEqual(row["flags"], [], row["flags"])
        row = self.mechanics("# T\n\nThe grey door and the colour red.\n", "--ignore", "grey")
        self.assertEqual([f["match"] for f in row["flags"]], ["colour"])
        row = self.mechanics("# T\n\nThe grey door.\n", "--checks", "double_space")
        self.assertEqual(row["flags"], [])

    def test_mechanics_unbalanced_quotes_and_continued_speech(self):
        row = self.mechanics("# T\n\nShe said \"it is late.\n\nNext line.\n")
        self.assertEqual([f["check"] for f in row["flags"]], ["unbalanced_quotes"])
        row = self.mechanics("# T\n\n\"First paragraph of a long speech,\n\n\"and the second, which ends here.\"\n")
        self.assertEqual(row["flags"], [])

    def test_mechanics_ellipsis_and_apostrophe_mix(self):
        row = self.mechanics("# T\n\nWait... what… it isn't (it’s) fine.\n")
        checks = sorted(set(f["check"] for f in row["flags"]))
        self.assertEqual(checks, ["ellipsis_style", "quote_mix"])

    def test_consistency_finds_name_variants_across_chapters(self):
        proj = self.init("book", "--chapters", "2")
        write(os.path.join(proj, "chapters", "001_chapter-1.md"),
              "# One\n\nKatherine opened the door. Katherine smiled at the guard.\n\nThe guard let Katherine pass.\n")
        write(os.path.join(proj, "chapters", "002_chapter-2.md"),
              "# Two\n\nKathryn crossed the yard.\n\nLater, Kathryn found the key.\n\nThe ice-cream melted. The ice cream was gone. "
              "Nobody saw icecream again. The Council met; the council voted.\n")
        write(os.path.join(proj, "bible", "characters.md"), "# Characters\n\n## Katherine Marsh\n\n- Role: lead\n\n## Jonas\n")
        write(os.path.join(proj, "chapters", "002_chapter-2.md"),
              read(os.path.join(proj, "chapters", "002_chapter-2.md")) + "\nJonus waved. Jonus left.\n")
        res = run(PC, "consistency", proj)
        self.assertEqual(res.rc, 0, res.err)
        groups = res.data["name_variants"]
        forms = [sorted(v["form"] for v in g["variants"]) for g in groups]
        self.assertIn(["Katherine", "Kathryn"], forms)
        group = groups[forms.index(["Katherine", "Kathryn"])]
        self.assertEqual(group["dominant"], "Katherine")
        self.assertFalse(group["likely_distinct_names"])
        self.assertTrue(group["variants"][0]["first"].endswith("001_chapter-1.md:3:1"))
        near = {(n["canonical"], n["variant"]) for n in res.data["bible_near_misses"]}
        self.assertIn(("Jonas", "Jonus"), near)
        hyph = res.data["hyphenation_variants"]
        self.assertTrue(any(h["forms"].get("hyphen") == "ice-cream" and h["forms"].get("open") == "ice cream"
                            and h["forms"].get("closed") == "icecream" for h in hyph), hyph)
        self.assertIn("council", [c["term"] for c in res.data["capitalization_variants"]])

    def test_consistency_needs_a_project(self):
        self.assertEqual(run(PC, "consistency", self.tmp).rc, 2)
        self.assertEqual(run(PC, "consistency", self.p("nope")).rc, 2)

    def test_readability_simple_versus_complex(self):
        simple = self.p("simple.md")
        write(simple, "The cat sat on the mat. The dog ran to the park. We had fun in the sun. I like to run and play.\n")
        hard = self.p("hard.md")
        write(hard, "The epistemological ramifications of institutional bureaucratization necessitate comprehensive "
                    "reconsideration of administrative methodologies, notwithstanding considerable organizational "
                    "resistance to transformational restructuring initiatives.\n")
        a = run(PC, "readability", simple).data["files"][0]
        b = run(PC, "readability", hard).data["files"][0]
        self.assertGreater(a["flesch_reading_ease"], 90)
        self.assertLess(a["fk_grade"], 3)
        self.assertLess(b["flesch_reading_ease"], 10)
        self.assertGreater(b["fk_grade"], 18)
        self.assertEqual(b["sentences"], 1)
        self.assertGreater(b["pct_long_words"], a["pct_long_words"])
        self.assertGreater(b["avg_syllables_per_word"], a["avg_syllables_per_word"])

    def test_readability_hardest_paragraphs_have_original_lines(self):
        easy = "The cat sat on the mat and the dog ran to the park to play in the sun with a ball."
        hard = ("Institutional bureaucratization necessitates comprehensive reconsideration of administrative methodologies "
                "notwithstanding considerable organizational resistance to transformational restructuring initiatives overall.")
        path = self.p("r.md")
        write(path, "---\ntitle: r\n---\n# T\n\n%s\n\n%s\n" % (easy, hard))
        res = run(PC, "readability", path, "--min-words", "10")
        rows = res.data["files"][0]["hardest_paragraphs"]
        self.assertEqual([r["line"] for r in rows], [8, 6])
        self.assertLess(rows[0]["flesch_reading_ease"], rows[1]["flesch_reading_ease"])

    def test_every_subcommand_has_help(self):
        for sub in ("style", "mechanics", "consistency", "readability"):
            res = run(PC, sub, "--help")
            self.assertEqual(res.rc, 0, sub)
            self.assertIn("usage:", res.out)
        self.assertEqual(run(PC).rc, 2)

    def test_wordlists_are_found_relative_to_a_copied_script_tree(self):
        # a user install copies .claude/skills/... elsewhere; the script must locate wordlists/ beside itself
        import shutil
        dest = self.p("home", ".claude", "stack", ".claude", "skills", "prose-style-analysis")
        shutil.copytree(os.path.dirname(PC_DIR), dest)
        sample = self.p("s.md")
        write(sample, "She felt it.\n")
        script = os.path.join(dest, "scripts", "prose_check.py")
        res = run(script, "style", sample, "--checks", "filter_words")
        self.assertEqual(res.rc, 0, res.err)
        self.assertEqual(res.data["totals"]["counts"]["filter_words"], 1)


if __name__ == "__main__":
    unittest.main()
