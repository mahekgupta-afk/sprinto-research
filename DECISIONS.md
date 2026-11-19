# Decisions

**Outcome.** A Growth Lead gets, per company, a verdict, a named contact and a drafted email in their own inbox in about a minute, each with cited evidence, instead of 15 to 20 minutes of manual research.

**Baseline.** 15 to 20 minutes per company by hand (Growth Lead's estimate), with quality dropping after 8 to 15 companies. `out/summary.md` compares each run to the midpoint (17.5 min).

**Workflow change.** The Growth Lead stops researching and starts reviewing: open the CRM Queue, read each draft and its evidence, edit if needed, approve (it lands in their own inbox) or reject, log the outcome. Edits and ratings are stored in SQLite and fed back into the next drafts. Nothing is ever sent to a prospect by the system.

**90-day measurement plan.** Track in `review.csv` (human columns): `lead_agrees` (verdict agreement), `edit_level` (none/light/heavy/rewrote), `replied`, `stage`.
Day 30: edit level and agreement on the first 50 accounts. Day 60: reply rate against the Growth Lead's manual-email baseline. Day 90: meetings booked per 100 accounts researched, and hours saved (companies x 17.5 min minus review time).

**Kill criteria.** Stop and rework if any of: an email containing a claim not backed by evidence is sent; more than 50% of drafted emails need a rewrite at day 30; the Growth Lead disagrees with more than a third of verdicts at day 30. `out/summary.md` checks the first two automatically.

**Choices worth knowing.**
- Python 3.9, not 3.12: the build machine had no 3.12. No 3.10+ syntax is used.
- ICP rubric (15 signals, 100 points) in `config/icp.yaml` is a first draft written from the brief; the Growth Lead should tune bucket points before day 1.
- Verdict uses the *proven* score (`low`); a verdict is certain only if the 60 line is outside `[low, high]`.
- Reviewer gate is the minimum of the three scores (>= 7), stricter than the average.
- The spelled-out number rule rejects "two" to "twenty", tens, "hundred" and larger, but allows "one".
- Demo masks contact names to first name + last initial in addition to removing emails and LinkedIn.
- Fonts: system grotesk stack (no font files bundled).

**Before going public (needs your yes; not done).** Run `scripts/pre_public_check.py`; enable GitHub secret scanning and push protection; deploy `site/` only; then verify `/.env`, `/app.py`, `/out/x`, `/contacts.csv` return 404 and the served data has zero emails and keys.

**Added in the second pass.** Funding-news discovery (Google News RSS, regex gates, 90-day cooldown, homepage-checked domain resolution), a human approval gate (default on, `REQUIRE_APPROVAL=false` restores auto-send to self), edit re-validation on approval, a feedback loop, a SQLite store, and scheduled GitHub Actions runs. Architecture follows the component map the user shared; all code is original and was not copied from that repository, which has no licence.
