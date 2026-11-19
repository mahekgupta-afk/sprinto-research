"""Outputs: per-company report.md, out/summary.md, out/review.csv (human columns survive re-runs)."""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Dict, List

BASELINE_MIN = (15, 20)
HUMAN_COLS = ["stage", "lead_agrees", "edit_level", "replied", "notes"]
MACHINE_COLS = ["domain", "company", "status", "verdict_fixed", "verdict_final", "score_low", "score_high", "contact_name",
                "contact_title", "contact_email", "subject", "reviewer_avg", "rewrites", "seconds"]


def load_traces(out_dir: Path) -> List[dict]:
    out = []
    for f in sorted(out_dir.glob("*/trace.json")):
        try:
            out.append(json.loads(f.read_text()))
        except ValueError:
            continue
    return out


def report_md(tr: dict) -> str:
    L = ["# %s" % tr["domain"], "", "Status: **%s**" % tr["status"]]
    if tr.get("error"):
        L += ["", "Error: %s" % tr["error"]]
    fin = tr.get("qualify_final")
    if fin:
        L += ["", "## Why this company", "",
              "Verdict **%s** (score %d to %d, qualify line 60). Fixed pipeline said **%s**." % (
                  tr["verdict_final"], fin["low"], fin["high"], tr["verdict_fixed"]), "",
              "| Signal | Bucket | Points | Evidence |", "|---|---|---|---|"]
        for s in fin["signals"]:
            L.append("| %s | %s | %s / %d | %s |" % (s["signal"], s["bucket"], "?" if s["points"] is None else s["points"], s["max"], ", ".join(s["evidence_ids"]) or s["note"]))
        for c in fin["caps"]:
            L.append("\nCap applied: %s (max %d)" % (c["cap"], c["max"]))
        for q in fin["disqualifiers"]:
            L.append("\nDisqualifier: %s %s" % (q["reason"], q.get("detail", "")))
    if tr.get("agent", {}).get("steps"):
        L += ["", "## Agent loop", ""]
        for s in tr["agent"]["steps"]:
            if "stopped" in s:
                L.append("- stopped: %s" % s["stopped"])
            else:
                L.append("- %s `%s` (%s): %s → %s%s" % (s["tool"], s["argument"], s["reason"], s.get("before"), s.get("after", "n/a"), " [%s]" % s["error"] if s.get("error") else ""))
    c = tr.get("contact")
    if c:
        p = c.get("person")
        L += ["", "## Why this person", ""]
        L.append("%s, %s (%s). Rule order for this headcount: %s. %s." % (p["name"], p["title"], p["source"], " > ".join(c["order"]), c["note"]) if p else "No contact: %s." % c["note"])
    em = tr.get("email")
    if em and em.get("best"):
        b = em["best"]
        L += ["", "## Why this email", ""] + ["- %s (%s)" % (p["pain"], ", ".join(p["evidence_ids"])) for p in tr.get("pains", [])]
        r = b["review"]
        L += ["", "Reviewer: specificity %d, relevance %d, reply likelihood %d. %s" % (r["specificity"], r["relevance"], r["reply_likelihood"], r["critique"]),
              "", "**Subject:** %s" % b["subject"], "", b["body"]]
        if tr.get("intended"):
            L += ["", "Intended recipient: %s" % tr["intended"]]
        if tr.get("gmail_link"):
            L += ["", "[Open in Gmail compose (to yourself)](%s)" % tr["gmail_link"]]
    elif em:
        L += ["", "## Email held", "", "No draft passed validation. Nothing was sent."]
        for d in em["drafts"]:
            L.append("- draft %d: %s" % (d["n"], "; ".join(d["code_failures"])))
    if tr.get("evidence"):
        L += ["", "## Evidence", "", "| ID | Topic | Claim | Quote | Source |", "|---|---|---|---|---|"]
        for e in tr["evidence"]:
            L.append("| %s | %s | %s | \"%s\" | %s |" % (e["id"], e["topic"], e["claim"].replace("|", "/"), e["quote"].replace("|", "/"), e["url"]))
    return "\n".join(L) + "\n"


def write_reports(out_dir: Path, traces: List[dict]) -> None:
    for tr in traces:
        (out_dir / tr["domain"]).mkdir(parents=True, exist_ok=True)
        (out_dir / tr["domain"] / "report.md").write_text(report_md(tr))
    (out_dir / "summary.md").write_text(summary_md(traces))
    write_review_csv(out_dir / "review.csv", traces)


def metrics(traces: List[dict]) -> dict:
    n = len(traces)
    secs = [t["seconds"] for t in traces if "seconds" in t]
    avg = sum(secs) / len(secs) if secs else 0
    overturned = [t["domain"] for t in traces if t.get("verdict_fixed") and t["verdict_fixed"] != t.get("verdict_final")]
    revs = [t["email"]["best"]["review"]["avg"] for t in traces if t.get("email") and t["email"].get("best")]
    drafted = [t for t in traces if t.get("email")]
    rewr = sum(1 for t in drafted if t["email"]["rewrites"] > 0)
    counts: Dict[str, int] = {}
    for t in traces:
        counts[t["status"]] = counts.get(t["status"], 0) + 1
    return {"companies": n, "avg_seconds": round(avg, 1), "baseline_minutes": BASELINE_MIN, "overturned": overturned,
            "reviewer_avg": round(sum(revs) / len(revs), 1) if revs else None, "statuses": counts,
            "rewrite_rate": round(rewr / len(drafted), 2) if drafted else 0}


