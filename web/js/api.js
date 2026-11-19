// Local mode talks to app.py. Any other host is the read-only public demo reading static JSON.
export const DEMO = !["localhost", "127.0.0.1", "[::1]"].includes(location.hostname);

async function getJSON(url) {
  const r = await fetch(url, { headers: { Accept: "application/json" } });
  if (!r.ok) throw new Error(`${r.status} ${url}`);
  return r.json();
}
async function postJSON(url, body) {
  const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) { const e = new Error(j.error || `HTTP ${r.status}`); e.failures = j.failures || []; throw e; }
  return j;
}

export const api = {
  accounts: () => getJSON(DEMO ? "data/accounts.json" : "/api/accounts"),
  account: (d) => getJSON(DEMO ? `data/account/${encodeURIComponent(d)}.json` : `/api/account/${encodeURIComponent(d)}`),
  job: () => (DEMO ? Promise.resolve({ state: "idle" }) : getJSON("/api/job")),
  run: (domains) => { if (DEMO) throw new Error("read-only demo"); return postJSON("/api/run", { domains }); },
  approve: (d, body) => { if (DEMO) throw new Error("read-only demo"); return postJSON(`/api/account/${encodeURIComponent(d)}/approve`, body); },
  reject: (d, body) => { if (DEMO) throw new Error("read-only demo"); return postJSON(`/api/account/${encodeURIComponent(d)}/reject`, body); },
  flagged: () => (DEMO ? Promise.resolve([]) : getJSON("/api/flagged")),
  resolveFlagged: (key, domain) => { if (DEMO) throw new Error("read-only demo"); return postJSON("/api/flagged/resolve", { key, domain }); },
  discover: (limit) => { if (DEMO) throw new Error("read-only demo"); return postJSON("/api/discover", { limit }); },
  review: (d, body) => { if (DEMO) throw new Error("read-only demo"); return postJSON(`/api/account/${encodeURIComponent(d)}/review`, body); },
};
