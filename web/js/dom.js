// Tiny DOM helpers. Text is ALWAYS set with textContent: scraped website text is untrusted.
const SVGNS = "http://www.w3.org/2000/svg";

export function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  setup(el, attrs, kids);
  return el;
}
export function s(tag, attrs, ...kids) {
  const el = document.createElementNS(SVGNS, tag);
  setup(el, attrs, kids);
  return el;
}
function setup(el, attrs, kids) {
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === false || v == null) continue;
    if (k === "class") el.setAttribute("class", v);
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "text") el.textContent = v;
    else el.setAttribute(k, v === true ? "" : String(v));
  }
  for (const kid of kids.flat()) {
    if (kid == null || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
}
export function clear(el) { el.replaceChildren(); return el; }

export const STATUS_LABEL = { sent: "Sent", pending_approval: "Awaiting approval", rejected: "Rejected", held: "Held", not_qualified: "Not qualified", insufficient_data: "Insufficient data", no_contact: "No contact", failed: "Failed" };
export const VERDICT_LABEL = { PRIORITY: "Priority", QUALIFY: "Qualify", NURTURE: "Nurture", REJECT: "Reject", DISQUALIFIED: "Disqualified", INSUFFICIENT_DATA: "Insufficient data" };
export const fmt = (n) => (n == null ? "n/a" : String(Math.round(n * 10) / 10));
export const secs = (n) => (n == null ? "n/a" : n < 90 ? `${Math.round(n)} s` : `${(n / 60).toFixed(1)} min`);
export const plural = (n, one, many) => `${n} ${n === 1 ? one : many || one + "s"}`;

// Hovering or focusing an account highlights it in every view.
export function wireHighlight(root) {
  const on = (e) => {
    const t = e.target.closest && e.target.closest("[data-domain]");
    if (t) setHl(t.dataset.domain, true);
  };
  const off = (e) => {
    const t = e.target.closest && e.target.closest("[data-domain]");
    if (t) setHl(t.dataset.domain, false);
  };
  root.addEventListener("mouseover", on);
  root.addEventListener("mouseout", off);
  root.addEventListener("focusin", on);
  root.addEventListener("focusout", off);
}
export function setHl(domain, yes) {
  document.querySelectorAll("[data-domain]").forEach((n) => n.classList.toggle("hl", yes && n.dataset.domain === domain));
}

const reduce = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;
let io;
export function reveal(root) {
  const items = root.querySelectorAll(".reveal");
  if (reduce() || !("IntersectionObserver" in window)) { items.forEach((n) => n.classList.add("in")); return; }
  io = io || new IntersectionObserver((es) => es.forEach((e) => {
    if (e.isIntersecting) { e.target.classList.add("in"); e.target.classList.remove("pre"); io.unobserve(e.target); }
  }), { threshold: 0.15 });
  items.forEach((n) => { n.classList.add("pre"); io.observe(n); });
}
