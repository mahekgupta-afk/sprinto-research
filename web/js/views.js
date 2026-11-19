import { h, clear, STATUS_LABEL, VERDICT_LABEL, fmt, secs, plural, reveal } from "./dom.js";
import { barRows, rangeChart, scoreStrip } from "./charts.js";
import { api, DEMO } from "./api.js";

const BASELINE = [15, 20]; // minutes per company by hand (the Growth Lead's own estimate)

export function metrics(rows) {
  const n = rows.length;
  const secsList = rows.map((r) => r.seconds).filter((x) => x != null);
  const avg = secsList.length ? secsList.reduce((a, b) => a + b, 0) / secsList.length : 0;
  const readable = rows.filter((r) => r.pages_ok > 0);
  const qualified = rows.filter((r) => ["PRIORITY", "QUALIFY"].includes(r.verdict_final));
  const withContact = qualified.filter((r) => r.contact);
  const sent = rows.filter((r) => r.status === "sent");
  const pending = rows.filter((r) => r.status === "pending_approval");
  const held = rows.filter((r) => r.status === "held");
  const overturned = rows.filter((r) => r.overturned);
  const scored = [...sent, ...pending].filter((r) => r.reviewer_avg != null);
  return { n, avg, readable, qualified, withContact, sent, pending, held, overturned, scored,
    reviewerAvg: scored.length ? scored.reduce((a, r) => a + r.reviewer_avg, 0) / scored.length : null };
}

function section(no, title, lede, chart) {
  return h("section", { class: "section grid reveal", "aria-labelledby": `h-${no}` },
    h("div", { class: "claim" }, h("p", { class: "sec-no", text: `0${no}` }), h("h2", { id: `h-${no}`, text: title }), lede ? h("p", { class: "lede", text: lede }) : null),
    h("div", { class: "chart" }, chart));
}

