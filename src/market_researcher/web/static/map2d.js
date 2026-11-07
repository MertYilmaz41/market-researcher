// 2D opportunity map (SVG): x = demand (reviews, log scale), y = dissatisfaction (% positive, lower is
// higher up), size = estimated revenue (log), color = opportunity score.
// It needs no CDN.
import { mapColor } from "/static/palette.js";
import { percent, t } from "/static/i18n.js";

const NS = "http://www.w3.org/2000/svg";
const PAD = { l: 64, r: 28, t: 26, b: 58 };
const NAMED = 5; // the best games get their name written next to the bubble

function svg(tag, attrs = {}, text = null) {
  const node = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  if (text != null) node.textContent = text;
  return node;
}

// 1200 -> "1.2K", 15000 -> "15K"
const reviewsText = (n) => (n >= 1e6 ? `${+(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${+(n / 1e3).toFixed(n >= 1e4 ? 0 : 1)}K` : `${Math.round(n)}`);

// describe(g): the hover card's content (a DOM node). axes(): the result's axes in reviews and % positive
// ({demand_log: [lo, hi], rating: [at 0, at 1]}), so the ticks read as the table does.
export function createMap2d(container, { onSelect, describe, axes }) {
  const tooltip = container.querySelector("#tooltip");
  const root = svg("svg", { class: "map2d", role: "img", "aria-label": t("Opportunity map, 2D") });
  container.prepend(root);
  let games = [], selected = null, w = 0, h = 0;
  let dx = [0, 1], dy = [0, 1]; // axis ranges, zoomed to the data

  // Big games all reach ~100% demand, so fixed 0-100% axes pile them into one corner.
  // Zoom each axis to the data, with padding and a minimum span of 25 points.
  function domain(values) {
    if (!values.length) return [0, 1];
    let lo = Math.min(...values) - 0.06, hi = Math.max(...values) + 0.06;
    const grow = Math.max(0, 0.25 - (hi - lo)) / 2;
    lo -= grow; hi += grow;
    if (lo < 0) { hi -= lo; lo = 0; }
    if (hi > 1) { lo = Math.max(0, lo - (hi - 1)); hi = 1; }
    return [lo, hi];
  }
  const scale = ([lo, hi], v) => Math.max(0, Math.min(1, (v - lo) / (hi - lo)));
  const x = (v) => PAD.l + scale(dx, v) * (w - PAD.l - PAD.r);
  const y = (v) => h - PAD.b - scale(dy, v) * (h - PAD.t - PAD.b);

  // Tick labels in the units people know: reviews for demand, % positive for dissatisfaction.
  function xTick(v) {
    const a = axes?.();
    if (!a) return percent(v * 100);
    const [lo, hi] = a.demand_log;
    return reviewsText(10 ** (lo + v * (hi - lo)));
  }
  function yTick(v) {
    const a = axes?.();
    if (!a) return percent(v * 100);
    const [at0, at1] = a.rating;
    return percent(at0 + v * (at1 - at0));
  }

  function showTooltip(e, g) {
    const box = container.getBoundingClientRect();
    tooltip.replaceChildren(describe(g));
    tooltip.hidden = false;
    // keep the card inside the map: flip it to the left of / above the pointer near the edges
    const left = e.clientX - box.left, top = e.clientY - box.top;
    const flipX = left + 16 + tooltip.offsetWidth > box.width, flipY = top + 16 + tooltip.offsetHeight > box.height;
    tooltip.style.left = `${flipX ? left - tooltip.offsetWidth - 32 : left}px`;
    tooltip.style.top = `${flipY ? top - tooltip.offsetHeight - 32 : top}px`;
  }

  function draw() {
    root.setAttribute("viewBox", `0 0 ${w} ${h}`);
    root.replaceChildren();
    if (w < 120 || h < 120) return;

    const [x0, x1] = dx, [y0, y1] = dy;
    // The corner the method looks for: lots of demand, unhappy players.
    const zx = x(x0 + (x1 - x0) * 0.5), zy = y(y1);
    root.append(
      svg("rect", { class: "zone", x: zx, y: zy, width: x(x1) - zx, height: y(y0 + (y1 - y0) * 0.5) - zy, rx: 10 }),
      svg("text", { class: "zone-label", x: x(x1) - 12, y: zy + 22, "text-anchor": "end" }, t("PROVEN DEMAND · POOR EXECUTION")),
    );
    for (let i = 0; i <= 4; i++) {
      const vx = x0 + (i / 4) * (x1 - x0), vy = y0 + (i / 4) * (y1 - y0);
      root.append(
        svg("line", { class: i ? "grid" : "axis", x1: x(x0), x2: x(x1), y1: y(vy), y2: y(vy) }),
        svg("line", { class: i ? "grid" : "axis", x1: x(vx), x2: x(vx), y1: y(y0), y2: y(y1) }),
        svg("text", { class: "tick", x: x(x0) - 10, y: y(vy) + 4, "text-anchor": "end" }, yTick(vy)),
        svg("text", { class: "tick", x: x(vx), y: y(y0) + 20, "text-anchor": "middle" }, xTick(vx)),
      );
    }
    const midY = (y(y0) + y(y1)) / 2;
    root.append(
      svg("text", { class: "axis-label", x: (x(x0) + x(x1)) / 2, y: h - 10, "text-anchor": "middle" }, t("Demand → reviews (log scale)")),
      svg("text", { class: "axis-label", x: 16, y: midY, "text-anchor": "middle", transform: `rotate(-90 16 ${midY})` },
        t("Dissatisfaction ↑ % positive")),
    );

    // Bubble size by revenue, relative within this result.
    // Free-to-play games have no Box Method revenue: smallest bubble, and left out of the scale.
    const grosses = games.map((g) => Math.log10(Math.max(1, g.box.gross_mid)));
    const priced = grosses.filter((_, i) => games[i].price > 0);
    const lo = Math.min(...priced), hi = Math.max(...priced);
    const unit = Math.min(w, h) / 100;
    const size = (i) => (games[i].price > 0 ? (hi > lo ? (grosses[i] - lo) / (hi - lo) : 0.5) : 0);
    const items = games.map((g, i) => ({ g, r: (1.6 + 3.6 * size(i)) * unit }));
    const best = new Set([...games].sort((a, b) => b.opportunity.score - a.opportunity.score).slice(0, NAMED).map((g) => g.game.appid));
    items.sort((a, b) => b.r - a.r); // big ones first, so small ones stay clickable on top

    const names = [];
    for (const { g, r } of items) {
      const o = g.opportunity, appid = g.game.appid;
      const cx = x(o.demand), cy = y(o.dissatisfaction);
      const dot = svg("circle", { class: "bubble", cx, cy, r, fill: mapColor(o.score) });
      dot.addEventListener("pointermove", (e) => showTooltip(e, g));
      dot.addEventListener("pointerleave", () => (tooltip.hidden = true));
      dot.addEventListener("click", () => { select(appid); onSelect(appid); });
      root.append(dot);
      if (appid === selected) root.append(svg("circle", { class: "ring", cx, cy, r: r + 5 }));
      if (appid === selected || best.has(appid)) {
        const right = cx < w - 180; // names go right of the bubble, or left near the right edge
        names.push(svg("text", { class: appid === selected ? "bubble-name picked" : "bubble-name",
          x: right ? cx + r + 6 : cx - r - 6, y: cy + 4, "text-anchor": right ? "start" : "end" }, g.game.name));
      }
    }
    root.append(...names); // on top of every bubble
  }

  function setGames(list) {
    games = list;
    selected = null;
    dx = domain(list.map((g) => g.opportunity.demand));
    dy = domain(list.map((g) => g.opportunity.dissatisfaction));
    container.querySelector("#map-empty").hidden = list.length > 0;
    draw();
  }

  function select(appid) {
    selected = appid;
    draw();
  }

  function setVisible(on) {
    root.style.display = on ? "" : "none";
    if (on) resize();
  }

  function resize() {
    w = container.clientWidth;
    h = container.clientHeight;
    draw();
  }
  new ResizeObserver(resize).observe(container);
  resize();

  function relabel() {
    root.setAttribute("aria-label", t("Opportunity map, 2D"));
    draw();
  }

  return { setGames, select, setVisible, relabel, available: true };
}
