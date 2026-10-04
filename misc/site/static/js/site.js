// One small entry module. Every page works without it; it only adds what
// needs a script, and loads the larger pieces only on pages that use them.

const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
const ui = JSON.parse(document.getElementById("ui-copy")?.textContent || "{}");

// Copy buttons: the text to copy is in data-copy.
for (const btn of $$("[data-copy]")) {
  btn.hidden = false;
  btn.addEventListener("click", async () => {
    const label = btn.textContent;
    try {
      await navigator.clipboard.writeText(btn.dataset.copy);
      btn.dataset.done = "";
      btn.textContent = ui.copied || "Copied";
    } catch {
      btn.textContent = ui.copy_failed || "Select and copy";
    }
    setTimeout(() => { btn.textContent = label; delete btn.dataset.done; }, 1600);
  });
}

if (document.querySelector("[data-entry], [data-meter]")) import("./progress.js");
if (document.querySelector("[data-filter-for]")) import("./filter.js");
if (document.querySelector("[role=tablist]")) import("./tabs.js");
if (document.querySelector(".chart .mark")) import("./tooltip.js");
if (document.getElementById("search-app")) import("./search.js");
if (location.pathname === "/" && location.hash.length > 1) import("./anchors.js");
