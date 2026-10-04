// Mark-as-read, kept in this browser only (localStorage), keyed by a hash of
// each source's URL plus its section, so renumbering the README keeps it.
const KEY = "cpe:progress:v1";
const ui = JSON.parse(document.getElementById("ui-copy")?.textContent || "{}");

const load = () => { try { return JSON.parse(localStorage.getItem(KEY) || "{}"); } catch { return {}; } };
const save = (s) => { try { localStorage.setItem(KEY, JSON.stringify(s)); } catch { /* storage blocked */ } };
let state = load();

function refresh() {
  for (const li of document.querySelectorAll("li[data-key]")) {
    const on = Boolean(state[li.dataset.key]);
    li.classList.toggle("is-read", on);
    const box = li.querySelector(".entry-read input");
    if (box) box.checked = on;
  }
  for (const box of document.querySelectorAll("[data-progress-box]")) {
    const total = Number(box.dataset.total) || 0;
    const done = document.querySelectorAll("article li.is-read[data-key]").length;
    box.hidden = false;
    box.querySelector("[data-progress-count]").textContent = String(done);
    box.querySelector(".meter > i").style.width = total ? `${(100 * done) / total}%` : "0";
  }
  for (const m of document.querySelectorAll("[data-meter]")) {
    const slug = m.dataset.meter;
    const total = Number(m.dataset.total) || 0;
    const done = Object.keys(state).filter((k) => k.endsWith(`@${slug}`)).length;
    m.hidden = done === 0;
    m.querySelector("i").style.width = total ? `${Math.min(100, (100 * done) / total)}%` : "0";
  }
}

for (const li of document.querySelectorAll("li[data-key]")) {
  const head = li.querySelector(".entry-head");
  if (!head) continue;
  const label = document.createElement("label");
  label.className = "entry-read";
  const box = document.createElement("input");
  box.type = "checkbox";
  box.addEventListener("change", () => {
    if (box.checked) state[li.dataset.key] = 1;
    else delete state[li.dataset.key];
    save(state);
    refresh();
    document.dispatchEvent(new CustomEvent("progress-change"));
  });
  label.append(box, document.createTextNode(` ${ui.read || "Read"}`));
  head.append(label);
}

window.addEventListener("storage", (e) => { if (e.key === KEY) { state = load(); refresh(); } });
refresh();