def summary_md(traces: List[dict]) -> str:
    m = metrics(traces)
    lo, hi = m["baseline_minutes"]
    L = ["# Run summary", "",
         "- Companies processed: %d" % m["companies"],
         "- Time per company: %.1f s automated vs %d-%d min by hand (%.0fx faster at the midpoint)" % (
             m["avg_seconds"], lo, hi, (lo + hi) / 2 * 60 / m["avg_seconds"] if m["avg_seconds"] else 0),
         "- Statuses: " + ", ".join("%s %d" % kv for kv in sorted(m["statuses"].items())),
         "- Verdicts overturned by the agent loop: %d %s" % (len(m["overturned"]), ", ".join(m["overturned"])),
         "- Reviewer average (0-10): %s" % (m["reviewer_avg"] if m["reviewer_avg"] is not None else "n/a"),
         "", "## Kill criteria", ""]
    unbacked = [t["domain"] for t in traces if t["status"] == "sent" and not (t.get("email", {}).get("best") or {}).get("passed")]
    L.append("- Any unbacked claim sent: %s" % ("YES: " + ", ".join(unbacked) if unbacked else "no"))
    L.append("- Rewrite rate %.0f%% (kill if >50%% at day 30): %s" % (m["rewrite_rate"] * 100, "BREACHED" if m["rewrite_rate"] > 0.5 else "ok"))
    return "\n".join(L) + "\n"


def write_review_csv(path: Path, traces: List[dict]) -> None:
    old: Dict[str, dict] = {}
    if path.exists():
        with path.open(newline="") as f:
            old = {r["domain"]: r for r in csv.DictReader(f)}
    rows = []
    for t in traces:
        fin = t.get("qualify_final") or {}
        p = (t.get("contact") or {}).get("person") or {}
        b = (t.get("email") or {}).get("best") or {}
        row = {"domain": t["domain"], "company": (t.get("profile") or {}).get("name", ""), "status": t["status"],
               "verdict_fixed": t.get("verdict_fixed", ""), "verdict_final": t.get("verdict_final", ""),
               "score_low": fin.get("low", ""), "score_high": fin.get("high", ""), "contact_name": p.get("name", ""),
               "contact_title": p.get("title", ""), "contact_email": p.get("email", ""), "subject": b.get("subject", ""),
               "reviewer_avg": (b.get("review") or {}).get("avg", ""), "rewrites": (t.get("email") or {}).get("rewrites", ""),
               "seconds": t.get("seconds", "")}
        prev = old.get(t["domain"], {})
        for h in HUMAN_COLS:
            row[h] = prev.get(h, "")
        rows.append(row)
    # keep human rows for domains not in this run
    done = {r["domain"] for r in rows}
    rows += [{**{c: "" for c in MACHINE_COLS}, **r} for d, r in old.items() if d not in done]
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=MACHINE_COLS + HUMAN_COLS)
        w.writeheader()
        w.writerows(rows)


STAGES = ["contacted", "replied", "meeting", "dead"]
ENUMS = {"stage": [""] + STAGES, "lead_agrees": ["", "yes", "no"], "edit_level": ["", "none", "light", "heavy", "rewrote"],
         "replied": ["", "yes", "no"]}


def update_review(path: Path, domain: str, fields: dict) -> dict:
    """Validate and save the human columns for one domain. Machine columns are untouched."""
    clean = {}
    for k, v in fields.items():
        if k in ENUMS:
            if v not in ENUMS[k]:
                raise ValueError("invalid %s" % k)
            clean[k] = v
        elif k == "notes":
            if not isinstance(v, str) or len(v) > 2000:
                raise ValueError("invalid notes")
            clean[k] = v.replace("\r", " ")
        else:
            raise ValueError("unknown field %s" % k)
    rows: Dict[str, dict] = {}
    if path.exists():
        with path.open(newline="") as f:
            rows = {r["domain"]: r for r in csv.DictReader(f)}
    row = rows.get(domain) or {c: "" for c in MACHINE_COLS + HUMAN_COLS}
    row["domain"] = domain
    row.update(clean)
    rows[domain] = row
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=MACHINE_COLS + HUMAN_COLS)
        w.writeheader()
        w.writerows(rows.values())
    return {h: row.get(h, "") for h in HUMAN_COLS}


def read_review(path: Path) -> Dict[str, dict]:
    if not path.exists():
        return {}
    with path.open(newline="") as f:
        return {r["domain"]: {h: r.get(h, "") for h in HUMAN_COLS} for r in csv.DictReader(f)}
