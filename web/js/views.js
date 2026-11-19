import { h, s, clear, echo, STATUS_LABEL, VERDICT_LABEL, fmt, secs, plural, reveal } from "./dom.js";
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

const ICONS = {
  search: '<circle cx="11" cy="11" r="6"/><path d="m20 20-4.2-4.2"/>',
  scale: '<path d="M12 4v16M5 20h14"/><path d="M5 8h14"/><path d="m5 8-3 6a3 3 0 0 0 6 0zM19 8l-3 6a3 3 0 0 0 6 0z"/>',
  mail: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 7 9 6 9-6"/>',
  arrow: '<path d="M5 12h14M13 6l6 6-6 6"/>',
};
function icon(name) {
  const svg = s("svg", { class: "i", viewBox: "0 0 24 24", "aria-hidden": "true" });
  const tmp = new DOMParser().parseFromString(`<svg xmlns="http://www.w3.org/2000/svg">${ICONS[name]}</svg>`, "image/svg+xml").documentElement;
  [...tmp.childNodes].forEach((n) => svg.append(document.importNode(n, true)));
  return svg;
}

function detail(no, title, lede, chart) {
  return h("section", { class: "detail reveal", "aria-labelledby": `h-${no}` },
    h("div", { class: "claim" }, h("p", { class: "sec-no", text: `0${no}` }), h("h2", { id: `h-${no}`, text: title }), lede ? h("p", { class: "lede", text: lede }) : null),
    h("div", { class: "chart" }, chart));
}

