from __future__ import annotations

from pathlib import Path
from typing import Callable, List, Optional

from .config import ROOT, load_icp, load_proof_lines, load_settings, require, clean_domain
from .contacts import Hunter, read_overrides
from .llm import LLM
from .pipeline import Deps, process, write_trace
from .report import load_traces, write_reports
from .scrape import make_client


def build_deps(settings=None) -> Deps:
    s = settings or load_settings()
    require(s)
    http = make_client()
    return Deps(settings=s, llm=LLM(s), http=http, hunter=Hunter(s, http), icp=load_icp(),
                proof_lines=load_proof_lines(), overrides=read_overrides(ROOT / "contacts.csv"))


def run_batch(domains: List[str], deps: Deps, on_progress: Optional[Callable[[str, dict], None]] = None) -> List[dict]:
    out = deps.settings.out_dir
    out.mkdir(parents=True, exist_ok=True)
    seen, results = set(), []
    for raw in domains:
        d = clean_domain(raw)
        if not d or d in seen:
            continue
        seen.add(d)
        tr = process(d, deps)
        write_trace(out, tr)
        results.append(tr)
        if on_progress:
            on_progress(d, tr)
    write_reports(out, load_traces(out))
    return results


def run_discovered(deps: Deps, limit: Optional[int] = None, on_progress=None) -> List[dict]:
    from .discover import discover
    found = discover(deps.http, deps.settings.db_path, limit)
    return run_batch([c["domain"] for c in found if c["domain"]], deps, on_progress)


def run_until_fits(deps: Deps, min_fits: Optional[int] = None, on_progress=None) -> dict:
    """Discover a batch, research it, and if too few companies fit the ICP fetch the next batch (cooldown skips repeats)."""
    from .discover import discover, load_cfg
    cfg = load_cfg()
    want, rounds = min_fits or cfg["min_fits"], cfg["max_rounds"]
    fits, flagged, done = 0, 0, []
    for n in range(rounds):
        found = discover(deps.http, deps.settings.db_path, cfg["max_candidates"], cfg=cfg)
        flagged += sum(1 for c in found if not c["domain"])
        res = run_batch([c["domain"] for c in found if c["domain"]], deps, on_progress)
        done += res
        fits += sum(1 for t in res if t.get("verdict_final") in ("PRIORITY", "QUALIFY"))
        if fits >= want or not found:
            break
    return {"rounds": n + 1, "fits": fits, "researched": len(done), "flagged": flagged}
