"""Per-operation env configuration: parsing, precedence, adapter detection, errors."""

from __future__ import annotations

import pytest

from stack_mcp.image_router.config import (
    OPS,
    ConfigError,
    current_env,
    detect_api,
    env_names,
    load_all,
    load_op,
    parse_env_text,
    read_env_file,
    redact,
    require,
    secret_values,
)

from .conftest import COMPAT_URL, FAKE_KEYS, OPENROUTER_URL, OPPER_URL

SAMPLE = """\
# comment line
export IMAGE_GEN_URL=https://openrouter.ai/api/v1   # inline comment is dropped
IMAGE_GEN_KEY="sk-or-quoted value # not a comment"
IMAGE_GEN_MODEL='google/gemini-nano-banana-2.1'
  IMAGE_EDIT_URL = ignored-because-key-has-spaces
IMAGE_EDIT_MODEL=
NOT A LINE
IMAGE_REF_PARAMS='{"quality": "high", "provider": {"only": ["openai"]}}'
"""


def test_parse_env_text_rules():
    env = parse_env_text(SAMPLE)
    assert env["IMAGE_GEN_URL"] == "https://openrouter.ai/api/v1"
    assert env["IMAGE_GEN_KEY"] == "sk-or-quoted value # not a comment"
    assert env["IMAGE_GEN_MODEL"] == "google/gemini-nano-banana-2.1"
    assert env["IMAGE_EDIT_MODEL"] == ""
    assert "IMAGE_EDIT_URL" not in env and "  IMAGE_EDIT_URL " not in env
    assert env["IMAGE_REF_PARAMS"].startswith("{")


def test_parse_matches_stack_envfile(tmp_path):
    """Same rules as stack/envfile.py (the stack's own parser)."""
    from stack import envfile

    p = tmp_path / "x.env"
    p.write_text(SAMPLE)
    assert parse_env_text(SAMPLE) == envfile.parse(str(p))


def test_env_names():
    assert env_names("VECTOR_MANIPULATION")["key"] == "IMAGE_VECTOR_MANIPULATION_KEY"
    assert set(OPS) == {"GEN", "REF", "EDIT", "TRANSPARENT", "SEGMENT", "BG_REMOVAL", "UPSCALE", "VECTOR", "TRACE",
                        "VECTOR_MANIPULATION"}


def test_each_op_reads_its_own_triple(stack_env):
    for i, op in enumerate(OPS):
        if op == "VECTOR_MANIPULATION":
            continue
        stack_env.configure(op, OPENROUTER_URL if i % 2 else OPPER_URL, f"model/{op.lower()}")
    cfgs = load_all()
    for i, op in enumerate(OPS):
        if op == "VECTOR_MANIPULATION":
            continue
        c = cfgs[op]
        assert c.configured, (op, c.missing_env, c.error)
        assert c.model == f"model/{op.lower()}"
        assert c.api == ("openrouter" if i % 2 else "opper") and c.api_source == "detected"
        assert c.key() == FAKE_KEYS[op]
        assert c.host == ("openrouter.ai" if i % 2 else "api.opper.ai")


def test_file_is_read_at_call_time_and_wins_over_environ(stack_env, monkeypatch):
    monkeypatch.setenv("IMAGE_GEN_MODEL", "from-environ")
    monkeypatch.setenv("IMAGE_GEN_URL", COMPAT_URL)
    monkeypatch.setenv("IMAGE_GEN_KEY", "environ-key-123456")
    c = load_op("GEN")
    assert c.model == "from-environ" and c.api == "openai"  # nothing in the file: environ fallback
    stack_env.set(IMAGE_GEN_MODEL="from-file")
    assert load_op("GEN").model == "from-file"  # edit applies without a restart
    stack_env.set(IMAGE_GEN_MODEL="")
    assert load_op("GEN").model == "from-environ"  # empty value in the file falls back


def test_missing_env_names_and_require_message(stack_env):
    c = load_op("EDIT")
    assert not c.configured
    assert c.missing_env == ("IMAGE_EDIT_URL", "IMAGE_EDIT_MODEL", "IMAGE_EDIT_KEY")
    stack_env.set(IMAGE_EDIT_URL=OPENROUTER_URL, IMAGE_EDIT_MODEL="openai/gpt-image-2.5-sunburst")
    with pytest.raises(ConfigError) as exc:
        require("EDIT", "image_edit")
    assert exc.value.missing_env == ["IMAGE_EDIT_KEY"]
    msg = str(exc.value)
    assert "image_edit is not configured" in msg and "IMAGE_EDIT_KEY" in msg and "No fallback" in msg


