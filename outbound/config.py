"""Settings, secret scrubbing and paths."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import yaml
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent.parent
REQUIRED = ["GEMINI_API_KEY", "RESEND_API_KEY", "HUNTER_API_KEY", "TO_EMAIL"]


class ConfigError(RuntimeError):
    pass


@dataclass
class Settings:
    gemini_api_key: str = ""
    resend_api_key: str = ""
    hunter_api_key: str = ""
    to_email: str = ""
    from_email: str = "onboarding@resend.dev"
    sender_name: str = "Sprinto Growth"
    model_fast: str = "gemini-3-flash-preview"
    model_strong: str = "gemini-3.1-pro-preview"
    model_grounding: str = "gemini-3-flash-preview"
    min_interval: float = 6.5
    require_approval: bool = True
    out_dir: Path = field(default_factory=lambda: ROOT / "out")
    cache_dir: Path = field(default_factory=lambda: ROOT / "cache")

    @property
    def db_path(self) -> Path:
        return self.out_dir / "autopilot.db"

    def secrets(self) -> List[str]:
        return [s for s in (self.gemini_api_key, self.resend_api_key, self.hunter_api_key) if s]

    def missing(self) -> List[str]:
        vals = {"GEMINI_API_KEY": self.gemini_api_key, "RESEND_API_KEY": self.resend_api_key,
                "HUNTER_API_KEY": self.hunter_api_key, "TO_EMAIL": self.to_email}
        return [k for k, v in vals.items() if not v]


def load_settings(env: Optional[Dict[str, str]] = None, env_file: Optional[Path] = None) -> Settings:
    """env overrides the process env and the .env file (used by tests)."""
    values: Dict[str, str] = {}
    f = env_file or (ROOT / ".env")
    if f.exists():
        values.update({k: v for k, v in dotenv_values(f).items() if v is not None})
    values.update(os.environ if env is None else {})
    if env is not None:
        values.update(env)
    g = lambda k, d="": (values.get(k) or d).strip()
    return Settings(
        gemini_api_key=g("GEMINI_API_KEY"), resend_api_key=g("RESEND_API_KEY"),
        hunter_api_key=g("HUNTER_API_KEY"), to_email=g("TO_EMAIL"),
        from_email=g("FROM_EMAIL", "onboarding@resend.dev"), sender_name=g("SENDER_NAME", "Sprinto Growth"),
        model_fast=g("GEMINI_MODEL_FAST", "gemini-3-flash-preview"),
        model_strong=g("GEMINI_MODEL_STRONG", "gemini-3.1-pro-preview"),
        model_grounding=g("GEMINI_MODEL_GROUNDING", "gemini-3-flash-preview"),
        min_interval=float(g("GEMINI_MIN_INTERVAL", "6.5")),
        require_approval=g("REQUIRE_APPROVAL", "true").lower() not in ("0", "false", "no"),
    )


def require(settings: Settings) -> None:
    miss = settings.missing()
    if miss:
        raise ConfigError("Missing in .env: " + ", ".join(miss))


_KEYLIKE = re.compile(r"(AIza[0-9A-Za-z_\-]{20,}|re_[0-9A-Za-z_]{16,}|sk-[0-9A-Za-z]{20,}|[0-9a-f]{40})")


def scrub(text: str, settings: Optional[Settings] = None) -> str:
    """Remove configured secrets and key-shaped strings from a message."""
    text = str(text)
    if settings:
        for s in settings.secrets():
            text = text.replace(s, "***")
    return _KEYLIKE.sub("***", text)


def load_icp(path: Optional[Path] = None) -> dict:
    return yaml.safe_load((path or ROOT / "config" / "icp.yaml").read_text())


def load_proof_lines(path: Optional[Path] = None) -> List[str]:
    p = path or ROOT / "config" / "sprinto_facts.md"
    lines, on = [], False
    for ln in p.read_text().splitlines():
        if ln.strip() == "PROOF":
            on = True
        elif on and ln.strip().startswith("- "):
            lines.append(ln.strip()[2:].strip())
    return lines


def valid_domain(d: str) -> bool:
    return bool(re.fullmatch(r"(?=.{4,253}$)([a-z0-9]([a-z0-9\-]{0,61}[a-z0-9])?\.)+[a-z]{2,24}", d.lower()))


def clean_domain(d: str) -> str:
    d = d.strip().lower()
    d = re.sub(r"^https?://", "", d).split("/")[0]
    return d[4:] if d.startswith("www.") else d