export function renderHome(root, rows, openAccount) {
  clear(root);
  const m = metrics(rows);
  if (!rows.length) {
    root.append(h("div", { class: "hero" }, h("h1", { text: "No accounts yet." }), h("p", { text: DEMO ? "The demo has no data." : "Run research on a list of domains from the Accounts view." })));
    return;
  }
  const synthetic = rows.some((r) => r.synthetic);
  const mid = ((BASELINE[0] + BASELINE[1]) / 2) * 60;
  root.append(h("div", { class: "hero reveal" },
    h("h1", {}, `${secs(m.avg)} per company, not `, h("em", { text: `${BASELINE[0]} to ${BASELINE[1]} minutes` }), "."),
    h("p", { text: `${plural(m.n, "company", "companies")} researched, qualified and drafted with no human in the loop. Every decision below cites evidence from the company's own pages.` }),
    synthetic ? h("span", { class: "sample", text: "Synthetic sample data: fictional .test companies" }) : null));

  // 01 time
  const maxS = BASELINE[1] * 60;
  root.append(section(1, "Hours of research become minutes of review.",
    `Average run time per company across ${plural(m.n, "company", "companies")}, compared with the ${BASELINE[0]} to ${BASELINE[1]} minutes the Growth Lead spends by hand.`,
    h("div", {}, barRows([
      { label: "By hand", sub: `${BASELINE[0]}–${BASELINE[1]} min each`, value: mid, display: `${(mid / 60).toFixed(1)} min (midpoint)` , cls: "hollow" },
      { label: "Autopilot", sub: "mean of this run", value: m.avg, display: secs(m.avg) },
    ], maxS), h("p", { class: "note", text: `Bars share one scale: the full track is ${BASELINE[1]} minutes. At the midpoint, the same ${m.n} companies would take ${((mid * m.n) / 3600).toFixed(1)} hours by hand and took ${((m.avg * m.n) / 60).toFixed(0)} minutes here.` }))));

  // 02 overturned
  const ov = m.overturned.map((r) => ({ domain: r.domain, label: r.company, before: r.fixed, after: r.final,
    beforeVerdict: VERDICT_LABEL[r.verdict_fixed] || r.verdict_fixed, afterVerdict: VERDICT_LABEL[r.verdict_final] || r.verdict_final }));
  root.append(section(2, ov.length ? `Research overturned ${plural(ov.length, "verdict")}.` : "Research overturned no verdicts.",
    "A fixed pipeline scores a thin website once and stops. The agent loop keeps researching while the score range still straddles the qualify line at 60.",
    ov.length ? h("div", {}, rangeChart(ov), h("p", { class: "note", text: "Hollow bar: score range from the website alone (low = proven points, high = if every unknown scored full marks). Solid bar: after the agent fetched pages, searched, or read job boards. A verdict is certain only when the range sits wholly on one side of the line." })) : h("p", { class: "empty", text: "Every verdict stood after research in this run." })));

  // 03 funnel
  const stages = [
    ["Domains in", m.n, ""],
    ["Site readable", m.readable.length, "at least one page loaded"],
    ["Qualified", m.qualified.length, "score line 60 cleared, no disqualifier"],
    ["Contact found", m.withContact.length, "a titled decision-maker with an address"],
    ["Email drafted", m.sent.length + m.pending.length, "passed all validator rules"],
    ["Sent after your approval", m.sent.length, "approved by you, sent to your own inbox"],
  ];
  const reasons = {};
  rows.forEach((r) => { if (r.drop_reason) reasons[r.drop_reason] = (reasons[r.drop_reason] || 0) + 1; });
  root.append(section(3, `${m.sent.length + m.pending.length} of ${m.n} became a sendable email.`, "Where companies drop out, and why. Each bar is a count of companies, drawn against the number of domains that came in.",
    h("div", {}, barRows(stages.map(([label, v, sub]) => ({ label, sub, value: v, display: String(v) })), Math.max(1, m.n)),
      h("table", { class: "ledger" }, h("caption", { text: "Drop-out reasons" }),
        h("thead", {}, h("tr", {}, h("th", { text: "Reason" }), h("th", { class: "n", text: "Companies" }))),
        h("tbody", {}, Object.entries(reasons).sort((a, b) => b[1] - a[1]).map(([k, v]) => h("tr", {}, h("td", { text: k }), h("td", { class: "n", text: String(v) }))))))));

  // 04 sent vs held
  const sh = m.sent.length + m.pending.length + m.held.length;
  root.append(section(4, `${m.sent.length} sent, ${m.pending.length} awaiting you, ${m.held.length} held back.`,
    `Of ${plural(sh, "email")} drafted for qualified companies, an email is drafted only if it passes every code rule, and goes out only after you approve it. Reviewer average: ${m.reviewerAvg == null ? "n/a" : fmt(m.reviewerAvg) + " of 10"}.`,
    h("div", {}, m.scored.length ? scoreStrip(m.scored.map((r) => ({ domain: r.domain, label: r.company, score: r.reviewer_avg }))) : h("p", { class: "empty", text: "No reviewed emails yet." }),
      h("p", { class: "note", text: "Each dot is the mean of three reviewer scores (specificity, relevance, reply likelihood) for the email that was sent. Below 7 the draft is rewritten with the reviewer's critique, up to four drafts. If none passes the code rules, nothing is sent." }))));

  // 05 needs you
  const needs = rows.filter((r) => r.needs);
  const list = needs.length ? h("ul", { class: "needs" }, needs.map((r) => h("li", { "data-domain": r.domain },
    h("div", {}, h("button", { class: "row-btn", type: "button", onclick: () => openAccount(r.domain), text: r.company }), h("span", { text: r.needs })),
    h("span", { class: "tag " + (r.status === "sent" ? "mute" : "red"), text: STATUS_LABEL[r.status] })))) : h("p", { class: "empty", text: "Nothing needs you." });
  root.append(section(5, needs.length ? `${plural(needs.length, "account")} need${needs.length === 1 ? "s" : ""} you.` : "Nothing needs you.",
    "Drafts to approve, held emails, missing contacts, unreadable sites, and sent emails whose replies are not logged yet.", list));
  reveal(root);
}

