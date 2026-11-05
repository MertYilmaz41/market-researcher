// 2D opportunity map (SVG): x = demand, y = dissatisfaction, size = estimated revenue (log),
// color = opportunity score. Same interface as map3d.js; needs no CDN, so it always works.
import { scoreColor } from "/static/palette.js";
import { fmt, pct, percent, t } from "/static/i18n.js";

const NS = "http://www.w3.org/2000/svg";
const PAD = { l: 58, r: 28, t: 26, b: 46 };

function svg(tag, attrs = {}, text = null) {
  const node = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  if (text != null) node.textContent = text;
  return node;
}

export function createMap2d(container, { onSelect }) {
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

  function showTooltip(e, g) {
    const o = g.opportunity, box = container.getBoundingClientRect();
    tooltip.replaceChildren(
      Object.assign(document.createElement("b"), { textContent: g.game.name }),
      Object.assign(document.createElement("span"), {
        textContent: t("Score {score} · {n} reviews · {pct} pos", { score: Math.round(o.score), n: fmt(g.reviews), pct: percent(g.rating) }),
      }),
      Object.assign(document.createElement("span"), {
        textContent: t("demand {demand} · dissatisfaction {dissatisfaction} · fixability {fixability}",
          { demand: pct(o.demand), dissatisfaction: pct(o.dissatisfaction), fixability: pct(o.fixability) })
          + (o.penalty ? t(" · -{points} risks", { points: Math.round(o.penalty) }) : ""),
      }),
    );
    tooltip.style.left = `${e.clientX - box.left}px`;
    tooltip.style.top = `${e.clientY - box.top}px`;
    tooltip.hidden = false;
  }

  function draw() {
    root.setAttribute("viewBox", `0 0 ${w} ${h}`);
    root.replaceChildren();
    if (w < 120 || h < 120) return;

    const [x0, x1] = dx, [y0, y1] = dy;
    for (let i = 0; i <= 4; i++) {
      const vx = x0 + (i / 4) * (x1 - x0), vy = y0 + (i / 4) * (y1 - y0);
      root.append(
        svg("line", { class: "grid", x1: x(x0), x2: x(x1), y1: y(vy), y2: y(vy) }),
        svg("line", { class: "grid", x1: x(vx), x2: x(vx), y1: y(y0), y2: y(y1) }),
        svg("text", { class: "tick", x: x(x0) - 8, y: y(vy) + 4, "text-anchor": "end" }, pct(vy)),
        svg("text", { class: "tick", x: x(vx), y: y(y0) + 17, "text-anchor": "middle" }, pct(vx)),
      );
    }
    root.append(
      svg("line", { class: "axis demand", x1: x(x0), x2: x(x1), y1: y(y0), y2: y(y0) }),
      svg("line", { class: "axis dissatisfaction", x1: x(x0), x2: x(x0), y1: y(y0), y2: y(y1) }),
      svg("text", { class: "axis-label", x: x(x1), y: h - 8, "text-anchor": "end" }, t("Demand →")),
      svg("text", { class: "axis-label", x: 16, y: y(y1), "text-anchor": "end", transform: `rotate(-90 16 ${y(y1)})` },
        t("Dissatisfaction →")),
      svg("text", { class: "hint", x: x(x1) - 8, y: y(y1) + 16, "text-anchor": "end" }, t("Best opportunities ↗")),
    );

    // Bubble size by revenue, relative within this result (like the 3D spheres).
    const grosses = games.map((g) => Math.log10(Math.max(1, g.box.gross_mid)));
    const lo = Math.min(...grosses), hi = Math.max(...grosses);
    const unit = Math.min(w, h) / 100;
    const items = games.map((g, i) => ({ g, r: (2.4 + 4.6 * (hi > lo ? (grosses[i] - lo) / (hi - lo) : 0.5)) * unit }));
    items.sort((a, b) => b.r - a.r); // big ones first, so small ones stay clickable on top

    let pick = null;
    for (const { g, r } of items) {
      const o = g.opportunity, appid = g.game.appid;
      const dot = svg("circle", { class: "bubble", cx: x(o.demand), cy: y(o.dissatisfaction), r, fill: scoreColor(o.score) });
      dot.addEventListener("pointermove", (e) => showTooltip(e, g));
      dot.addEventListener("pointerleave", () => (tooltip.hidden = true));
      dot.addEventListener("click", () => { select(appid); onSelect(appid); });
      root.append(dot);
      if (appid === selected) pick = { g, r };
    }
    if (pick) {
      const cx = x(pick.g.opportunity.demand), cy = y(pick.g.opportunity.dissatisfaction);
      const below = cy - pick.r - 12 < PAD.t; // no room above: put the name below
      root.append(
        svg("circle", { class: "ring", cx, cy, r: pick.r + 5 }),
        svg("text", { class: "bubble-name", x: cx, y: below ? cy + pick.r + 22 : cy - pick.r - 12,
          "text-anchor": cx > w - 160 ? "end" : cx < 160 ? "start" : "middle" }, pick.g.game.name),
      );
    }
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
