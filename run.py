#!/usr/bin/env python
"""Usage: python run.py domains.txt   |   python run.py acme.com globex.io"""
import sys
from pathlib import Path

from outbound.config import ConfigError
from outbound.runner import build_deps, run_batch


def read_domains(args):
    out = []
    for a in args:
        p = Path(a)
        if p.exists() and p.is_file():
            out += [l.split("#")[0].strip() for l in p.read_text().splitlines()]
        else:
            out.append(a)
    return [d for d in out if d]


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    try:
        deps = build_deps()
    except ConfigError as e:
        print(e)
        return 1
    res = run_batch(read_domains(argv), deps, lambda d, t: print("%-32s %-18s %s" % (d, t["status"], t.get("error", ""))))
    print("\nWrote out/summary.md, out/review.csv and out/<domain>/report.md")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
