import subprocess
from pathlib import Path

from outbound.config import ConfigError, clean_domain, load_icp, load_proof_lines, load_settings, require, scrub, valid_domain

ROOT = Path(__file__).resolve().parent.parent


def test_load_settings_from_env_and_defaults(tmp_path):
    s = load_settings(env={"GEMINI_API_KEY": "g", "RESEND_API_KEY": "r", "HUNTER_API_KEY": "h", "TO_EMAIL": "me@x.com"},
                      env_file=tmp_path / "none.env")
    assert s.to_email == "me@x.com" and s.min_interval == 6.5 and s.from_email == "onboarding@resend.dev"
    assert s.missing() == []


def test_missing_keys_reported(tmp_path):
    s = load_settings(env={"GEMINI_API_KEY": "g"}, env_file=tmp_path / "none.env")
    try:
        require(s)
        assert False
    except ConfigError as e:
        assert "HUNTER_API_KEY" in str(e) and "TO_EMAIL" in str(e)


def test_models_and_interval_configurable(tmp_path):
    s = load_settings(env={"GEMINI_MODEL_FAST": "m1", "GEMINI_MIN_INTERVAL": "0.5"}, env_file=tmp_path / "none.env")
    assert s.model_fast == "m1" and s.min_interval == 0.5


def test_scrub_removes_secrets(settings):
    msg = "failed with key %s and re_ABCDEFGHIJKLMNOP1234 " % settings.gemini_api_key
    out = scrub(msg, settings)
    assert settings.gemini_api_key not in out and "re_ABCDEF" not in out


def test_domain_helpers():
    assert clean_domain("https://www.Acme.com/x") == "acme.com"
    assert valid_domain("acme.com") and not valid_domain("../etc") and not valid_domain("a b.com") and not valid_domain("localhost")


def test_icp_is_100_points_15_signals_4_blocks():
    icp = load_icp()
    assert len(icp["signals"]) == 15
    assert sum(s["max"] for s in icp["signals"]) == 100
    for b, pts in icp["blocks"].items():
        assert sum(s["max"] for s in icp["signals"] if s["block"] == b) == pts
    for s in icp["signals"]:
        assert max(x["points"] for x in s["buckets"]) == s["max"]
    assert {"headcount", "funding_stage", "security_hiring", "recent_funding"} <= {s["id"] for s in icp["signals"] if s.get("external")}


def test_proof_lines_whitelist():
    assert len(load_proof_lines()) >= 2


def test_secrets_are_ignored_by_git():
    for f in [".env", ".env.local", "out/x/trace.json", "cache/hunter/a.json", "contacts.csv", ".vercel/x", "shots/a.png"]:
        r = subprocess.run(["git", "check-ignore", "-q", f], cwd=ROOT)
        assert r.returncode == 0, f
    assert subprocess.run(["git", "check-ignore", "-q", ".env.example"], cwd=ROOT).returncode == 1


def test_env_example_has_only_placeholders():
    t = (ROOT / ".env.example").read_text()
    assert "your-gemini-key" in t and "AIza" not in t and "re_" not in t


def test_bucket_ids_are_strings_and_unique():
    for s in load_icp()["signals"]:
        ids = [b["id"] for b in s["buckets"]]
        assert all(isinstance(i, str) for i in ids) and len(set(ids)) == len(ids)
