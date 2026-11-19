import { h, clear, STATUS_LABEL, VERDICT_LABEL, fmt, secs } from "./dom.js";
import { rangeBar } from "./charts.js";
import { api, DEMO } from "./api.js";

const drawer = () => document.getElementById("drawer");
const scrim = () => document.getElementById("scrim");
let opener = null;
let onSaved = () => {};
const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

export function setOnSaved(fn) { onSaved = fn; }

export async function openDrawer(domain, tab = "company") {
  opener = document.activeElement;
  const d = drawer();
  clear(d).append(h("div", { class: "d-body", text: "Loading…" }));
  d.hidden = false; scrim().hidden = false;
  document.body.style.overflow = "hidden";
  d.setAttribute("aria-labelledby", "drawer-title");
  d.focus?.();
  try {
    const tr = await api.account(domain);
    build(d, tr, tab);
  } catch (e) {
    clear(d).append(h("div", { class: "d-body" }, h("p", { text: `Could not load ${domain}: ${e.message}` }), h("button", { class: "btn", type: "button", onclick: closeDrawer, text: "Close" })));
  }
  (d.querySelector("[data-first]") || d.querySelector(FOCUSABLE))?.focus();
}

export function closeDrawer() {
  if (drawer().hidden) return;
  drawer().hidden = true; scrim().hidden = true;
  document.body.style.overflow = "";
  if (opener && document.contains(opener)) opener.focus();
}

document.addEventListener("keydown", (e) => {
  const d = drawer();
  if (d.hidden) return;
  if (e.key === "Escape") { e.preventDefault(); closeDrawer(); return; }
  if (e.key !== "Tab") return;
  const f = [...d.querySelectorAll(FOCUSABLE)].filter((n) => n.offsetParent !== null);
  if (!f.length) return;
  const first = f[0], last = f[f.length - 1];
  if (!d.contains(document.activeElement)) { e.preventDefault(); first.focus(); }
  else if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
  else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
});
document.addEventListener("click", (e) => { if (e.target === scrim()) closeDrawer(); });

const TABS = [["company", "Company"], ["person", "Person"], ["email", "Email"], ["activity", "Activity"]];

