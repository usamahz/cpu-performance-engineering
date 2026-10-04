// Styled tooltips and arrow-key traversal over chart marks. Without this the
// marks still carry native <title> tooltips and every value is in a table.
const tip = document.createElement("div");
tip.className = "tooltip";
tip.hidden = true;
tip.setAttribute("role", "status");
document.body.append(tip);

const show = (mark) => {
  tip.textContent = mark.dataset.tip || "";
  tip.hidden = false;
  const r = mark.getBoundingClientRect();
  const w = tip.offsetWidth;
  tip.style.left = `${Math.max(8, Math.min(innerWidth - w - 8, r.left + r.width / 2 - w / 2))}px`;
  tip.style.top = `${Math.max(8, r.top - tip.offsetHeight - 8)}px`;
};
const hide = () => { tip.hidden = true; };

for (const chart of document.querySelectorAll(".chart")) {
  const marks = Array.from(chart.querySelectorAll(".mark"));
  marks.forEach((m, i) => {
    m.addEventListener("mouseenter", () => show(m));
    m.addEventListener("mouseleave", hide);
    m.addEventListener("focus", () => show(m));
    m.addEventListener("blur", hide);
    m.addEventListener("keydown", (e) => {
      const d = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
      if (d) { e.preventDefault(); marks[(i + d + marks.length) % marks.length].focus(); }
    });
  });
}
// Focusing a mark scrolls it into view; keep its tooltip with it.
addEventListener("scroll", () => {
  const a = document.activeElement;
  if (a && a.classList && a.classList.contains("mark")) show(a);
  else hide();
}, { passive: true });
