"""Tests for the hook entry points (depth guard, budgets) and the env-file parser."""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from stack import envfile, hooks  # noqa: E402


def run_hook(name, payload, env=None):
    e = dict(os.environ)
    e.update(env or {})
    p = subprocess.run([os.path.join(ROOT, "bin", "stack"), "hook", name], input=json.dumps(payload),
                       capture_output=True, text=True, env=e, timeout=30)
    return p.returncode, (json.loads(p.stdout) if p.stdout.strip() else None), p.stderr


class DepthGuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.env = {"CLAUDE_STACK_DATA": os.path.join(self.tmp, "data"), "CLAUDE_STACK_MAX_DEPTH": "8"}
        # a session with one subagent at native spawnDepth 3
        self.transcript = os.path.join(self.tmp, "s.jsonl")
        open(self.transcript, "w").close()
        sub = os.path.join(self.tmp, "s", "subagents", "workflows", "wf_x")
        os.makedirs(sub)
        with open(os.path.join(sub, "agent-deep.meta.json"), "w") as fh:
            json.dump({"agentType": "orchestrator", "spawnDepth": 8}, fh)
        with open(os.path.join(sub, "agent-mid.meta.json"), "w") as fh:
            json.dump({"agentType": "planner", "spawnDepth": 3}, fh)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def payload(self, agent_id=None, prompt="do it"):
        p = {"tool_name": "Agent", "session_id": "S", "transcript_path": self.transcript,
             "tool_input": {"subagent_type": "tester", "prompt": prompt, "description": "t"}}
        if agent_id:
            p.update(agent_id=agent_id, agent_type="planner")
        return p

    def test_main_thread_spawn_gets_depth_1_header(self):
        rc, out, _ = run_hook("pre-agent", self.payload(), self.env)
        self.assertEqual(rc, 0)
        hso = out["hookSpecificOutput"]
        self.assertEqual(hso["permissionDecision"], "allow")
        self.assertTrue(hso["updatedInput"]["prompt"].startswith('<stack-context depth="1" max_depth="8"'))
        self.assertEqual(hso["updatedInput"]["subagent_type"], "tester")
        self.assertEqual(hso["updatedInput"]["description"], "t")

    def test_nested_depth_from_meta(self):
        rc, out, _ = run_hook("pre-agent", self.payload("mid"), self.env)
        self.assertIn('depth="4"', out["hookSpecificOutput"]["updatedInput"]["prompt"])
        self.assertIn('remaining_depth="4"', out["hookSpecificOutput"]["updatedInput"]["prompt"])

    def test_denies_beyond_max_depth(self):
        rc, out, _ = run_hook("pre-agent", self.payload("deep"), self.env)
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn("depth limit", out["hookSpecificOutput"]["permissionDecisionReason"])

    def test_spawn_rules_restrict_leaf_callers(self):
        p = self.payload("mid")
        p["agent_type"] = "web-scraper"
        p["tool_input"]["subagent_type"] = "orchestrator"
        rc, out, _ = run_hook("pre-agent", p, self.env)
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn("Spawn policy", out["hookSpecificOutput"]["permissionDecisionReason"])
        p["tool_input"]["subagent_type"] = "file-summarizer"
        rc, out, _ = run_hook("pre-agent", p, self.env)
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "allow")

    def test_orchestrators_not_started_deep(self):
        sub = os.path.join(self.tmp, "s", "subagents")
        with open(os.path.join(sub, "agent-d6.meta.json"), "w") as fh:
            json.dump({"agentType": "planner", "spawnDepth": 6}, fh)
        p = self.payload("d6")
        p["tool_input"]["subagent_type"] = "mediator"
        rc, out, _ = run_hook("pre-agent", p, self.env)
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")
        p["tool_input"]["subagent_type"] = "tester"
        rc, out, _ = run_hook("pre-agent", p, self.env)
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "allow")

    def test_subagent_stop_records_effort(self):
        payload = {"session_id": "S2", "agent_id": "x1", "agent_type": "rust-expert",
                   "effort": {"level": "xhigh"}, "transcript_path": "/nonexistent/s.jsonl"}
        rc, out, _ = run_hook("subagent-stop", payload, self.env)
        self.assertEqual(rc, 0)
        lines = open(os.path.join(self.env["CLAUDE_STACK_DATA"], "stops", "S2.jsonl")).read().splitlines()
        ev = json.loads(lines[-1])
        self.assertEqual((ev["agent_id"], ev["effort"]), ("x1", "xhigh"))

    def test_header_not_duplicated(self):
        rc, out, _ = run_hook("pre-agent", self.payload(prompt='<stack-context depth="1"/>\nx'), self.env)
        self.assertIsNone(out)

    def test_ignores_other_tools(self):
        p = self.payload()
        p["tool_name"] = "Bash"
        rc, out, _ = run_hook("pre-agent", p, self.env)
        self.assertEqual(rc, 0)
        self.assertIsNone(out)

    def test_fail_open_on_garbage(self):
        p = subprocess.run([os.path.join(ROOT, "bin", "stack"), "hook", "pre-agent"], input="not json",
                           capture_output=True, text=True, env=dict(os.environ, **self.env))
        self.assertEqual(p.returncode, 0)


