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
