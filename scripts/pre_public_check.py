#!/usr/bin/env python
"""Run BEFORE making the repo public. Scans every commit for key-shaped strings, emails and screenshots/videos.
Exits 1 on any finding. Read-only: it changes nothing."""
import re
import subprocess
import sys

KEY = re.compile(r"(AIza[0-9A-Za-z_\-]{20,}|\bre_[0-9A-Za-z_]{16,}|\bsk-[0-9A-Za-z]{20,}|\b[0-9a-f]{40}\b|\bgh[pousr]_[0-9A-Za-z]{30,})")
EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(\.[A-Za-z0-9\-]+)+")
OK_EMAIL = re.compile(r"@(example\.(com|org)|resend\.dev|[a-z\-]+\.test)$|^(noreply|you|me|owner)@", re.I)
MEDIA = re.compile(r"\.(png|jpe?g|gif|webp|mp4|webm|mov)$", re.I)


def git(*a):
    return subprocess.run(["git", *a], capture_output=True, text=True, errors="ignore").stdout


def main():
    problems = []
    names = set(git("log", "--all", "--name-only", "--pretty=format:").split("\n"))
    problems += ["media file in history: %s" % n for n in sorted(names) if MEDIA.search(n)]
    problems += ["secret-like file in history: %s" % n for n in sorted(names) if re.search(r"(^|/)\.env(\..*)?$", n) and not n.endswith(".example")]
    patch = git("log", "--all", "-p", "--pretty=format:%H")
    added = [l[1:] for l in patch.split("\n") if l.startswith("+") and not l.startswith("+++")]
    for l in added:
        if KEY.search(l):
            problems.append("key-shaped string: %s..." % KEY.search(l).group(0)[:8])
        for m in EMAIL.finditer(l):
            if not OK_EMAIL.search(m.group(0)):
                problems.append("email in history: %s" % m.group(0))
    problems = sorted(set(problems))
    print("\n".join(problems) or "history clean")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
