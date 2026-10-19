"""Tests for install packs (stack/packs.py) and tier enforcement helpers (stack/tiers.py)."""
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from stack import doctor, frontmatter, packs, paths, tiers  # noqa: E402


class PackTests(unittest.TestCase):
    def test_core_always_included_and_requirements_resolved(self):
        self.assertEqual(packs.resolve([]), ["core"])
        r = packs.resolve(["graphic-design"])
        self.assertEqual(r[0], "core")
        self.assertIn("image", r)
        self.assertLess(r.index("image"), r.index("graphic-design"))
        with self.assertRaises(ValueError):
            packs.resolve(["no-such-pack"])

    def test_every_skill_and_agent_belongs_to_a_pack(self):
        cfg = packs.load()
        all_packs = list(cfg["packs"])
        self.assertEqual(packs.skills_of(all_packs, cfg), doctor.skill_names())
        self.assertEqual(packs.agents_of(all_packs, cfg), set(doctor.agent_names()))

    def test_overrides_turn_off_unselected_domains_only(self):
        ov = packs.overrides(["rust"])
        self.assertNotIn("rust-craft", ov)
        self.assertEqual(ov.get("quantum-computing"), "off")
        for s in packs.skills_of(["core"]):
            self.assertNotEqual(ov.get(s), "off", s)

    def test_preloaded_skills_are_never_name_only(self):
        ov = packs.overrides(["all"])
        for f in paths.all_agent_files():
            for s in doctor._as_list(frontmatter.read(f).get("skills")):
                self.assertNotIn(s, ov, s)


class TierTests(unittest.TestCase):
    def test_allowed_models_are_the_three_tiers(self):
        self.assertEqual(tiers.allowed_models(), ["claude-haiku-5-5", "claude-opus-5-5", "claude-sonnet-5-5"])
        self.assertEqual(tiers.alias_models()["opus"], "claude-opus-5-5")

    def test_every_agent_runs_on_an_allowed_model(self):
        allowed = set(tiers.allowed_models())
        for f in paths.all_agent_files():
            self.assertIn(frontmatter.read(f).get("model"), allowed, f)

    def test_main_thread_pin(self):
        self.assertEqual(tiers.main_thread("delegator"), {"model": "claude-opus-5-5", "effort": "high"})


if __name__ == "__main__":
    unittest.main()
