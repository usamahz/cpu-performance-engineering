// Filters over lists the page already shows in full. A control names the
// data attribute it matches (data-filter-field), or filters by text, or by
// unread state; items and the groups that hold them hide when nothing matches.
for (const bar of document.querySelectorAll("[data-filter-for]")) {
  const scope = bar.closest("[data-filter-scope]") || bar.closest("article") || document;
  const items = Array.from(scope.querySelectorAll(bar.dataset.filterItems || "li[data-entry]"));
  const groups = bar.dataset.filterGroups ? Array.from(scope.querySelectorAll(bar.dataset.filterGroups)) : [];
  const text = bar.querySelector("[data-filter-text]");
  const unread = bar.querySelector("[data-filter-unread]");
  const fields = Array.from(bar.querySelectorAll("[data-filter-field]"));
  const kind = bar.querySelector("[data-filter-kind]");
  const count = bar.querySelector("[data-filter-count]");
  const hay = new Map(items.map((el) => [el, el.textContent.toLowerCase()]));
  bar.hidden = false;

  const apply = () => {
    const q = (text?.value || "").trim().toLowerCase().split(/\s+/).filter(Boolean);
    let shown = 0;
    for (const el of items) {
      let ok = q.every((t) => hay.get(el).includes(t));
      if (ok && kind?.value) ok = el.dataset.kind === kind.value;
      for (const f of fields) {
        if (!ok || !f.value) continue;
        const values = (el.dataset[f.dataset.filterField] || "").split(" ");
        ok = values.includes(f.value);
      }
      if (ok && unread?.checked) ok = !el.classList.contains("is-read");
      el.hidden = !ok;
      if (ok) shown += 1;
    }
    for (const g of groups) g.hidden = !g.querySelector("[data-entry]:not([hidden]), [data-item]:not([hidden])");
    if (count) count.textContent = `${shown} / ${items.length}`;
  };

  for (const el of [text, unread, kind, ...fields]) el?.addEventListener("input", apply);
  document.addEventListener("progress-change", apply);
  apply();
}