const FILTER = { q: "", status: "", verdict: "" };
export function renderAccounts(root, rows, openAccount, onRun) {
  clear(root);
  const tbody = h("tbody");
  const count = h("p", { class: "note", role: "status" });
  const draw = () => {
    const q = FILTER.q.toLowerCase();
    const list = rows.filter((r) => (!q || (r.company + " " + r.domain + " " + ((r.contact && r.contact.name) || "")).toLowerCase().includes(q))
      && (!FILTER.status || r.status === FILTER.status) && (!FILTER.verdict || r.verdict_final === FILTER.verdict));
    clear(tbody);
    list.forEach((r) => tbody.append(h("tr", { "data-domain": r.domain },
      h("td", { class: "first" }, h("button", { class: "row-btn", type: "button", onclick: () => openAccount(r.domain), text: r.company }), h("div", { class: "quote", text: r.domain })),
      h("td", { "data-label": "Status" }, h("span", { class: "tag " + (r.status === "sent" ? "solid" : ["held", "failed", "no_contact"].includes(r.status) ? "red" : "mute"), text: STATUS_LABEL[r.status] })),
      h("td", { "data-label": "Verdict" }, VERDICT_LABEL[r.verdict_final] || "n/a", r.overturned ? h("span", { class: "tag red", text: " overturned" }) : null),
      h("td", { class: "n", "data-label": "Score" }, r.final[0] == null ? "n/a" : r.final[0] === r.final[1] ? String(r.final[0]) : `${r.final[0]}–${r.final[1]}`),
      h("td", { "data-label": "Contact" }, r.contact ? `${r.contact.name}, ${r.contact.title}` : "none"),
      h("td", { class: "n", "data-label": "Reviewer" }, r.reviewer_avg == null ? "n/a" : fmt(r.reviewer_avg)),
      h("td", { class: "n", "data-label": "Time" }, secs(r.seconds)))));
    count.textContent = `Showing ${list.length} of ${rows.length}. Score is points proven from evidence out of 100; a range means some signals are still unknown.`;
  };
  const input = (label, key, el) => h("div", { class: "field" }, h("label", { for: "f-" + key, text: label }), el);
  const q = h("input", { id: "f-q", type: "search", placeholder: "Company, domain or contact", value: FILTER.q, oninput: (e) => { FILTER.q = e.target.value; draw(); } });
  const st = h("select", { id: "f-status", onchange: (e) => { FILTER.status = e.target.value; draw(); } }, h("option", { value: "", text: "All statuses" }), Object.entries(STATUS_LABEL).map(([k, v]) => h("option", { value: k, text: v, selected: FILTER.status === k })));
  const vd = h("select", { id: "f-verdict", onchange: (e) => { FILTER.verdict = e.target.value; draw(); } }, h("option", { value: "", text: "All verdicts" }), Object.entries(VERDICT_LABEL).map(([k, v]) => h("option", { value: k, text: v, selected: FILTER.verdict === k })));
  root.append(h("div", { class: "page-h" }, h("h1", { text: "Accounts" }), h("p", { text: "Every company that went through the pipeline, with the reason for each outcome one click away." })),
    runBox(onRun),
    h("div", { class: "filters" }, input("Search", "q", q), input("Status", "status", st), input("Verdict", "verdict", vd)),
    h("div", { class: "table-scroll" }, h("table", { class: "ledger acc-table" },       h("thead", {}, h("tr", {}, ["Company", "Status", "Verdict", "Score", "Contact", "Reviewer", "Time"].map((t, i) => h("th", { class: [3, 5, 6].includes(i) ? "n" : "", text: t })))), tbody)), count);
  draw();
}