def test_api_detection_and_explicit_override(stack_env):
    assert detect_api("https://openrouter.ai/api/v1") == "openrouter"
    assert detect_api("https://eu.openrouter.ai/api/v1") == "openrouter"
    assert detect_api("https://api.opper.ai") == "opper"
    assert detect_api("https://api.openai.com/v1") == "openai"
    assert detect_api("http://localhost:8080/v1") == "openai"
    stack_env.configure("GEN", "https://proxy.example.test/v1", "m", api="opper")
    c = load_op("GEN")
    assert c.api == "opper" and c.api_source == "explicit"
    stack_env.set(IMAGE_GEN_API="nonsense")
    assert "not one of" in load_op("GEN").error


def test_local_only_for_trace_and_upscale(stack_env):
    stack_env.set(IMAGE_TRACE_API="local", IMAGE_UPSCALE_API="local", IMAGE_GEN_API="local")
    assert load_op("TRACE").configured and load_op("TRACE").is_local
    assert load_op("UPSCALE").configured and load_op("UPSCALE").missing_env == ()
    gen = load_op("GEN")
    assert not gen.configured and "only available for TRACE and UPSCALE" in gen.error


def test_params_json_and_directives(stack_env):
    stack_env.configure("SEGMENT", OPENROUTER_URL, "m", params={"strategy": "detect", "quality": "high"})
    c = load_op("SEGMENT")
    assert c.params == {"quality": "high"} and c.directives == {"strategy": "detect"}
    assert c.strategy("render") == "detect"
    stack_env.set(IMAGE_SEGMENT_PARAMS="'{not json'")
    c = load_op("SEGMENT")
    assert not c.configured and "IMAGE_SEGMENT_PARAMS is not valid JSON" in c.error
    stack_env.set(IMAGE_SEGMENT_PARAMS="'[1, 2]'")
    assert "must be a JSON object" in load_op("SEGMENT").error


def test_vector_manipulation_defaults_to_claude(stack_env):
    c = load_op("VECTOR_MANIPULATION")
    assert c.is_claude and c.configured and c.describe()["tools"] == [] and c.describe()["mode"] == "claude"
    stack_env.set(IMAGE_VECTOR_MANIPULATION_MODEL="CLAUDE")
    assert load_op("VECTOR_MANIPULATION").is_claude
    stack_env.set(IMAGE_VECTOR_MANIPULATION_MODEL="anthropic/claude-sonnet-4.5")
    c = load_op("VECTOR_MANIPULATION")
    assert not c.is_claude and not c.configured
    assert c.missing_env == ("IMAGE_VECTOR_MANIPULATION_URL", "IMAGE_VECTOR_MANIPULATION_KEY")


def test_loopback_openai_compatible_needs_no_key(stack_env):
    stack_env.set(IMAGE_GEN_URL="http://127.0.0.1:8080/v1", IMAGE_GEN_MODEL="local-sd")
    c = load_op("GEN")
    assert c.configured and c.api == "openai" and c.key() == ""


def test_describe_never_contains_the_key(stack_env):
    key = stack_env.configure("GEN", OPENROUTER_URL + "?token=abc", "m")
    d = load_op("GEN").describe()
    text = repr(d)
    assert key not in text and "token=abc" not in text and "/api/v1" not in text
    assert d["url_host"] == "openrouter.ai"
    assert key not in repr(load_op("GEN"))  # dataclass repr hides the key too


def test_secret_values_and_redact(stack_env, monkeypatch):
    k1 = stack_env.configure("GEN", OPENROUTER_URL, "m")
    monkeypatch.setenv("OPPER_API_KEY", "op-environ-secret-1234")
    secrets = secret_values()
    assert k1 in secrets and "op-environ-secret-1234" in secrets
    assert redact(f"boom {k1} and op-environ-secret-1234") == "boom *** and ***"


def test_read_env_file_missing_is_empty(tmp_path):
    assert read_env_file(tmp_path / "nope.env") == {}
    assert "PATH" in current_env()


