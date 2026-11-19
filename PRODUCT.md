# Product

**Problem.** Sprinto's Growth Lead researches each prospect by hand: 15 to 20 minutes per company, and quality drops after 8 to 15.

**What it does.** Domain list in; for each company: cited research, an ICP verdict with a score range, a named contact with the reason, two pain points, and a personalised email in the Growth Lead's own inbox with "Intended recipient" at the bottom.

**Principles.**
1. Every decision is defensible: evidence IDs (E1, E2...) trace to an exact quote on a real page.
2. Unknown is not absent. A blocked page, an empty shell or a signal the website cannot settle (headcount, funding, hiring) widens the score range; it never subtracts points.
3. The LLM picks buckets; Python does the maths, caps and verdicts.
4. Nothing unbacked goes out: 20+ code rules gate every email; a failing email is held, not sent.
5. Mail goes to `TO_EMAIL` only. `send_email()` has no recipient parameter.

**Users.** The Growth Lead (reviews, edits, forwards by hand) and the head of growth (reads the Home view).