function runBox(onRun) {
  const ta = h("textarea", { id: "run-domains", placeholder: "acme.com\nglobex.io", disabled: DEMO, "aria-describedby": "run-help" });
  const status = h("p", { class: "saved", role: "status", id: "run-status" });
  const btn = h("button", { class: "btn", type: "button", disabled: DEMO, text: "Run research" });
  const find = h("button", { class: "btn alt", type: "button", disabled: DEMO, text: "Find recently funded companies" });
  find.addEventListener("click", async () => {
    find.disabled = true; status.textContent = "Searching funding news and checking homepages…";
    try {
      const r = await api.discover(10);
      const ok = r.candidates.filter((c) => c.domain), flagged = r.candidates.filter((c) => !c.domain);
      ta.value = [ta.value.trim(), ...ok.map((c) => c.domain)].filter(Boolean).join("\n");
      status.textContent = `Added ${ok.length} domain(s) to the list${flagged.length ? `; ${flagged.length} need a human to resolve (${flagged.map((c) => c.company).join(", ")})` : ""}. Review, then run.`;
    } catch (e) { status.textContent = `Discovery failed: ${e.message}`; }
    find.disabled = DEMO;
  });
  btn.addEventListener("click", async () => {
    const domains = ta.value.split(/[\s,]+/).filter(Boolean);
    if (!domains.length) { status.textContent = "Enter at least one domain."; return; }
    btn.disabled = true;
    try { await api.run(domains); status.textContent = "Started. This page updates as each company finishes."; onRun(); }
    catch (e) { status.textContent = `Could not start: ${e.message}`; btn.disabled = false; }
  });
  return h("div", { class: "runbox" }, h("label", { class: "lbl", for: "run-domains", text: "Domains to research (one per line)" }), ta,
    h("p", { class: "note", id: "run-help", text: DEMO ? "Read-only demo: runs are disabled." : "Runs in the background. Emails only ever go to your own inbox." }),
    h("div", { class: "row" }, btn, find, status));
}

export function renderQueue(root, rows, openAccount) {
  clear(root);
  const list = rows.filter((r) => r.status === "pending_approval");
  root.append(h("div", { class: "page-h" }, h("h1", { text: "Queue" }), h("p", { text: "Drafts that passed every rule and wait for you. Nothing is sent until you approve. Your edits and ratings teach the next drafts." })),
    list.length ? h("div", { class: "table-scroll" }, h("table", { class: "ledger acc-table" },
      h("thead", {}, h("tr", {}, ["Company", "To", "Subject", "Reviewer", ""].map((t, i) => h("th", { class: i === 3 ? "n" : "", text: t })))),
      h("tbody", {}, list.map((r) => h("tr", { "data-domain": r.domain },
        h("td", { class: "first" }, h("b", { text: r.company }), h("div", { class: "quote", text: r.domain })),
        h("td", { "data-label": "To" }, r.contact ? `${r.contact.name}, ${r.contact.title}` : "n/a"),
        h("td", { "data-label": "Subject" }, r.subject, h("div", { class: "quote", text: r.body_preview })),
        h("td", { class: "n", "data-label": "Reviewer" }, r.reviewer_avg == null ? "n/a" : fmt(r.reviewer_avg)),
        h("td", {}, h("button", { class: "btn", type: "button", onclick: () => openAccount(r.domain, "email"), text: "Review draft" }))))))) :
      h("p", { class: "empty", text: "Nothing is waiting. Run research on the Accounts view." }));
}

const COLUMNS = [["screened_out", "Screened out"], ["needs_you", "Needs you"], ["approval", "Awaiting approval"], ["sent", "Sent"], ["contacted", "Contacted"], ["replied", "Replied"], ["meeting", "Meeting"], ["dead", "Closed"]];
export function renderPipeline(root, rows, openAccount) {
  clear(root);
  root.append(h("div", { class: "page-h" }, h("h1", { text: "Pipeline" }), h("p", { text: "Where each account stands today. Screened-out and needs-you are set by the pipeline; the rest move when you log a stage on the account." })),
    h("div", { class: "board" }, COLUMNS.map(([key, label]) => {
      const cards = rows.filter((r) => r.stage === key);
      return h("section", { class: "col", "aria-label": label }, h("h2", {}, label, h("small", { text: String(cards.length) })),
        cards.length ? cards.map((r) => h("button", { class: "card", type: "button", "data-domain": r.domain, onclick: () => openAccount(r.domain) },
          h("b", { text: r.company }), h("span", { text: r.needs || (VERDICT_LABEL[r.verdict_final] || "") + (r.final[0] != null ? ` · ${r.final[0] === r.final[1] ? r.final[0] : r.final[0] + "–" + r.final[1]}` : "") }))) : h("p", { class: "note", text: "Empty" }));
    })));
}
