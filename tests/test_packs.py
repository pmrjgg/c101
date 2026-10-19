"""Tests for install packs (stack/packs.py) and tier enforcement helpers (stack/tiers.py)."""
import stackenv  # noqa: F401  (first: scrub leaked env vars, see tests/stackenv.py)
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


class DoctorAuthTests(unittest.TestCase):
    def _env_warnings(self):
        rep = doctor.Report()
        doctor.check_auth(rep)
        return [w for w in rep.warnings if w.startswith("environment:")]

    def test_api_credential_in_env_warns(self):
        saved = os.environ.pop("ANTHROPIC_API_KEY", None)
        try:
            self.assertEqual(self._env_warnings(), [])
            os.environ["ANTHROPIC_API_KEY"] = "x"
            self.assertEqual(len(self._env_warnings()), 1)
            self.assertIn("instead of your subscription", self._env_warnings()[0])
        finally:
            os.environ.pop("ANTHROPIC_API_KEY", None)
            if saved is not None:
                os.environ["ANTHROPIC_API_KEY"] = saved


class ManagedSettingsTests(unittest.TestCase):
    def test_install_merges_exact_allowlist_and_keeps_other_keys(self):
        import tempfile
        from stack import managed
        d = tempfile.mkdtemp()
        p = os.path.join(d, "ClaudeCode", "managed-settings.json")
        os.makedirs(os.path.dirname(p))
        with open(p, "w") as fh:
            json.dump({"permissions": {"deny": ["WebFetch"]}, "availableModelsMatch": "prefix"}, fh)
        self.assertTrue(managed.install(p))
        with open(p) as fh:
            got = json.load(fh)
        self.assertEqual(got["permissions"], {"deny": ["WebFetch"]})
        self.assertEqual(got["availableModelsMatch"], "exact")
        self.assertEqual(got["availableModels"], sorted(tiers.allowed_models()))
        self.assertFalse(managed.install("/proc/no-such-dir/managed-settings.json"))

    def test_doctor_warns_on_managed_only_keys_outside_managed_settings(self):
        import tempfile
        d = tempfile.mkdtemp()
        os.makedirs(os.path.join(d, ".claude"))
        with open(os.path.join(d, ".claude", "settings.json"), "w") as fh:
            json.dump({"availableModelsMatch": "exact"}, fh)
        real, paths.REPO = paths.REPO, d
        try:
            rep = doctor.Report()
            doctor.check_auth(rep)
        finally:
            paths.REPO = real
        self.assertTrue(any("availableModelsMatch is honoured only from managed settings" in w for w in rep.warnings))

    def test_repo_settings_carry_no_managed_only_keys(self):
        from stack.managed import MANAGED_ONLY_KEYS
        with open(os.path.join(paths.REPO, ".claude", "settings.json")) as fh:
            st = json.load(fh)
        self.assertFalse(set(MANAGED_ONLY_KEYS) & set(st))


class GlobalModelEnforcementTests(unittest.TestCase):
    def test_enforce_models_alone_writes_only_model_keys_and_undoes_cleanly(self):
        import tempfile
        from stack import install
        d = tempfile.mkdtemp()
        p = os.path.join(d, "settings.json")
        before = {"theme": "dark", "availableModelsMatch": "exact",
                  "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo hi"}]}]}}
        with open(p, "w") as fh:
            json.dump(before, fh)
        real, install.CLAUDE = install.CLAUDE, d
        try:
            install.enforce_models_global(install.Ctx(False), True)
            install.enforce_models_global(install.Ctx(False), True)  # idempotent
            with open(p) as fh:
                on = json.load(fh)
            install.enforce_models_global(install.Ctx(False), False)
            with open(p) as fh:
                off = json.load(fh)
        finally:
            install.CLAUDE = real
        self.assertEqual(on["availableModels"], sorted(tiers.allowed_models()))
        self.assertIs(on["enforceAvailableModels"], True)
        self.assertNotIn("availableModelsMatch", on)  # ignored outside managed settings
        self.assertEqual(len(on["hooks"]["PreModelSwitch"]), 1)
        self.assertIn(install.MODEL_HOOK, on["hooks"]["PreModelSwitch"][0]["hooks"][0]["command"])
        self.assertEqual(on["theme"], "dark")
        self.assertEqual(off, {"theme": "dark", "hooks": before["hooks"]})


if __name__ == "__main__":
    unittest.main()
