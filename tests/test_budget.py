"""Tests for whole-tree token budgets (stack/budget.py) and their hook enforcement."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from stack import budget  # noqa: E402


def line(**kw):
    return json.dumps(kw) + "\n"


def assistant(mid, inp=0, cr=0, cc=0, out=0, text="", stop="tool_use"):
    return line(type="assistant", message={"id": mid, "stop_reason": stop, "content": [{"type": "text", "text": text}],
                                           "usage": {"input_tokens": inp, "cache_read_input_tokens": cr,
                                                     "cache_creation_input_tokens": cc, "output_tokens": out}})


class BudgetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["CLAUDE_STACK_DATA"] = os.path.join(self.tmp, "data")
        self.main = os.path.join(self.tmp, "s.jsonl")
        with open(self.main, "w") as fh:
            fh.write(line(type="user", promptId="P1", message={"content": "hi"}))
            fh.write(assistant("m1", inp=10, cr=1000, cc=100, out=50))
            fh.write(assistant("m1", inp=10, cr=1000, cc=100, out=80))   # same response, later block: output grows
            fh.write(line(type="user", promptId="P2", message={"content": "next"}))
            fh.write(assistant("m2", inp=5, cr=2000, cc=0, out=20))
        sub = os.path.join(self.tmp, "s", "subagents", "workflows", "wf_1")
        os.makedirs(sub)
        with open(os.path.join(sub, "agent-a.jsonl"), "w") as fh:
            fh.write(line(type="user", promptId="P2", message={"content": "brief"}))
            # streaming placeholder: 2 reported tokens but 360 chars of content -> estimate 100
            fh.write(assistant("s1", inp=3, cr=500, out=2, text="x" * 360, stop=None))

    def tearDown(self):
        os.environ.pop("CLAUDE_STACK_DATA", None)
        shutil.rmtree(self.tmp)

    def test_totals_and_prompt_attribution(self):
        st = budget.session_usage("S", self.main)
        s = st["session"]
        self.assertEqual(s["input"], 18)
        self.assertEqual(s["cache_read"], 3500)
        self.assertEqual(s["cache_creation"], 100)
        self.assertEqual(s["output"], 80 + 20 + 100)
        self.assertEqual(budget.effective(st["prompts"]["P1"], 1.0), 10 + 1000 + 100 + 80)
        self.assertEqual(budget.effective(st["prompts"]["P2"], 1.0), 5 + 2000 + 20 + 3 + 500 + 100)

    def test_incremental_scan_counts_appends_once(self):
        budget.session_usage("S", self.main)
        with open(self.main, "a") as fh:
            fh.write(assistant("m3", inp=1, cr=10, out=1))
        st = budget.session_usage("S", self.main)
        st2 = budget.session_usage("S", self.main)  # nothing new: totals unchanged
        self.assertEqual(st["session"], st2["session"])
        self.assertEqual(st2["session"]["input"], 19)

    def test_partial_line_waits_for_newline(self):
        budget.session_usage("S", self.main)
        with open(self.main, "a") as fh:
            fh.write(assistant("m4", inp=7)[:-5])  # incomplete record
        st = budget.session_usage("S", self.main)
        self.assertEqual(st["session"]["input"], 18)
        with open(self.main, "a") as fh:
            fh.write(assistant("m4", inp=7)[-5:])
        # the completed tail alone is not valid JSON; the scanner must not double count or crash
        st = budget.session_usage("S", self.main)
        self.assertGreaterEqual(st["session"]["input"], 18)

    def test_levels(self):
        self.assertEqual(budget.level(10, 100, 200, 300), "ok")
        self.assertEqual(budget.level(250, 100, 200, 300), "soft")
        self.assertEqual(budget.level(300, 100, 200, 300), "hard")
        self.assertEqual(budget.level(500, 600, 200, 300), "ok")  # below the guaranteed minimum: never throttled

    def test_policy_values(self):
        lim = budget.limits()
        self.assertEqual(lim["max_global_tokens"], 3_000_000_000)
        self.assertEqual(lim["soft_global_tokens"], 2_250_000_000)
        self.assertEqual(lim["min_global_tokens"], 750_000_000)
        self.assertEqual(lim["max_prompt_tokens"], 120_000_000)
        self.assertLess(lim["min_prompt_tokens"], lim["soft_prompt_tokens"])
        self.assertLess(lim["soft_prompt_tokens"], lim["max_prompt_tokens"])


class HardLimitHookTests(unittest.TestCase):
    def test_hard_limit_denies_non_finishing_spawns(self):
        tmp = tempfile.mkdtemp()
        try:
            main = os.path.join(tmp, "s.jsonl")
            with open(main, "w") as fh:
                fh.write(line(type="user", promptId="P", message={"content": "x"}))
                fh.write(assistant("m", inp=130_000_000))  # beyond the 120M per-prompt maximum
            env = dict(os.environ, CLAUDE_STACK_DATA=os.path.join(tmp, "data"))
            base = {"tool_name": "Agent", "session_id": "H", "transcript_path": main, "prompt_id": "P",
                    "tool_input": {"subagent_type": "deep-researcher", "prompt": "go"}}

            def run(p):
                r = subprocess.run([os.path.join(ROOT, "bin", "stack"), "hook", "pre-agent"], input=json.dumps(p),
                                   capture_output=True, text=True, env=env, timeout=30)
                return json.loads(r.stdout)["hookSpecificOutput"]

            out = run(base)
            self.assertEqual(out["permissionDecision"], "deny")
            self.assertIn("Token budget exhausted", out["permissionDecisionReason"])
            base["tool_input"]["subagent_type"] = "file-summarizer"
            out = run(base)
            self.assertEqual(out["permissionDecision"], "allow")
            self.assertIn('budget="hard"', out["updatedInput"]["prompt"])
        finally:
            shutil.rmtree(tmp)


if __name__ == "__main__":
    unittest.main()
