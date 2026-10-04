// Search over /search.json: every section, part, source, benchmark and
// rejected candidate. Every term must match; title matches rank first.
const app = document.getElementById("search-app");
const input = app.querySelector("input");
const out = app.querySelector("[data-results]");
const status = app.querySelector("[data-status]");
const ui = JSON.parse(document.getElementById("ui-copy")?.textContent || "{}");
const BONUS = { benchmark: 1, section: 0.5, part: 0.5 };
let index = [];

const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text) e.textContent = text; return e; };

function render(q) {
  const terms = q.toLowerCase().split(/\s+/).filter(Boolean);
  out.textContent = "";
  if (!terms.length) { status.textContent = `${index.length} ${ui.indexed || "items indexed"}`; return; }
  const hits = [];
  for (const h of index) {
    const t = h.t.toLowerCase(), x = `${h.x} ${h.h || ""}`.toLowerCase();
    let score = 0, ok = true;
    for (const term of terms) {
      if (t.includes(term)) score += 3;
      else if (x.includes(term)) score += 1;
      else { ok = false; break; }
    }
    if (ok) hits.push([score + (BONUS[h.y] || 0), h]);
  }
  hits.sort((a, b) => b[0] - a[0]);
  status.textContent = `${hits.length} ${ui.results || "results"}`;
  for (const [, h] of hits.slice(0, 60)) {
    const li = el("li");
    const head = el("div", "entry-head");
    head.append(el("span", `type${h.y === "benchmark" ? " bench" : ""}`, ui[`type_${h.y}`] || h.y));
    const a = el("a", "t", h.t); a.href = h.u; head.append(a);
    if (h.k) head.append(el("span", `badge badge-${h.k}`, h.k === "unlinked" ? ui.no_link || "no link" : h.k));
    li.append(head);
    if (h.x) li.append(el("p", "x", h.x));
    if (h.i) li.append(el("p", "in", `${ui.in || "in"} ${h.i}`));
    out.append(li);
  }
}

const q0 = new URLSearchParams(location.search).get("q") || "";
input.value = q0;
fetch("/search.json").then((r) => r.json()).then((rows) => { index = rows; render(input.value); });
input.addEventListener("input", () => {
  const u = new URL(location.href);
  if (input.value) u.searchParams.set("q", input.value); else u.searchParams.delete("q");
  history.replaceState(null, "", u);
  render(input.value);
});
