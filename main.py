#!/usr/bin/env python
"""Command line for the whole system.

  python main.py migrate                  create/upgrade the SQLite database
  python main.py discover [--limit N]     find recently funded companies (no research yet)
  python main.py run acme.com globex.io   research domains (or: run --discovered [--limit N])
  python main.py pending                  list drafts waiting for approval
  python main.py learn                    distil your edits and ratings into writing rules
  python main.py serve [--port 8000]      open the CRM
Approve or reject drafts in the CRM Queue.
"""
import argparse
import sys
from pathlib import Path

from outbound.config import ConfigError, load_settings


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("migrate")
    d = sub.add_parser("discover"); d.add_argument("--limit", type=int, default=None)
    r = sub.add_parser("run"); r.add_argument("domains", nargs="*"); r.add_argument("--discovered", action="store_true"); r.add_argument("--limit", type=int, default=None)
    sub.add_parser("pending")
    sub.add_parser("learn")
    s = sub.add_parser("serve"); s.add_argument("--port", type=int, default=8000)
    a = ap.parse_args(argv)
    st = load_settings()
    from outbound.db import connect
    if a.cmd == "migrate":
        with connect(st.db_path):
            pass
        print("database ready at", st.db_path)
        return 0
    if a.cmd == "pending":
        with connect(st.db_path) as c:
            rows = c.execute("SELECT domain, subject, created_at FROM drafts WHERE status='pending' ORDER BY id").fetchall()
        for x in rows:
            print("%-30s %s  (%s)" % (x["domain"], x["subject"], x["created_at"]))
        print("%d waiting" % len(rows))
        return 0
    if a.cmd == "serve":
        import app
        srv = app.make_server(a.port)
        print("CRM on http://127.0.0.1:%d" % a.port)
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            pass
        return 0
    try:
        from outbound.runner import build_deps, run_batch, run_discovered
        deps = build_deps(st)
    except ConfigError as e:
        print(e)
        return 1
    if a.cmd == "discover":
        from outbound.discover import discover
        for c in discover(deps.http, st.db_path, a.limit):
            print("%-28s %-22s %s  %s" % (c["company"], c["domain"] or "FLAGGED", c["round"], c["note"] if not c["domain"] else c["headline"]))
        return 0
    if a.cmd == "learn":
        from outbound.feedback import learn
        rules = learn(deps.llm, st.db_path)
        print("\n".join("- " + x for x in rules) or "nothing to learn from yet")
        return 0
    show = lambda dom, t: print("%-32s %-18s %s" % (dom, t["status"], t.get("error", "")))
    if a.discovered:
        run_discovered(deps, a.limit, show)
    elif a.domains:
        from run import read_domains
        run_batch(read_domains(a.domains), deps, show)
    else:
        print("give domains or --discovered")
        return 2
    print("\nDrafts wait in the CRM Queue." if st.require_approval else "\nDone.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