export function renderHome(root, rows, openAccount) {
  clear(root);
  const m = metrics(rows);
  if (!rows.length) {
    root.append(h("div", { class: "wrap hero" }, h("h1", { text: "No accounts yet." }), h("p", { text: DEMO ? "The demo has no data." : "Run research on a list of domains from the Accounts view." })));
    return;
  }
  const synthetic = rows.some((r) => r.synthetic);
  const mid = ((BASELINE[0] + BASELINE[1]) / 2) * 60;
  const wrap = h("div", { class: "wrap" });

  // hero: the echo stack
  wrap.append(h("section", { class: "hero reveal", "aria-labelledby": "hero-h" },
    echo(secs(m.avg)),
    h("h1", { id: "hero-h", text: `per company, not ${BASELINE[0]} to ${BASELINE[1]} minutes.` }),
    h("p", { text: `${plural(m.n, "company", "companies")} researched, qualified and drafted with no human in the loop. Every decision cites evidence from the company's own pages.` }),
    synthetic ? h("span", { class: "sample", text: "Synthetic sample data: fictional .test companies" }) : null));

  // narrative
  wrap.append(h("section", { class: "philo reveal", "aria-label": "How it works" },
    h("q", {}, "Python decides, Gemini reads, and every claim carries its ", h("em", { text: "evidence" }), "."),
    h("div", { class: "cols3" },
      h("div", {}, h("h3", { text: "Cited, not guessed" }), h("p", { text: "A fact counts only if its exact quote appears on the page. Anything else is dropped before it can score." })),
      h("div", {}, h("h3", { text: "Unknown is not absent" }), h("p", { text: "A blocked page or a silent website widens the score range. It never subtracts points." })),
      h("div", {}, h("h3", { text: "You approve every send" }), h("p", { text: "Drafts wait in the Queue. Your edits are re-checked against every rule and teach the next drafts." })))));

  // asymmetric showcase: rectangle, pill, circle, wide rectangle
  const ov = m.overturned.map((r) => ({ domain: r.domain, label: r.company, before: r.fixed, after: r.final,
    beforeVerdict: VERDICT_LABEL[r.verdict_fixed] || r.verdict_fixed, afterVerdict: VERDICT_LABEL[r.verdict_final] || r.verdict_final }));
  const drafted = m.sent.length + m.pending.length;
  wrap.append(h("div", { class: "shell" },
    h("section", { class: "tile t-rect reveal", "aria-labelledby": "t1" }, h("h2", { id: "t1", text: "Hours of research become minutes of review." }),
      h("p", { class: "lede", text: `Mean run time per company across ${plural(m.n, "company", "companies")}, against the ${BASELINE[0]} to ${BASELINE[1]} minutes the Growth Lead spends by hand.` }),
      h("div", { class: "chart-in" }, barRows([
        { label: "By hand", sub: `${BASELINE[0]}–${BASELINE[1]} min each`, value: mid, display: `${(mid / 60).toFixed(1)} min (midpoint)`, cls: "hollow" },
        { label: "Autopilot", sub: "mean of this run", value: m.avg, display: secs(m.avg) }], BASELINE[1] * 60),
        h("p", { class: "note", text: `One scale: the full track is ${BASELINE[1]} minutes. At the midpoint these ${m.n} companies take ${((mid * m.n) / 3600).toFixed(1)} hours by hand, and took ${((m.avg * m.n) / 60).toFixed(0)} minutes here.` }))),
    h("section", { class: "tile t-pill reveal", tabindex: "0", "aria-label": "Emails sent, awaiting approval and held" },
      h("div", { class: "stack" },
        h("div", {}, h("p", { class: "big", text: String(m.sent.length) }), h("span", { text: "sent to your inbox" })),
        h("div", {}, h("p", { class: "big", text: String(m.pending.length) }), h("span", { text: "awaiting your approval" })),
        h("div", {}, h("p", { class: "big", text: String(m.held.length) }), h("span", { text: "held: failed a rule" }))),
      h("div", { class: "hover-ov", "aria-hidden": "true", text: m.reviewerAvg == null ? "No reviewer scores yet" : `Reviewer average ${fmt(m.reviewerAvg)} of 10` })),
    h("section", { class: "tile t-circle reveal", "aria-label": "Funnel result" },
      h("p", { class: "big", text: `${drafted}/${m.n}` }), h("p", { text: `domains became a sendable email. The rest were screened out, unreadable or had no contact.` })),
    h("section", { class: "tile t-wide reveal", "aria-labelledby": "t4" },
      h("h2", { id: "t4", text: ov.length ? `Research overturned ${plural(ov.length, "verdict")}.` : "Research overturned no verdicts." }),
      h("p", { class: "lede", text: "The agent loop keeps researching while the score range straddles the qualify line at 60." }),
      h("div", { class: "chart-in" }, ov.length ? [rangeChart(ov), h("p", { class: "note", text: "Hollow bar: range from the website alone. Solid bar: after the agent fetched pages or read job boards. Dashed line: qualify at 60." })] : h("p", { class: "empty", text: "Every verdict stood after research in this run." })))));

  // details
  const stages = [
    ["Domains in", m.n, ""], ["Site readable", m.readable.length, "at least one page loaded"], ["Qualified", m.qualified.length, "score line 60 cleared, no disqualifier"],
    ["Contact found", m.withContact.length, "a titled decision-maker with an address"], ["Email drafted", drafted, "passed all validator rules"],
    ["Sent after your approval", m.sent.length, "approved by you, sent to your own inbox"]];
  const reasons = {};
  rows.forEach((r) => { if (r.drop_reason) reasons[r.drop_reason] = (reasons[r.drop_reason] || 0) + 1; });
  wrap.append(detail(1, `${drafted} of ${m.n} became a sendable email.`, "Where companies drop out, and why. Each bar counts companies, drawn against the domains that came in.",
    h("div", {}, barRows(stages.map(([label, v, sub]) => ({ label, sub, value: v, display: String(v) })), Math.max(1, m.n)),
      h("table", { class: "ledger" }, h("caption", { text: "Drop-out reasons" }), h("thead", {}, h("tr", {}, h("th", { text: "Reason" }), h("th", { class: "n", text: "Companies" }))),
        h("tbody", {}, Object.entries(reasons).sort((a, b) => b[1] - a[1]).map(([k, v]) => h("tr", {}, h("td", { text: k }), h("td", { class: "n", text: String(v) }))))))));
  const sh = drafted + m.held.length;
  wrap.append(detail(2, "Every email is scored before you see it.", `Of ${plural(sh, "email")} drafted for qualified companies, reviewer average: ${m.reviewerAvg == null ? "n/a" : fmt(m.reviewerAvg) + " of 10"}.`,
    h("div", {}, m.scored.length ? scoreStrip(m.scored.map((r) => ({ domain: r.domain, label: r.company, score: r.reviewer_avg }))) : h("p", { class: "empty", text: "No reviewed emails yet." }),
      h("p", { class: "note", text: "Each dot is the mean of three reviewer scores (specificity, relevance, reply likelihood). Below 7 the draft is rewritten with the critique, up to four drafts. If none passes the code rules, nothing is sent." }))));
  const needs = rows.filter((r) => r.needs);
  wrap.append(detail(3, needs.length ? `${plural(needs.length, "account")} need${needs.length === 1 ? "s" : ""} you.` : "Nothing needs you.",
    "Drafts to approve, held emails, missing contacts, unreadable sites, and sent emails whose replies are not logged yet.",
    needs.length ? h("ul", { class: "needs" }, needs.map((r) => h("li", { "data-domain": r.domain },
      h("div", {}, h("button", { class: "row-btn", type: "button", onclick: () => openAccount(r.domain), text: r.company }), h("span", { text: r.needs })),
      h("span", { class: "tag " + (r.status === "sent" ? "mute" : "red"), text: STATUS_LABEL[r.status] })))) : h("p", { class: "empty", text: "Nothing needs you." })));

  // service cards
  const card = (ico, title, text, href, cta) => h("a", { class: "svc reveal", href },
    h("span", { class: "ico" }, icon(ico)), h("h3", { text: title }), h("p", { text }), h("span", { class: "cta" }, cta, icon("arrow")));
  wrap.append(h("div", { class: "cards3" },
    card("search", "Research", "Find recently funded companies, read their pages, and keep only facts whose quote is on the page.", "#/accounts", "Open accounts"),
    card("scale", "Qualify", "Score each company against the ICP. A range, not a guess, until the evidence settles it.", "#/pipeline", "Open pipeline"),
    card("mail", "Approve", "Read the draft with its evidence, edit it, rate it, and send it to your own inbox.", "#/queue", "Open queue")));
  root.append(wrap);
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

export async function renderQueue(root, rows, openAccount) {
  clear(root);
  const flagged = await api.flagged().catch(() => []);
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
      h("p", { class: "empty", text: "Nothing is waiting. Run research on the Accounts view." }),
    flaggedBlock(flagged));
}

