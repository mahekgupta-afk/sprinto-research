import { h, clear, wireHighlight } from "./dom.js";
import { api, DEMO } from "./api.js";
import { renderHome, renderQueue, renderAccounts, renderPipeline } from "./views.js";
import { openDrawer, setOnSaved } from "./drawer.js";

const main = document.getElementById("main");
let rows = [];
let pollTimer = null;

function route() { const r = (location.hash.match(/^#\/(\w+)/) || [])[1]; return ["home", "queue", "accounts", "pipeline"].includes(r) ? r : "home"; }

async function draw() {
  const r = route();
  document.querySelectorAll("#nav a").forEach((a) => (a.dataset.route === r ? a.setAttribute("aria-current", "page") : a.removeAttribute("aria-current")));
  document.title = `${{ home: "Home", queue: "Queue", accounts: "Accounts", pipeline: "Pipeline" }[r]} · Outbound Autopilot`;
  if (r === "home") renderHome(main, rows, openDrawer);
  else if (r === "queue") await renderQueue(main, rows, openDrawer);
  else if (r === "accounts") renderAccounts(main, rows, openDrawer, startPolling);
  else renderPipeline(main, rows, openDrawer);
}

async function load() {
  try { rows = await api.accounts(); }
  catch (e) { rows = []; clear(main).append(h("p", { class: "empty", text: `Could not load accounts: ${e.message}` })); return; }
  const q = rows.filter((x) => x.status === "pending_approval").length;
  document.getElementById("qcount").textContent = q ? String(q) : "";
  draw();
}

function startPolling() {
  clearInterval(pollTimer);
  pollTimer = setInterval(async () => {
    const j = await api.job().catch(() => ({ state: "idle" }));
    const st = document.getElementById("run-status");
    if (st && j.state === "running") st.textContent = `Researching… ${j.done} of ${j.total} done${j.current ? " (" + j.current + ")" : ""}`;
    if (j.state !== "running") {
      clearInterval(pollTimer);
      if (st && j.state === "error") st.textContent = `Run stopped: ${j.error}`;
      await load();
    } else { try { rows = await api.accounts(); } catch (e) { /* keep last rows */ } }
  }, 2500);
}

const mode = document.getElementById("mode");
if (DEMO) mode.append(h("strong", { text: "Read-only demo" }), " · contact details hidden");
else mode.textContent = "Local · emails go only to your own inbox";

setOnSaved(load);
wireHighlight(document.body);
window.addEventListener("hashchange", () => { draw(); window.scrollTo(0, 0); });
load();
