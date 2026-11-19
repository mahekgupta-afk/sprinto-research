# Outbound Autopilot

Takes a list of company domains and, with no human in the loop: scrapes each site, extracts cited facts, scores the company
against Sprinto's ICP (an agent loop researches more when the site is too thin), finds the right contact, drafts a
personalised email, waits for **your approval**, then sends it to **your own inbox only**. State lives in SQLite (`out/autopilot.db`): funding candidates, the draft queue, and learned feedback. The prospect is never emailed.

## Setup
```bash
python3 -m venv .venv && .venv/bin/pip install -U pip && .venv/bin/pip install --only-binary=:all: -r requirements.txt
cp .env.example .env        # fill in GEMINI_API_KEY, RESEND_API_KEY, HUNTER_API_KEY, TO_EMAIL
.venv/bin/python preflight.py     # checks Hunter, Gemini structured output, Gemini grounding; sends ONE test email to TO_EMAIL
```
Built and tested on Python 3.9 (the only interpreter on the build machine). The code uses no 3.10+ syntax, so 3.12 also works.

## Run
```bash
.venv/bin/python main.py discover        # find recently funded companies from Google News (no LLM)
.venv/bin/python main.py run --discovered # research them; drafts wait in the CRM Queue
.venv/bin/python main.py learn           # distil your edits and ratings into writing rules
```
```bash
.venv/bin/python run.py domains.txt          # or: run.py acme.com globex.io
.venv/bin/python app.py 8000                 # CRM at http://127.0.0.1:8000
.venv/bin/python scripts/make_sample_data.py # synthetic .test accounts to try the CRM without keys
.venv/bin/pytest                             # tests (no network, no keys)
```
Outputs: `out/<domain>/trace.json` + `report.md`, `out/summary.md`, `out/review.csv` (your review columns survive re-runs).
Optional `contacts.csv` (`domain,name,title,email,linkedin`) overrides Hunter.

## Pipeline (one module each in `outbound/`)
`discover` → `resolve` → `scrape` → `extract` → `qualify` → `agent` → `contacts` → `pains` → `draft` (+ `validate`) → **your approval in the Queue** → `send`; `feedback` feeds your edits back into drafting; `pipeline.py` wires them.
Statuses: `sent`, `held`, `not_qualified`, `insufficient_data`, `no_contact`, `failed`. If no draft passes validation the email is **held** and nothing is sent.

## Public demo (Vercel)
```bash
.venv/bin/python build_demo.py     # web/ -> site/ with a scrubbed snapshot; refuses to build if an email or key survives
.venv/bin/python scripts/pre_public_check.py   # scan git history BEFORE making the repo public
```
`vercel.json` serves `site/` with a CSP; `.vercelignore` uploads only `site/` and `vercel.json`. Deploying and going public are manual steps: see DECISIONS.md.

## Scheduled runs
`.github/workflows/weekly-run.yml` (Mondays) and `run-domains.yml` (manual) research and upload `out/` as an artifact; they need the four secrets as repository secrets. SQLite is local, so approvals happen on your machine.