function build(d, tr, tab = "company") {
  const body = h("div", { class: "d-body", id: "d-panel", role: "tabpanel", tabindex: "0" });
  const tabs = h("div", { class: "tabs", role: "tablist", "aria-label": "Account sections" });
  const show = (key) => {
    tabs.querySelectorAll("button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === key)));
    clear(body);
    body.setAttribute("aria-labelledby", "tab-" + key);
    ({ company: pCompany, person: pPerson, email: pEmail, activity: pActivity })[key](body, tr);
    body.append(reviewForm(tr));
  };
  TABS.forEach(([k, label], i) => tabs.append(h("button", { type: "button", role: "tab", id: "tab-" + k, "data-tab": k, ...(i === 0 ? { "data-first": "" } : {}), "aria-selected": String(i === 0), "aria-controls": "d-panel",
    onclick: () => show(k), onkeydown: (e) => {
      const btns = [...tabs.querySelectorAll("button")]; const at = btns.indexOf(e.currentTarget);
      if (e.key === "ArrowRight" || e.key === "ArrowLeft") { e.preventDefault(); const n = btns[(at + (e.key === "ArrowRight" ? 1 : btns.length - 1)) % btns.length]; n.focus(); n.click(); }
    }, text: label })));
  clear(d).append(h("div", { class: "d-head" },
    h("div", { class: "d-top" }, h("div", {}, h("h2", { id: "drawer-title", text: (tr.profile && tr.profile.name) || tr.domain }),
      h("p", { text: `${tr.domain} · ${STATUS_LABEL[tr.status] || tr.status}${tr.profile && tr.profile.one_liner ? " · " + tr.profile.one_liner : ""}` })),
      h("button", { class: "btn alt", type: "button", onclick: closeDrawer, "aria-label": "Close account panel", text: "Close" })), tabs), body);
  show(tab);
}

const kv = (pairs) => h("dl", { class: "kv" }, pairs.filter(Boolean).flatMap(([k, v]) => [h("dt", { text: k }), h("dd", {}, v == null || v === "" ? "n/a" : v)]));

function pCompany(root, tr) {
  const fin = tr.qualify_final || {};
  const fix = tr.qualify_fixed || {};
  const over = tr.verdict_fixed && tr.verdict_fixed !== tr.verdict_final;
  root.append(h("section", {}, h("h3", { text: "Verdict" }),
    kv([["Final", `${VERDICT_LABEL[tr.verdict_final] || "n/a"}, score ${fin.low}${fin.low === fin.high ? "" : "–" + fin.high} of 100`],
      ["Before research", `${VERDICT_LABEL[tr.verdict_fixed] || "n/a"}, score ${fix.low}${fix.low === fix.high ? "" : "–" + fix.high}${over ? " (overturned)" : ""}`],
      ["Caps", (fin.caps || []).map((c) => `${c.cap.replace(/_/g, " ")} (max ${c.max})`).join("; ") || "none"],
      ["Disqualifiers", (fin.disqualifiers || []).map((c) => `${c.reason.replace(/_/g, " ")}${c.detail ? " – " + c.detail : ""}`).join("; ") || "none"]]),
    fin.low != null ? h("div", { class: "chart-box" }, rangeBar(fin.low, fin.high)) : null));
  const sig = fin.signals || [];
  if (sig.length) {
    root.append(h("section", {}, h("h3", { text: "Signals" }), h("div", { class: "table-scroll" }, h("table", { class: "ledger" },
      h("thead", {}, h("tr", {}, ["Signal", "Answer", "Points", "Evidence"].map((t, i) => h("th", { class: i === 2 ? "n" : "", text: t })))),
      h("tbody", {}, sig.map((x) => h("tr", {}, h("td", { text: x.signal.replace(/_/g, " ") + (x.external ? " (external)" : "") }),
        h("td", { text: x.status === "unknown" ? "unknown" : x.bucket.replace(/_/g, " ") }),
        h("td", { class: "n", text: x.points == null ? `? / ${x.max}` : `${x.points} / ${x.max}` }),
        h("td", { text: (x.evidence_ids || []).join(", ") || x.note || "" }))))))));
  }
  const ev = tr.evidence || [];
  root.append(h("section", {}, h("h3", { text: `Evidence ledger (${ev.length})` }), ev.length ? h("div", { class: "table-scroll" }, h("table", { class: "ledger" },
    h("thead", {}, h("tr", {}, ["ID", "Topic", "Claim and exact quote"].map((t) => h("th", { text: t })))),
    h("tbody", {}, ev.map((e) => h("tr", {}, h("td", { text: e.id }), h("td", { text: e.topic }), h("td", {}, e.claim, h("div", { class: "quote", text: `“${e.quote}”` }), h("div", { class: "quote", text: e.url }))))))) : h("p", { class: "empty", text: "No verified evidence. Unreadable pages never count as evidence." })));
  const pages = tr.scrape || [];
  if (pages.length) root.append(h("section", {}, h("h3", { text: "Pages read" }), kv(pages.map((p) => [p.path, `${p.outcome}${p.outcome === "OK" ? "" : " (unknown, not counted as absent)"}`]))));
}

function pPerson(root, tr) {
  const c = tr.contact;
  if (!c) { root.append(h("section", {}, h("h3", { text: "Person" }), h("p", { class: "empty", text: "No contact was looked up: the company did not qualify." }))); return; }
  const p = c.person;
  if (!p) { root.append(h("section", {}, h("h3", { text: "Person" }), h("p", { class: "empty", text: `No contact: ${c.note}.` }))); return; }
  const link = p.linkedin && /^https:\/\//.test(p.linkedin) ? h("a", { href: p.linkedin, rel: "noopener noreferrer", target: "_blank", text: p.linkedin }) : p.linkedin;
  root.append(h("section", {}, h("h3", { text: "Person" }),
    kv([["Name", p.name], ["Title", p.title], ["Email", p.email], ["LinkedIn", link || null], ["Source", p.source], ["Confidence", p.confidence != null ? String(p.confidence) : null]])),
    h("section", {}, h("h3", { text: "Why this person" }),
      kv([["Headcount", tr.profile && tr.profile.headcount != null ? String(tr.profile.headcount) : "unknown (treated as 51–200)"], ["Role order", c.order.join(" → ")], ["Chosen role", p.role], ["How found", c.note]]),
      h("p", { class: "note", text: "Sales, marketing and HR titles are dropped. At 50 staff or fewer the founder or CEO comes first, then the CTO. Between 51 and 200, or when unknown, security/GRC leads, then CTO, then founder. Above 200, security/GRC, then CTO." })));
}

function pEmail(root, tr) {
  const em = tr.email;
  if (!em) { root.append(h("section", {}, h("h3", { text: "Email" }), h("p", { class: "empty", text: "No email was drafted for this account." }))); return; }
  const b = em.best;
  const pending = tr.approval && tr.approval.status === "pending" && !DEMO;
  if (b && pending) {
    root.append(approvalForm(tr, b));
  } else if (b) {
    const r = b.review || {};
    root.append(h("section", {}, h("h3", { text: "Email" }), kv([["Subject", b.subject], ["Intended recipient", tr.intended]]), h("div", { class: "email-body", text: b.body })),
      h("section", {}, h("h3", { text: "Reviewer" }), kv([["Specificity", `${r.specificity} of 10`], ["Relevance", `${r.relevance} of 10`], ["Reply likelihood", `${r.reply_likelihood} of 10`], ["Average", `${fmt(r.avg)} of 10 (rewrite below 7)`], ["Critique", r.critique]])));
    if (tr.gmail_link && !DEMO) root.append(h("p", { class: "note" }, h("a", { href: tr.gmail_link, rel: "noopener noreferrer", target: "_blank", text: "Open in Gmail compose (to your own inbox)" })));
  } else root.append(h("section", {}, h("h3", { text: "Email held" }), h("p", { text: "No draft passed validation, so nothing was sent." })));
  root.append(h("section", {}, h("h3", { text: `Drafts (${em.drafts.length})` }), h("ol", {}, em.drafts.map((dr) => h("li", { class: "note" },
    h("b", { text: `Draft ${dr.n}: ${dr.passed ? "passed" : "failed"}` }), dr.code_failures.length ? ` – ${dr.code_failures.join("; ")}` : dr.review ? ` – reviewer min ${dr.review.min}` : "")))));
}

function approvalForm(tr, b) {
  const r = b.review || {};
  const subject = h("input", { id: "ap-subject", type: "text", maxlength: "200" }); subject.value = b.subject;
  const body = h("textarea", { id: "ap-body", rows: "10", maxlength: "3000" }); body.value = b.body;
  const words = h("p", { class: "saved", id: "ap-words" });
  const count = () => { const n = (body.value.match(/\S+/g) || []).length; words.textContent = `${n} of 110 words, ${(body.value.match(/\?/g) || []).length} question mark(s)`; };
  body.addEventListener("input", count); count();
  const rating = h("select", { id: "ap-rating" }, h("option", { value: "", text: "No rating" }), [1, 2, 3, 4, 5].map((n) => h("option", { value: String(n), text: `${n} of 5` })));
  const note = h("input", { id: "ap-note", type: "text", maxlength: "500", placeholder: "Why you edited it or rejected it" });
  const errs = h("ul", { class: "errors", hidden: true, role: "alert" });
  const status = h("p", { class: "saved", role: "status" });
  const go = async (kind) => {
    errs.hidden = true; clear(errs); status.textContent = kind === "approve" ? "Sending to your inbox…" : "Rejecting…";
    const rt = rating.value ? Number(rating.value) : null;
    try {
      if (kind === "approve") await api.approve(tr.domain, { subject: subject.value, body: body.value, rating: rt, note: note.value });
      else await api.reject(tr.domain, { reason: note.value, rating: rt });
      status.textContent = kind === "approve" ? "Sent to your own inbox." : "Rejected.";
      onSaved(); setTimeout(() => openDrawer(tr.domain, "email"), 600);
    } catch (e) {
      status.textContent = `Not done: ${e.message}`;
      (e.failures || []).forEach((f) => errs.append(h("li", { text: f }))); errs.hidden = !(e.failures || []).length;
      okBtn.disabled = noBtn.disabled = false;
    }
  };
  const okBtn = h("button", { class: "btn", type: "button", text: "Approve and send to my inbox", onclick: () => { okBtn.disabled = noBtn.disabled = true; go("approve"); } });
  const noBtn = h("button", { class: "btn alt", type: "button", text: "Reject", onclick: () => { okBtn.disabled = noBtn.disabled = true; go("reject"); } });
  return h("section", {}, h("h3", { text: "Draft awaiting your approval" }),
    kv([["To (intended)", tr.intended || "n/a"], ["Reviewer", `${fmt(r.avg)} of 10. ${r.critique || ""}`]]),
    h("div", { class: "field" }, h("label", { for: "ap-subject", text: "Subject" }), subject),
    h("div", { class: "field" }, h("label", { for: "ap-body", text: "Body (edit freely; edits are re-checked against every rule)" }), body, words),
    h("div", { class: "field" }, h("label", { for: "ap-rating", text: "Rating" }), rating),
    h("div", { class: "field" }, h("label", { for: "ap-note", text: "Note (teaches the next drafts)" }), note),
    errs, h("div", { class: "actions" }, okBtn, noBtn, status),
    h("p", { class: "note", text: "The email goes to your own inbox only. The intended recipient is named at the bottom so you can forward it by hand." }));
}

function pActivity(root, tr) {
  const ev = [];
  const sc = tr.scrape || [];
  ev.push(["Scraped pages", `${sc.filter((p) => p.outcome === "OK").length} of ${sc.length} readable. ` + sc.filter((p) => p.outcome !== "OK").map((p) => `${p.path} ${p.outcome}`).join(", ")]);
  ev.push(["Extracted facts", `${(tr.evidence || []).length} verified, ${(tr.rejected_facts || []).length} dropped because the quote was not on the page.`]);
  const fx = tr.qualify_fixed;
  if (fx) ev.push(["Qualified (website only)", `${VERDICT_LABEL[fx.verdict]}, score ${fx.low}–${fx.high}`]);
  ((tr.agent || {}).steps || []).forEach((s) => ev.push(s.stopped ? ["Agent stopped", s.stopped, true] : [`Agent: ${s.tool}`, `${s.argument} – ${s.reason}. Score ${(s.before || []).join("–")} → ${(s.after || []).join("–") || "n/a"}${s.error ? " (" + s.error + ")" : ""}`]));
  if (tr.verdict_final) ev.push(["Final verdict", VERDICT_LABEL[tr.verdict_final], tr.verdict_fixed !== tr.verdict_final]);
  if (tr.contact) ev.push(["Contact", tr.contact.person ? `${tr.contact.person.name}, ${tr.contact.person.title} (${tr.contact.person.source})` : tr.contact.note, !tr.contact.person]);
  (tr.pains || []).forEach((p, i) => ev.push([`Pain point ${i + 1}`, `${p.pain} (${(p.evidence_ids || []).join(", ")})`]));
  if (tr.email) ev.push(["Drafted", `${tr.email.drafts.length} draft(s), ${tr.email.rewrites} rewrite(s)`, !tr.email.best]);
  if (tr.approval) ev.push(["Approval", `${tr.approval.status}${tr.approval.rating ? ", rated " + tr.approval.rating + " of 5" : ""}`, tr.approval.status === "pending"]);
  if (tr.send) ev.push(["Sent to your inbox", "Intended recipient is named at the bottom of the email."]);
  if (tr.error) ev.push(["Error", tr.error, true]);
  ev.push(["Finished", `Status ${STATUS_LABEL[tr.status] || tr.status} in ${secs(tr.seconds)}`]);
  root.append(h("section", {}, h("h3", { text: "Activity" }), h("ol", { class: "timeline" }, ev.map(([t, d, flag]) => h("li", { class: flag ? "flag" : "" }, h("b", { text: t }), d)))));
}

function reviewForm(tr) {
  const hm = tr.human || {};
  const sel = (id, label, opts, val) => h("div", { class: "field" }, h("label", { for: id, text: label }), h("select", { id, disabled: DEMO }, opts.map(([v, t]) => h("option", { value: v, text: t, selected: v === (val || "") }))));
  const stage = sel("rv-stage", "Stage", [["", "Auto"], ["contacted", "Contacted"], ["replied", "Replied"], ["meeting", "Meeting booked"], ["dead", "Closed"]], hm.stage);
  const agrees = sel("rv-agrees", "Lead agrees with the verdict", [["", "Not reviewed"], ["yes", "Yes"], ["no", "No"]], hm.lead_agrees);
  const edit = sel("rv-edit", "Edit level before use", [["", "Not reviewed"], ["none", "None"], ["light", "Light"], ["heavy", "Heavy"], ["rewrote", "Rewrote"]], hm.edit_level);
  const replied = sel("rv-replied", "Prospect replied", [["", "Unknown"], ["yes", "Yes"], ["no", "No"]], hm.replied);
  const notes = h("textarea", { id: "rv-notes", maxlength: "2000", disabled: DEMO }); notes.value = hm.notes || "";
  const status = h("p", { class: "saved", role: "status" });
  const btn = h("button", { class: "btn", type: "button", disabled: DEMO, text: "Save review" });
  btn.addEventListener("click", async () => {
    btn.disabled = true; status.textContent = "Saving…";
    try {
      await api.review(tr.domain, { stage: stage.querySelector("select").value, lead_agrees: agrees.querySelector("select").value, edit_level: edit.querySelector("select").value,
        replied: replied.querySelector("select").value, notes: notes.value });
      status.textContent = "Saved to review.csv."; onSaved();
    } catch (e) { status.textContent = `Not saved: ${e.message}`; }
    btn.disabled = DEMO;
  });
  return h("form", { class: "review", onsubmit: (e) => e.preventDefault(), "aria-label": "Review" },
    h("h3", { class: "wide", text: "Your review" }), stage, agrees, edit, replied,
    h("div", { class: "field wide" }, h("label", { for: "rv-notes", text: "Notes" }), notes),
    h("div", { class: "wide" }, btn, " ", status),
    DEMO ? h("p", { class: "saved wide", text: "Read-only demo: reviews cannot be saved here." }) : null);
}
