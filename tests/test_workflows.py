"""Dry-run every saved workflow through tests/wf_harness.mjs with stubbed agents.

Catches runtime errors a syntax check cannot (bad .map on null, schema mistakes,
forbidden Date/Math.random calls, missing-arg handling). Fixture args per
workflow live in tests/workflow_args.json: {"<file>.js": [args, ...]}; each
workflow also runs once with no args and must return {started:false} cleanly.
"""
import json
import os
import shutil
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WF = os.path.join(ROOT, ".claude", "workflows")
NODE = shutil.which("node")


def run(path, args, seed=1):
    p = subprocess.run([NODE, os.path.join(ROOT, "tests", "wf_harness.mjs"), path, json.dumps(args), str(seed)],
                       capture_output=True, text=True, timeout=60)
    return json.loads(p.stdout.strip().splitlines()[-1])


@unittest.skipUnless(NODE and os.path.isdir(WF), "node or workflows missing")
class WorkflowDryRuns(unittest.TestCase):
    def fixtures(self):
        p = os.path.join(ROOT, "tests", "workflow_args.json")
        return json.load(open(p)) if os.path.exists(p) else {}

    def test_missing_args_are_rejected_cleanly(self):
        for f in sorted(os.listdir(WF)):
            if f.endswith(".js"):
                with self.subTest(workflow=f):
                    out = run(os.path.join(WF, f), None)
                    self.assertTrue(out["ok"], out.get("error"))
                    self.assertEqual(out["agents"], 0, "no agents should run without args")
                    self.assertIsInstance(out["result"], dict)
                    self.assertIs(out["result"].get("started"), False)

    def test_fixture_runs(self):
        fx = self.fixtures()
        for f in sorted(os.listdir(WF)):
            if not f.endswith(".js"):
                continue
            for i, args in enumerate(fx.get(f, [])):
                for seed in (1, 2, 3):
                    with self.subTest(workflow=f, case=i, seed=seed):
                        out = run(os.path.join(WF, f), args, seed)
                        self.assertTrue(out["ok"], out.get("error"))
                        self.assertGreater(out["agents"], 0)
                        self.assertIsInstance(out["result"], dict)


if __name__ == "__main__":
    unittest.main()
