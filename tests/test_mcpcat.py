import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from stack import doctor, frontmatter, mcpcat  # noqa: E402

CAT = {"exa": {"type": "http", "url": "https://x.test/mcp", "headersHelper": 'd="$PWD"; exec "$d/h" exa'},
       "fetch": {"type": "stdio", "command": "sh", "args": ["-c", 'exec "$d/bin/mcp-run" uvx f']}}


class InlineServerTests(unittest.TestCase):
    def test_frontmatter_round_trips_inline_definitions(self):
        doc = "---\nname: a\nmcpServers: [exa, computer-use]\n---\nbody\n"
        entries = mcpcat.render(frontmatter.parse(doc)["mcpServers"], CAT)
        self.assertEqual(entries, [{"exa": CAT["exa"]}, "computer-use"])
        out = frontmatter.set_keys(doc, {"mcpServers": entries})
        self.assertEqual(len([ln for ln in out.split("\n") if ln.startswith("mcpServers:")]), 1)
        self.assertEqual(frontmatter.parse(out)["mcpServers"], entries)
        self.assertTrue(out.endswith("---\nbody\n"))

    def test_drift_flags_names_and_stale_copies_only(self):
        stale = {"exa": dict(CAT["exa"], url="https://old.test")}
        self.assertEqual(mcpcat.drift(["exa", {"fetch": CAT["fetch"]}, "computer-use"], CAT), ["exa"])
        self.assertEqual(mcpcat.drift([stale], CAT), ["exa"])
        self.assertEqual(mcpcat.drift(mcpcat.render(["exa", "fetch"], CAT), CAT), [])

    def test_repo_agents_carry_current_inline_copies(self):
        cat = mcpcat.catalog()
        self.assertTrue(cat)
        self.assertEqual(mcpcat.sync(dry_run=True), [])
        for f in mcpcat.agent_files():
            for e in doctor._as_list(frontmatter.read(f).get("mcpServers")):
                if mcpcat.entry_name(e) in cat:
                    self.assertIsInstance(e, dict, "%s references %r by name (not lazy)" % (f, e))

    def test_catalog_servers_are_not_session_wide(self):
        self.assertFalse(set(mcpcat.catalog()) & doctor.mcp_names())


if __name__ == "__main__":
    unittest.main()