def test_image_ops_json_matches_the_code():
    """config/image-ops.json documents exactly the ops, tools, env names and adapters the server has."""
    import json

    from stack_mcp.image_router.config import OP_SPECS, OPS_DOC_PATH
    from stack_mcp.image_router.providers import ADAPTERS

    doc = json.loads(OPS_DOC_PATH.read_text())
    assert list(doc["ops"]) == list(OPS)
    for op, entry in doc["ops"].items():
        assert tuple(entry["tools"]) == OP_SPECS[op].tools
        names = env_names(op)
        assert entry["env"] == [names["url"], names["key"], names["model"], names["api"], names["params"]]
    for name, entry in doc["adapters"].items():
        assert sorted(entry["ops"]) == sorted(ADAPTERS[name].supports), name
    text = OPS_DOC_PATH.read_text()
    assert "sk-" not in text and "op-mak" not in text  # documentation only: no secrets


# --- regression: values bin/mcp-run injected at launch follow the file -------------------------------------


def test_lines_deleted_or_blanked_after_launch_stop_applying(stack_env, monkeypatch):
    from stack_mcp.image_router import config

    stack_env.set(
        IMAGE_GEN_URL=COMPAT_URL, IMAGE_GEN_KEY="sk-test-launch-0123456789", IMAGE_GEN_MODEL="gpt-image-1",
        IMAGE_GEN_API="openai", IMAGE_VECTOR_MANIPULATION_MODEL="openai/gpt-5.4", IMAGE_EDIT_MODEL="edit-model",
    )
    for k, v in read_env_file().items():  # what bin/mcp-run does before exec'ing the server
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("IMAGE_REF_MODEL", "from-the-real-environment")  # never in the file
    config.snapshot_boot_env()
    assert load_op("GEN").api == "openai" and not load_op("VECTOR_MANIPULATION").is_claude

    # the user switches GEN to OpenRouter (API line deleted: auto-detect), drops external vector
    # manipulation and blanks EDIT's model - without restarting the server
    stack_env.values = {"IMAGE_GEN_URL": OPENROUTER_URL, "IMAGE_GEN_KEY": FAKE_KEYS["GEN"],
                        "IMAGE_GEN_MODEL": "google/gemini-nano-banana-2.1", "IMAGE_EDIT_MODEL": ""}
    stack_env.set()
    gen = load_op("GEN")
    assert gen.api == "openrouter" and gen.api_source == "detected" and gen.host == "openrouter.ai"
    assert load_op("VECTOR_MANIPULATION").is_claude
    assert load_op("EDIT").model is None
    assert load_op("REF").model == "from-the-real-environment"  # names the file never set keep the fallback
    assert "sk-test-launch-0123456789" in secret_values()  # a stale key is still redacted if it ever shows up


def test_params_may_not_set_router_owned_fields(stack_env):
    stack_env.configure("GEN", OPENROUTER_URL, "m", params={"model": "other", "prompt": "x", "quality": "high"})
    c = load_op("GEN")
    assert not c.configured and "IMAGE_GEN_PARAMS may not set model, prompt" in c.error
    assert c.params == {"quality": "high"}


def test_deprecated_mask_and_rgba_prefixes_still_configure(stack_env):
    stack_env.set(IMAGE_MASK_URL=OPENROUTER_URL, IMAGE_MASK_KEY="sk-test-oldmask-0123456789", IMAGE_MASK_MODEL="m",
                  IMAGE_RGBA_URL=OPENROUTER_URL, IMAGE_RGBA_KEY="sk-test-oldrgba-0123456789", IMAGE_RGBA_MODEL="r")
    seg = load_op("SEGMENT")
    assert seg.configured and seg.deprecated_env == ("IMAGE_MASK_KEY", "IMAGE_MASK_MODEL", "IMAGE_MASK_URL")
    assert "rename" in seg.describe()["note"]
    assert load_op("TRANSPARENT").configured and load_op("BG_REMOVAL").model == "r"
    stack_env.configure("SEGMENT", OPENROUTER_URL, "new-model")  # the current prefix wins
    assert load_op("SEGMENT").model == "new-model" and load_op("SEGMENT").deprecated_env == ()


def test_fal_hosts_select_the_fal_adapter(stack_env):
    from stack_mcp.image_router.config import detect_api

    assert detect_api("https://queue.fal.run") == detect_api("https://fal.run") == "fal"
    assert detect_api("https://rest.alpha.fal.ai") == "fal"
    stack_env.configure("BG_REMOVAL", "https://queue.fal.run", "fal-ai/bria/background/remove")
    c = load_op("BG_REMOVAL")
    assert c.configured and c.api == "fal" and c.api_source == "detected"
