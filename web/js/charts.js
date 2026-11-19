// Charts are drawn to scale from the data: bar length = value / axis maximum.
import { h, s, fmt } from "./dom.js";

// Horizontal bar rows. rows: [{label, sub, value, display, cls}], max = axis max.
export function barRows(rows, max) {
  const wrap = h("div", { class: "bars" });
  for (const r of rows) {
    const frac = max ? Math.max(0, Math.min(1, r.value / max)) : 0;
    const fill = h("div", { class: "fill " + (r.cls || ""), role: "presentation" });
    fill.style.width = `${frac * 100}%`;
    const val = h("span", { class: "val", text: r.display });
    // keep the label readable: inside the bar when it is long, outside when short
    if (frac > 0.78) { val.style.right = `${(1 - frac) * 100}%`; val.style.paddingRight = "8px"; if (!(r.cls || "").includes("hollow")) val.style.color = "#fff"; } else { val.style.left = `${frac * 100}%`; }
    wrap.append(h("div", { class: "bar-row", ...(r.domain ? { "data-domain": r.domain } : {}) },
      h("div", { class: "lab" }, r.label, r.sub ? h("small", { text: r.sub }) : null),
      h("div", { class: "track", role: "img", "aria-label": `${r.label}: ${r.display}` }, fill, val)));
  }
  return wrap;
}

// Score range (low to high) on a 0..100 axis with the qualify line at 60.
export function rangeChart(items, line = 60) {
  const W = 640, L = 150, R = 24, rowH = 54, top = 28;
  const H = top + items.length * rowH + 18;
  const x = (v) => L + (v / 100) * (W - L - R);
  const svg = s("svg", { class: "svg-chart", viewBox: `0 0 ${W} ${H}`, role: "img",
    "aria-label": "Score range before and after research, against the qualify line at " + line });
  for (let v = 0; v <= 100; v += 20) {
    svg.append(s("line", { x1: x(v), x2: x(v), y1: top - 6, y2: H - 18, stroke: "#cfcfcf", "stroke-width": 1 }));
    svg.append(s("text", { x: x(v), y: H - 4, "text-anchor": "middle" }, String(v)));
  }
  svg.append(s("line", { x1: x(line), x2: x(line), y1: top - 12, y2: H - 18, stroke: "#c8201a", "stroke-width": 2 }));
  svg.append(s("text", { x: x(line), y: top - 16, "text-anchor": "middle", class: "t-red" }, `qualify at ${line}`));
  items.forEach((it, i) => {
    const y = top + i * rowH;
    const g = s("g", { "data-domain": it.domain, tabindex: "0", role: "group", "aria-label": `${it.label}: before ${it.before[0]} to ${it.before[1]}, after ${it.after[0]} to ${it.after[1]}` });
    g.append(s("rect", { x: 0, y: y - 4, width: W, height: rowH - 4, fill: "transparent" }));
    g.append(s("text", { x: 0, y: y + 14, class: "t-strong" }, it.label));
    g.append(s("text", { x: 0, y: y + 30 }, `${it.beforeVerdict} → ${it.afterVerdict}`));
    const bar = (rng, yy, filled) => s("rect", { x: x(rng[0]), y: yy, width: Math.max(3, x(rng[1]) - x(rng[0])), height: 12,
      fill: filled ? "#111" : "#fff", stroke: "#111", "stroke-width": 2 });
    g.append(bar(it.before, y, false));
    g.append(bar(it.after, y + 18, true));
    g.append(s("text", { x: Math.min(x(it.before[1]) + 6, W - 70), y: y + 10 }, `before ${it.before[0]}–${it.before[1]}`));
    g.append(s("text", { x: Math.min(x(it.after[1]) + 6, W - 70), y: y + 28, class: "t-strong" }, `after ${it.after[0]}–${it.after[1]}`));
    svg.append(g);
  });
  return svg;
}

// Dot strip on a 0..10 axis with the pass line at 7.
export function scoreStrip(items, pass = 7) {
  const W = 640, L = 150, R = 24, rowH = 30, top = 22;
  const H = top + items.length * rowH + 20;
  const x = (v) => L + (v / 10) * (W - L - R);
  const svg = s("svg", { class: "svg-chart", viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Reviewer score per email against the pass line at " + pass });
  for (let v = 0; v <= 10; v += 2) {
    svg.append(s("line", { x1: x(v), x2: x(v), y1: top - 6, y2: H - 18, stroke: "#cfcfcf" }));
    svg.append(s("text", { x: x(v), y: H - 4, "text-anchor": "middle" }, String(v)));
  }
  svg.append(s("line", { x1: x(pass), x2: x(pass), y1: top - 12, y2: H - 18, stroke: "#c8201a", "stroke-width": 2 }));
  svg.append(s("text", { x: x(pass), y: top - 14, "text-anchor": "middle", class: "t-red" }, `rewrite below ${pass}`));
  items.forEach((it, i) => {
    const y = top + i * rowH + 12;
    const g = s("g", { "data-domain": it.domain, tabindex: "0", role: "group", "aria-label": `${it.label}: ${fmt(it.score)} of 10` });
    g.append(s("text", { x: 0, y: y + 4 }, it.label));
    g.append(s("line", { x1: x(0), x2: x(it.score), y1: y, y2: y, stroke: "#111", "stroke-width": 2 }));
    g.append(s("circle", { cx: x(it.score), cy: y, r: 6, fill: it.score >= pass ? "#111" : "#c8201a" }));
    g.append(s("text", { x: x(it.score) + 12, y: y + 4, class: "t-strong" }, fmt(it.score)));
    svg.append(g);
  });
  return svg;
}

// Score range bar for the drawer (single account).
export function rangeBar(low, high, line = 60) {
  const W = 420, H = 46;
  const x = (v) => 4 + (v / 100) * (W - 8);
  const svg = s("svg", { class: "svg-chart", viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": `Score ${low} to ${high} of 100, qualify line ${line}` });
  svg.append(s("rect", { x: 4, y: 14, width: W - 8, height: 12, fill: "#f3f3f1" }));
  svg.append(s("rect", { x: x(low), y: 14, width: Math.max(3, x(high) - x(low)), height: 12, fill: "#fff", stroke: "#111", "stroke-width": 2 }));
  svg.append(s("rect", { x: x(0), y: 14, width: Math.max(0, x(low) - x(0)), height: 12, fill: "#111" }));
  svg.append(s("line", { x1: x(line), x2: x(line), y1: 6, y2: 34, stroke: "#c8201a", "stroke-width": 2 }));
  svg.append(s("text", { x: x(line), y: 45, "text-anchor": "middle", class: "t-red" }, String(line)));
  svg.append(s("text", { x: 4, y: 45 }, "0"));
  svg.append(s("text", { x: W - 4, y: 45, "text-anchor": "end" }, "100"));
  return svg;
}