function flaggedBlock(list) {
  if (!list.length) return null;
  const status = h("p", { class: "saved", role: "status" });
  return h("section", { class: "flagged" }, h("h2", { text: `Flagged leads (${list.length})` }),
    h("p", { class: "note", text: "The rules were unsure which website belongs to these companies. Type the right domain and it is researched like any other." }),
    status,
    h("ul", { class: "needs" }, list.map((f) => {
      const input = h("input", { type: "text", "aria-label": `Domain for ${f.company}`, placeholder: "domain.com", disabled: DEMO });
      const btn = h("button", { class: "btn", type: "button", disabled: DEMO, text: "Use this domain" });
      btn.addEventListener("click", async () => {
        btn.disabled = true;
        try { const r = await api.resolveFlagged(f.key, input.value); await api.run([r.domain]); status.textContent = `${f.company}: researching ${r.domain}. It appears in Accounts when done.`; btn.closest("li").remove(); }
        catch (e) { status.textContent = `${f.company}: ${e.message}`; btn.disabled = false; }
      });
      return h("li", {}, h("div", {}, h("b", { text: f.company }), h("span", { text: `${f.round || ""} · ${f.flag_reason}` }), h("span", { class: "quote", text: f.headline })), h("div", { class: "row" }, input, btn));
    })));
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