class ModelSwitchTests(unittest.TestCase):
    def run_switch(self, to, main=None):
        env = dict(os.environ)
        env.pop("CLAUDE_STACK_MAIN_AGENT", None)
        env.pop("CLAUDE_STACK_ALLOW_MODEL_SWITCH", None)
        if main:
            env["CLAUDE_STACK_MAIN_AGENT"] = main
        return subprocess.run([os.path.join(ROOT, "bin", "stack"), "hook", "model-switch"],
                              input=json.dumps({"to_model": to}), capture_output=True, text=True, env=env).returncode

    def test_only_tier_models(self):
        self.assertEqual(self.run_switch("claude-sonnet-5-5"), 0)
        self.assertEqual(self.run_switch("claude-fable-5-1"), 2)

    def test_main_thread_pinned(self):
        self.assertEqual(self.run_switch("claude-opus-5-5", "delegator"), 0)
        self.assertEqual(self.run_switch("claude-haiku-5-5", "delegator"), 2)


class EnvFileTests(unittest.TestCase):
    def test_parse_rules(self):
        tmp = tempfile.mkdtemp()
        try:
            path = os.path.join(tmp, "e.env")
            with open(path, "w") as fh:
                fh.write('# c\nexport A=1\nB="two words # kept"\nC=three   # comment\nD=\n'
                         'bad-key=x\nE=hash#inside\nF=\'single\'\n')
            d = envfile.parse(path)
            self.assertEqual(d["A"], "1")
            self.assertEqual(d["B"], "two words # kept")
            self.assertEqual(d["C"], "three")
            self.assertEqual(d["D"], "")
            self.assertNotIn("bad-key", d)
            self.assertEqual(d["E"], "hash#inside")
            self.assertEqual(d["F"], "single")
        finally:
            shutil.rmtree(tmp)

    def test_bash_launcher_matches_python_parser(self):
        tmp = tempfile.mkdtemp()
        try:
            path = os.path.join(tmp, "e.env")
            with open(path, "w") as fh:
                fh.write('A=1\nB="two words # kept"\nC=three   # comment\nE=hash#inside\n')
            out = subprocess.run([os.path.join(ROOT, "bin", "mcp-run"), "/usr/bin/env"], capture_output=True,
                                 text=True, env={"CLAUDE_STACK_ENV": path, "PATH": "/usr/bin:/bin"}).stdout
            got = dict(l.split("=", 1) for l in out.splitlines() if "=" in l)
            want = envfile.parse(path)
            for k in ("A", "B", "C", "E"):
                self.assertEqual(got[k], want[k], k)
        finally:
            shutil.rmtree(tmp)

    def test_headers_helper_matches_python_parser(self):
        # bin/mcp-headers: a bare key without '=' is ignored and the last assignment wins, as in envfile.
        tmp = tempfile.mkdtemp()
        try:
            path = os.path.join(tmp, "e.env")
            with open(path, "w") as fh:
                fh.write('EXA_API_KEY\nEXA_API_KEY=first\nEXA_API_KEY=second   # comment\n'
                         'export JINA_API_KEY="j k"\nSPIDER_API_KEY=\n# CONTEXT7_API_KEY=commented\n')
            want = envfile.parse(path)

            def header(service):
                out = subprocess.run([os.path.join(ROOT, "bin", "mcp-headers"), service], capture_output=True,
                                     text=True, env={"CLAUDE_STACK_ENV": path, "PATH": "/usr/bin:/bin"}).stdout
                return json.loads(out)

            self.assertEqual(want["EXA_API_KEY"], "second")
            self.assertEqual(header("exa"), {"x-api-key": want["EXA_API_KEY"]})
            self.assertEqual(header("jina"), {"Authorization": "Bearer " + want["JINA_API_KEY"]})
            self.assertEqual(header("spider"), {})
            self.assertEqual(header("context7"), {})
        finally:
            shutil.rmtree(tmp)


if __name__ == "__main__":
    unittest.main()
